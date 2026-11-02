"""Real-PostgreSQL concurrency races for the Phase 14 authoring commands.

Each test uses separate committed connections and a genuine lock wait (a
second transaction blocks on the first's row lock until it commits), then
verifies the final state from a third connection. Committed fixtures are
removed explicitly afterward.
"""

import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands.campaigns import archive_campaign, create_campaign
from dnd_ai.commands.entity_lifecycle import approve_entity
from dnd_ai.commands.memberships import CampaignNotActiveError, add_campaign_member
from dnd_ai.commands.timelines import (
    LatestPoint,
    archive_timeline,
    create_timeline,
    create_timeline_branch,
)
from dnd_ai.commands.worlds import archive_world, update_world
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER
from dnd_ai.domain.authoring import (
    StaleWriteError,
    TimelineArchivedError,
    WorldArchivedError,
    WorldHasActiveCampaignsError,
)
from tests.builders import (
    dnd5e_ids,
    make_authored_campaign,
    make_authored_world,
    make_world_creator,
)
from tests.factories import make_external_identity, make_location, make_user, oidc_principal

pytestmark = pytest.mark.database


def _purge_user_worlds(engine: Engine, user_id: uuid.UUID) -> None:
    with engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        world_ids = (
            cleanup.execute(
                text("SELECT world_id FROM security.world_memberships WHERE user_id = :u"),
                {"u": user_id},
            )
            .scalars()
            .all()
        )
        for world_id in world_ids:
            cleanup.execute(
                text("DELETE FROM audit.change_log WHERE world_id = :w"), {"w": world_id}
            )
            scoped = (
                "campaign_id IN (SELECT c.campaign_id FROM campaign.campaigns c "
                "JOIN campaign.timelines t ON t.timeline_id = c.timeline_id "
                "WHERE t.world_id = :w)"
            )
            cleanup.execute(
                text(
                    "DELETE FROM security.membership_roles WHERE campaign_membership_id IN "
                    f"(SELECT campaign_membership_id FROM security.campaign_memberships "
                    f"WHERE {scoped})"
                ),
                {"w": world_id},
            )
            cleanup.execute(
                text(f"DELETE FROM security.campaign_memberships WHERE {scoped}"), {"w": world_id}
            )
            cleanup.execute(
                text(f"DELETE FROM security.idempotent_requests WHERE {scoped}"), {"w": world_id}
            )
            cleanup.execute(
                text(
                    "DELETE FROM campaign.session_participants WHERE session_id IN "
                    f"(SELECT session_id FROM campaign.sessions WHERE {scoped})"
                ),
                {"w": world_id},
            )
            cleanup.execute(text(f"DELETE FROM campaign.sessions WHERE {scoped}"), {"w": world_id})
            cleanup.execute(
                text(
                    "DELETE FROM campaign.campaigns WHERE timeline_id IN "
                    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)"
                ),
                {"w": world_id},
            )
            for statement in (
                "DELETE FROM campaign.party_knowledge WHERE timeline_id IN "
                "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)",
                "DELETE FROM campaign.campaign_parties WHERE party_id IN "
                "(SELECT party_id FROM campaign.parties WHERE world_id = :w)",
                "DELETE FROM campaign.objective_state WHERE timeline_id IN "
                "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)",
                "DELETE FROM campaign.quest_state WHERE timeline_id IN "
                "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)",
                "DELETE FROM narrative.event_effects WHERE event_id IN "
                "(SELECT entity_id FROM core.entities WHERE world_id = :w)",
                "DELETE FROM narrative.event_participants WHERE event_id IN "
                "(SELECT entity_id FROM core.entities WHERE world_id = :w)",
                "DELETE FROM narrative.events WHERE event_id IN "
                "(SELECT entity_id FROM core.entities WHERE world_id = :w)",
                "DELETE FROM narrative.quest_objectives WHERE quest_stage_id IN "
                "(SELECT quest_stage_id FROM narrative.quest_stages WHERE quest_id IN "
                "(SELECT entity_id FROM core.entities WHERE world_id = :w))",
                "DELETE FROM narrative.quest_stages WHERE quest_id IN "
                "(SELECT entity_id FROM core.entities WHERE world_id = :w)",
                "DELETE FROM narrative.quests WHERE quest_id IN "
                "(SELECT entity_id FROM core.entities WHERE world_id = :w)",
                # Phase 15 operation state and character records (the purge runs with
                # triggers and foreign keys off, so nothing cascades).
                "DELETE FROM campaign.party_memberships WHERE timeline_id IN (SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)",
                "DELETE FROM campaign.timeline_clocks WHERE timeline_id IN (SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)",
                "DELETE FROM campaign.character_state WHERE timeline_id IN (SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)",
                "DELETE FROM core.entity_revisions WHERE world_id = :w",
                "DELETE FROM character.character_known_spells WHERE character_spellcasting_profile_id IN (SELECT character_spellcasting_profile_id FROM character.character_spellcasting_profiles WHERE character_build_id IN (SELECT character_build_id FROM character.character_builds WHERE character_id IN (SELECT entity_id FROM core.entities WHERE world_id = :w)))",
                "DELETE FROM character.character_prepared_spells WHERE character_spellcasting_profile_id IN (SELECT character_spellcasting_profile_id FROM character.character_spellcasting_profiles WHERE character_build_id IN (SELECT character_build_id FROM character.character_builds WHERE character_id IN (SELECT entity_id FROM core.entities WHERE world_id = :w)))",
                "DELETE FROM character.character_spellcasting_profiles WHERE character_build_id IN (SELECT character_build_id FROM character.character_builds WHERE character_id IN (SELECT entity_id FROM core.entities WHERE world_id = :w))",
                "DELETE FROM character.character_features WHERE character_build_id IN (SELECT character_build_id FROM character.character_builds WHERE character_id IN (SELECT entity_id FROM core.entities WHERE world_id = :w))",
                "DELETE FROM character.character_proficiencies WHERE character_build_id IN (SELECT character_build_id FROM character.character_builds WHERE character_id IN (SELECT entity_id FROM core.entities WHERE world_id = :w))",
                "DELETE FROM character.character_class_levels WHERE character_build_id IN (SELECT character_build_id FROM character.character_builds WHERE character_id IN (SELECT entity_id FROM core.entities WHERE world_id = :w))",
                "DELETE FROM character.character_ability_scores WHERE character_build_id IN (SELECT character_build_id FROM character.character_builds WHERE character_id IN (SELECT entity_id FROM core.entities WHERE world_id = :w))",
                "DELETE FROM character.character_builds WHERE character_id IN (SELECT entity_id FROM core.entities WHERE world_id = :w)",
                "DELETE FROM character.character_descriptions WHERE character_id IN (SELECT entity_id FROM core.entities WHERE world_id = :w)",
                "DELETE FROM character.player_characters WHERE player_character_id IN (SELECT entity_id FROM core.entities WHERE world_id = :w)",
                "DELETE FROM character.npcs WHERE npc_id IN (SELECT entity_id FROM core.entities WHERE world_id = :w)",
                "DELETE FROM character.characters WHERE character_id IN (SELECT entity_id FROM core.entities WHERE world_id = :w)",
                "DELETE FROM campaign.parties WHERE world_id = :w",
                "DELETE FROM knowledge.knowledge_items WHERE knowledge_item_id IN "
                "(SELECT entity_id FROM core.entities WHERE world_id = :w)",
            ):
                cleanup.execute(text(statement), {"w": world_id})
            for subtype, column in (
                ("governments", "government_id"),
                ("businesses", "business_id"),
                ("military_units", "military_unit_id"),
                ("political_factions", "political_faction_id"),
                ("religious_organizations", "religious_organization_id"),
                ("organizations", "organization_id"),
                ("religions", "religion_id"),
                ("settlements", "settlement_id"),
                ("buildings", "building_id"),
            ):
                cleanup.execute(
                    text(
                        f"DELETE FROM world.{subtype} WHERE {column} IN "
                        "(SELECT entity_id FROM core.entities WHERE world_id = :w)"
                    ),
                    {"w": world_id},
                )
            cleanup.execute(
                text(
                    "DELETE FROM world.locations WHERE location_id IN "
                    "(SELECT entity_id FROM core.entities WHERE world_id = :w)"
                ),
                {"w": world_id},
            )
            cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": world_id})
            cleanup.execute(text("DELETE FROM core.sources WHERE world_id = :w"), {"w": world_id})
            cleanup.execute(
                text("DELETE FROM security.world_memberships WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(
                text("DELETE FROM campaign.timelines WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(
                text("DELETE FROM core.world_times WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(
                text("DELETE FROM rules.world_rulesets WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id})
        cleanup.execute(
            text("DELETE FROM security.actor_idempotent_requests WHERE actor_user_id = :u"),
            {"u": user_id},
        )
        cleanup.execute(
            text("DELETE FROM security.campaign_creation_reservations WHERE actor_user_id = :u"),
            {"u": user_id},
        )
        cleanup.execute(
            text("DELETE FROM audit.change_log WHERE actor_user_id = :u"), {"u": user_id}
        )
        cleanup.execute(text("DELETE FROM security.users WHERE user_id = :u"), {"u": user_id})


@pytest.fixture
def committed_owner(postgres_engine: Engine) -> Iterator[uuid.UUID]:
    with postgres_engine.begin() as setup:
        user_id = make_world_creator(setup, make_user(setup, "Race Owner"))
    yield user_id
    _purge_user_worlds(postgres_engine, user_id)


def _wait_until_blocked(engine: Engine, predicate_sql: str, timeout: float = 10.0) -> None:
    """Poll pg_stat_activity (from a third connection) until a backend is
    waiting on a lock matching `predicate_sql`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with engine.connect() as probe:
            waiting = probe.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND " + predicate_sql
                )
            ).scalar()
        if waiting:
            return
        time.sleep(0.05)
    # Release whatever the test is holding (idle-in-transaction sessions) so a
    # failed wait fails fast instead of hanging fixture teardown on a lock.
    with engine.connect() as probe:
        probe.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                "AND state = 'idle in transaction'"
            )
        )
    raise AssertionError("no backend ever blocked on the expected lock")


def test_two_updates_with_the_same_expected_version_one_wins_one_is_stale(
    postgres_engine: Engine, committed_owner: uuid.UUID
) -> None:
    """Race 4: both read version V; the loser blocks on the world row lock
    until the winner commits, then sees V+1 and is rejected."""
    with postgres_engine.begin() as setup:
        world = make_authored_world(setup, owner_user_id=committed_owner, name="Race World")

    winner = postgres_engine.connect()
    winner_tx = winner.begin()
    update_world(
        winner,
        world_id=world.world_id,
        actor_user_id=committed_owner,
        expected_row_version=world.row_version,
        name="Winner",
        description=None,
    )

    outcome: dict[str, object] = {}

    def loser() -> None:
        with postgres_engine.begin() as connection:
            try:
                update_world(
                    connection,
                    world_id=world.world_id,
                    actor_user_id=committed_owner,
                    expected_row_version=world.row_version,
                    name="Loser",
                    description=None,
                )
                outcome["result"] = "ok"
            except StaleWriteError:
                outcome["result"] = "stale"

    thread = threading.Thread(target=loser)
    thread.start()
    _wait_until_blocked(postgres_engine, "query LIKE '%FROM core.worlds w%'")
    winner_tx.commit()
    winner.close()
    thread.join(timeout=15)
    assert not thread.is_alive()

    assert outcome["result"] == "stale"
    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("SELECT name, row_version FROM core.worlds WHERE world_id = :w"),
            {"w": world.world_id},
        ).one()
    assert (row.name, row.row_version) == ("Winner", world.row_version + 1)


def _client_for(engine: Engine, user_id: uuid.UUID) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
    client = TestClient(app, raise_server_exceptions=False)
    client.__enter__()
    return client


def test_two_concurrent_create_world_requests_with_one_key_create_one_world(
    postgres_engine: Engine, committed_owner: uuid.UUID
) -> None:
    """Race 5: the reservation INSERT serializes the two requests on the
    unique index; the second replays the first's stored response."""
    with postgres_engine.connect() as probe:
        ruleset_id, _ = dnd5e_ids(probe)
    body = {
        "name": "Concurrent World",
        "description": None,
        "ruleset_ids": [str(ruleset_id)],
        "default_ruleset_id": str(ruleset_id),
        "primary_timeline": {"name": "T", "description": None},
    }
    clients = [_client_for(postgres_engine, committed_owner) for _ in range(2)]
    barrier = threading.Barrier(2)

    def fire(client: TestClient):  # type: ignore[no-untyped-def]
        barrier.wait()
        return client.post("/worlds", json=body, headers={"Idempotency-Key": "race-create"})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(fire, clients))
    finally:
        for client in clients:
            client.__exit__(None, None, None)

    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    with postgres_engine.connect() as verify:
        worlds = verify.execute(
            text("SELECT count(*) FROM core.worlds WHERE name = 'Concurrent World'")
        ).scalar()
        audits = verify.execute(
            text(
                "SELECT count(*) FROM audit.change_log WHERE command_name = 'create_world' "
                "AND actor_user_id = :u"
            ),
            {"u": committed_owner},
        ).scalar()
    assert worlds == 1
    assert audits == 3


# --- Race 2: archive_timeline vs create_timeline_branch -------------------------------


def _committed_side_timeline(engine: Engine, owner: uuid.UUID):  # type: ignore[no-untyped-def]
    with engine.begin() as setup:
        world = make_authored_world(setup, owner_user_id=owner, name="Race Timeline World")
        side = create_timeline(
            setup,
            world_id=world.world_id,
            actor_user_id=owner,
            name="Side",
            description=None,
        )
    return world, side


def _branch_from(engine: Engine, world, parent: uuid.UUID, owner: uuid.UUID, out: dict) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as connection:
        try:
            create_timeline_branch(
                connection,
                world_id=world.world_id,
                parent_timeline_id=parent,
                actor_user_id=owner,
                name="Racing Branch",
                description=None,
                branch_point=LatestPoint(label="race"),
            )
            out["result"] = "branched"
        except TimelineArchivedError:
            out["result"] = "timeline_archived"


def test_a_branch_waits_for_an_in_flight_archive_and_is_then_refused(
    postgres_engine: Engine, committed_owner: uuid.UUID
) -> None:
    world, side = _committed_side_timeline(postgres_engine, committed_owner)
    archiver = postgres_engine.connect()
    tx = archiver.begin()
    archive_timeline(
        archiver,
        world_id=world.world_id,
        timeline_id=side.timeline_id,
        actor_user_id=committed_owner,
        expected_row_version=side.row_version,
    )
    out: dict[str, object] = {}
    thread = threading.Thread(
        target=_branch_from, args=(postgres_engine, world, side.timeline_id, committed_owner, out)
    )
    thread.start()
    _wait_until_blocked(postgres_engine, "query LIKE '%FOR SHARE OF t%'")
    tx.commit()
    archiver.close()
    thread.join(timeout=15)

    assert out["result"] == "timeline_archived"
    with postgres_engine.connect() as verify:
        branches = verify.execute(
            text("SELECT count(*) FROM campaign.timelines WHERE name = 'Racing Branch'")
        ).scalar()
    assert branches == 0


def test_an_archive_waits_for_an_in_flight_branch_and_leaves_it_intact(
    postgres_engine: Engine, committed_owner: uuid.UUID
) -> None:
    world, side = _committed_side_timeline(postgres_engine, committed_owner)
    brancher = postgres_engine.connect()
    tx = brancher.begin()
    create_timeline_branch(
        brancher,
        world_id=world.world_id,
        parent_timeline_id=side.timeline_id,
        actor_user_id=committed_owner,
        name="Racing Branch",
        description=None,
        branch_point=LatestPoint(label="race"),
    )
    out: dict[str, object] = {}

    def archive() -> None:
        with postgres_engine.begin() as connection:
            archive_timeline(
                connection,
                world_id=world.world_id,
                timeline_id=side.timeline_id,
                actor_user_id=committed_owner,
                expected_row_version=side.row_version,
            )
            out["result"] = "archived"

    thread = threading.Thread(target=archive)
    thread.start()
    _wait_until_blocked(postgres_engine, "query LIKE '%FOR UPDATE OF t%'")
    tx.commit()
    brancher.close()
    thread.join(timeout=15)

    assert out["result"] == "archived"
    with postgres_engine.connect() as verify:
        rows = verify.execute(
            text("""
                SELECT t.name, ls.code FROM campaign.timelines t
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = t.lifecycle_status_id
                WHERE t.world_id = :w AND t.name IN ('Side', 'Racing Branch') ORDER BY t.name
            """),
            {"w": world.world_id},
        ).all()
    assert [(r.name, r.code) for r in rows] == [("Racing Branch", "active"), ("Side", "archived")]


# --- Race 1: archive_world vs create_campaign ------------------------------------------


def _committed_world(engine: Engine, owner: uuid.UUID):  # type: ignore[no-untyped-def]
    with engine.begin() as setup:
        return make_authored_world(setup, owner_user_id=owner, name="Race Campaign World")


def _create_campaign_racing(engine: Engine, world, owner: uuid.UUID, out: dict) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as connection:
        try:
            create_campaign(
                connection,
                timeline_id=world.primary_timeline_id,
                ruleset_version_id=world.ruleset_version_id,
                name="Racing Campaign",
                creator_user_id=owner,
            )
            out["result"] = "created"
        except WorldArchivedError:
            out["result"] = "world_archived"


def test_a_campaign_creation_waits_for_an_in_flight_world_archive_and_is_refused(
    postgres_engine: Engine, committed_owner: uuid.UUID
) -> None:
    world = _committed_world(postgres_engine, committed_owner)
    archiver = postgres_engine.connect()
    tx = archiver.begin()
    archive_world(
        archiver,
        world_id=world.world_id,
        actor_user_id=committed_owner,
        expected_row_version=world.row_version,
    )
    out: dict[str, object] = {}
    thread = threading.Thread(
        target=_create_campaign_racing, args=(postgres_engine, world, committed_owner, out)
    )
    thread.start()
    _wait_until_blocked(postgres_engine, "query LIKE '%FOR SHARE%'")
    tx.commit()
    archiver.close()
    thread.join(timeout=15)

    assert out["result"] == "world_archived"
    with postgres_engine.connect() as verify:
        campaigns = verify.execute(
            text("SELECT count(*) FROM campaign.campaigns WHERE name = 'Racing Campaign'")
        ).scalar()
    assert campaigns == 0


def test_a_world_archive_waits_for_an_in_flight_campaign_creation_and_is_then_refused(
    postgres_engine: Engine, committed_owner: uuid.UUID
) -> None:
    world = _committed_world(postgres_engine, committed_owner)
    creator = postgres_engine.connect()
    tx = creator.begin()
    create_campaign(
        creator,
        timeline_id=world.primary_timeline_id,
        ruleset_version_id=world.ruleset_version_id,
        name="Racing Campaign",
        creator_user_id=committed_owner,
    )
    out: dict[str, object] = {}

    def archive() -> None:
        with postgres_engine.begin() as connection:
            try:
                archive_world(
                    connection,
                    world_id=world.world_id,
                    actor_user_id=committed_owner,
                    expected_row_version=world.row_version,
                )
                out["result"] = "archived"
            except WorldHasActiveCampaignsError:
                out["result"] = "world_has_active_campaigns"

    thread = threading.Thread(target=archive)
    thread.start()
    _wait_until_blocked(postgres_engine, "query LIKE '%FOR UPDATE OF w%'")
    tx.commit()
    creator.close()
    thread.join(timeout=15)

    assert out["result"] == "world_has_active_campaigns"
    with postgres_engine.connect() as verify:
        status = verify.execute(
            text("""
                SELECT ls.code FROM core.worlds w
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = w.lifecycle_status_id
                WHERE w.world_id = :w
            """),
            {"w": world.world_id},
        ).scalar()
    assert status == "active"


# --- Race 6: archive_campaign vs add_campaign_member --------------------------------------


def test_adding_a_member_waits_for_an_in_flight_archive_and_is_then_refused(
    postgres_engine: Engine, committed_owner: uuid.UUID
) -> None:
    world = _committed_world(postgres_engine, committed_owner)
    with postgres_engine.begin() as setup:
        created = create_campaign(
            setup,
            timeline_id=world.primary_timeline_id,
            ruleset_version_id=world.ruleset_version_id,
            name="Archive Race",
            creator_user_id=committed_owner,
        )
        invitee = make_user(setup, "Late Joiner")
        make_external_identity(
            setup, invitee, issuer=LOCAL_AUTH_ISSUER, subject=f"late-{uuid.uuid4().hex[:8]}"
        )
        player_role = setup.execute(
            text("SELECT role_id FROM security.roles WHERE code = 'player' AND campaign_id IS NULL")
        ).scalar()
        version = setup.execute(
            text("SELECT row_version FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": created.campaign_id},
        ).scalar()

    archiver = postgres_engine.connect()
    tx = archiver.begin()
    archive_campaign(
        archiver,
        campaign_id=created.campaign_id,
        actor_user_id=committed_owner,
        expected_row_version=version,
    )
    out: dict[str, object] = {}

    def add_member() -> None:
        with postgres_engine.begin() as connection:
            try:
                add_campaign_member(
                    connection,
                    campaign_id=created.campaign_id,
                    user_id=invitee,
                    role_id=player_role,
                    added_by_membership_id=created.campaign_membership_id,
                )
                out["result"] = "added"
            except CampaignNotActiveError:
                out["result"] = "campaign_not_active"

    thread = threading.Thread(target=add_member)
    thread.start()
    _wait_until_blocked(
        postgres_engine, "query LIKE '%FOR UPDATE%' AND query LIKE '%campaign.campaigns%'"
    )
    tx.commit()
    archiver.close()
    thread.join(timeout=15)

    assert out["result"] == "campaign_not_active"
    with postgres_engine.connect() as verify:
        members = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u"
            ),
            {"c": created.campaign_id, "u": invitee},
        ).scalar()
    assert members == 0
    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.external_identities WHERE user_id = :u"), {"u": invitee}
        )
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(text("DELETE FROM security.users WHERE user_id = :u"), {"u": invitee})


# --- Race 3: two approvals with the same expected version -------------------------------


def test_two_approvals_with_the_same_expected_version_one_wins_one_is_stale(
    postgres_engine: Engine, committed_owner: uuid.UUID
) -> None:
    world = _committed_world(postgres_engine, committed_owner)
    with postgres_engine.begin() as setup:
        campaign = make_authored_campaign(setup, world)
        place = make_location(setup, world.world_id, name="Contested")
        setup.execute(
            text(
                "UPDATE core.entities SET canon_status_id = (SELECT canon_status_id FROM "
                "core.canon_statuses WHERE code = 'proposed') WHERE entity_id = :e"
            ),
            {"e": place},
        )
        version = setup.execute(
            text("SELECT row_version FROM core.entities WHERE entity_id = :e"), {"e": place}
        ).scalar()

    first = postgres_engine.connect()
    tx = first.begin()
    approve_entity(
        first,
        campaign_id=campaign,
        entity_id=place,
        actor_user_id=committed_owner,
        expected_row_version=version,
    )
    out: dict[str, object] = {}

    def second() -> None:
        with postgres_engine.begin() as connection:
            try:
                approve_entity(
                    connection,
                    campaign_id=campaign,
                    entity_id=place,
                    actor_user_id=committed_owner,
                    expected_row_version=version,
                )
                out["result"] = "approved"
            except StaleWriteError:
                out["result"] = "stale"

    thread = threading.Thread(target=second)
    thread.start()
    _wait_until_blocked(postgres_engine, "query LIKE '%FOR UPDATE OF e%'")
    tx.commit()
    first.close()
    thread.join(timeout=15)

    assert out["result"] == "stale"
    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT cs.code, e.row_version FROM core.entities e "
                "JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id "
                "WHERE e.entity_id = :e"
            ),
            {"e": place},
        ).one()
    assert (row.code, row.row_version) == ("approved", version + 1)
