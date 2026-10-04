"""Real-PostgreSQL concurrency races for typed Location authoring (Phase 15.1).

Separate committed connections and a genuine lock wait: a *holder* transaction
runs a command and stays uncommitted, a *racer* thread issues the competing
command and blocks on the holder's row lock, then the holder commits and the
racer's outcome is checked. Nothing here is mocked. Committed fixtures are
purged by `tests/database/test_authoring_concurrency._purge_user_worlds`.
"""

import threading
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.campaigns import archive_campaign
from dnd_ai.commands.entity_lifecycle import (
    approve_entity,
    archive_entity,
    delete_draft_entity,
    publish_entity_as_canon,
    submit_entity_for_review,
)
from dnd_ai.commands.knowledge import _reveal_knowledge_to_party_impl
from dnd_ai.commands.knowledge_definitions import create_knowledge_item, update_knowledge_item
from dnd_ai.commands.locations import create_location, update_location
from dnd_ai.commands.memberships import revoke_membership_role
from dnd_ai.commands.organizations import create_organization, update_organization
from dnd_ai.commands.quest_definitions import (
    add_quest_objective,
    add_quest_stage,
    create_quest,
    remove_quest_objective,
    update_quest_stage,
)
from dnd_ai.commands.quests import _advance_objective_impl
from dnd_ai.domain.authoring import (
    CampaignArchivedError,
    CampaignNotAuthorizedError,
    EntityReferencedError,
    HeadquartersLocationInvalidError,
    KnowledgeAlreadyKnownError,
    LocationHierarchyCycleError,
    OrganizationHierarchyCycleError,
    ParentLocationInvalidError,
    QuestHasProgressError,
    StaleWriteError,
)
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import (
    _client_for,
    _purge_user_worlds,
    _wait_until_blocked,
)
from tests.factories import make_campaign_party, make_party, make_user, make_world_time

pytestmark = pytest.mark.database

ENTITY_LOCK = "query LIKE '%FOR UPDATE OF e%' OR query LIKE '%FOR SHARE OF e%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    world_id: uuid.UUID
    campaign_id: uuid.UUID
    campaign_version: int

    def location(
        self, name: str, category: str = "region", parent: uuid.UUID | None = None
    ) -> tuple[uuid.UUID, int]:
        with self.engine.begin() as connection:
            result = create_location(
                connection,
                campaign_id=self.campaign_id,
                actor_user_id=self.owner,
                category_code=category,
                name=name,
                summary=None,
                parent_location_id=parent,
            )
        return result.entity_id, result.row_version

    def version(self, entity_id: uuid.UUID) -> int:
        with self.engine.connect() as connection:
            value = connection.execute(
                text("SELECT row_version FROM core.entities WHERE entity_id = :e"),
                {"e": entity_id},
            ).scalar()
        assert isinstance(value, int)
        return value

    def parent(self, entity_id: uuid.UUID) -> uuid.UUID | None:
        with self.engine.connect() as connection:
            return connection.execute(
                text("SELECT parent_location_id FROM world.locations WHERE location_id = :e"),
                {"e": entity_id},
            ).scalar()

    def count(self, sql: str, **params: Any) -> int:
        with self.engine.connect() as connection:
            value = connection.execute(text(sql), params).scalar()
        assert isinstance(value, int)
        return value

    def update(
        self,
        connection: Connection,
        entity_id: uuid.UUID,
        version: int,
        *,
        name: str = "Edited",
        parent: uuid.UUID | None = None,
    ) -> Any:
        return update_location(
            connection,
            campaign_id=self.campaign_id,
            location_id=entity_id,
            actor_user_id=self.owner,
            expected_row_version=version,
            name=name,
            summary=None,
            parent_location_id=parent,
        )


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Content Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Content Race World")
        campaign_id = make_authored_campaign(setup, world, name="Content Race Campaign")
        version = setup.execute(
            text("SELECT row_version FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": campaign_id},
        ).scalar()
    assert isinstance(version, int)
    yield Fixture(postgres_engine, owner, world.world_id, campaign_id, version)
    _purge_user_worlds(postgres_engine, owner)


def race(
    engine: Engine,
    hold: Callable[[Connection], object],
    racer: Callable[[Connection], object],
    blocked_on: str,
) -> dict[str, Any]:
    """Run `hold` in an uncommitted transaction, start `racer` in a thread, wait
    until it is blocked on a lock, commit the holder, and return the racer's
    `{"value": ...}` or `{"error": exception}`."""
    out: dict[str, Any] = {}

    def run() -> None:
        try:
            with engine.begin() as connection:
                out["value"] = racer(connection)
        except Exception as exc:  # the racer's classified failure is the datum
            out["error"] = exc

    holder = engine.connect()
    tx = holder.begin()
    try:
        hold(holder)
        thread = threading.Thread(target=run)
        thread.start()
        _wait_until_blocked(engine, blocked_on)
        tx.commit()
    except BaseException:
        tx.rollback()
        raise
    finally:
        holder.close()
    thread.join(timeout=20)
    assert not thread.is_alive()
    return out


# --- edit vs edit / archive / publish / submit ---------------------------------------


def test_two_edits_with_one_expected_version_one_wins_one_is_stale(fx: Fixture) -> None:
    place, version = fx.location("Race")
    out = race(
        fx.engine,
        lambda c: fx.update(c, place, version, name="Winner"),
        lambda c: fx.update(c, place, version, name="Loser"),
        ENTITY_LOCK,
    )
    assert isinstance(out["error"], StaleWriteError)
    with fx.engine.connect() as verify:
        name = verify.execute(
            text("SELECT canonical_name FROM core.entities WHERE entity_id = :e"), {"e": place}
        ).scalar()
    assert name == "Winner"


def test_an_edit_waits_for_an_in_flight_archive_and_is_then_stale(fx: Fixture) -> None:
    place, version = fx.location("Archived under it")
    out = race(
        fx.engine,
        lambda c: archive_entity(
            c,
            campaign_id=fx.campaign_id,
            entity_id=place,
            actor_user_id=fx.owner,
            expected_row_version=version,
        ),
        lambda c: fx.update(c, place, version),
        ENTITY_LOCK,
    )
    assert isinstance(out["error"], StaleWriteError)
    assert (
        fx.count("SELECT count(*) FROM audit.change_log WHERE command_name = 'update_location'")
        == 0
    )


def test_an_archive_waits_for_an_in_flight_edit_and_is_then_stale(fx: Fixture) -> None:
    place, version = fx.location("Edited under it")
    out = race(
        fx.engine,
        lambda c: fx.update(c, place, version),
        lambda c: archive_entity(
            c,
            campaign_id=fx.campaign_id,
            entity_id=place,
            actor_user_id=fx.owner,
            expected_row_version=version,
        ),
        ENTITY_LOCK,
    )
    assert isinstance(out["error"], StaleWriteError)


def test_an_edit_waits_for_an_in_flight_publish_and_is_then_stale(fx: Fixture) -> None:
    place, version = fx.location("Publishing")
    for command in (submit_entity_for_review, approve_entity):
        with fx.engine.begin() as connection:
            command(
                connection,
                campaign_id=fx.campaign_id,
                entity_id=place,
                actor_user_id=fx.owner,
                expected_row_version=version,
            )
        version = fx.version(place)
    out = race(
        fx.engine,
        lambda c: publish_entity_as_canon(
            c,
            campaign_id=fx.campaign_id,
            entity_id=place,
            actor_user_id=fx.owner,
            expected_row_version=version,
        ),
        lambda c: fx.update(c, place, version),
        ENTITY_LOCK,
    )
    assert isinstance(out["error"], StaleWriteError)


def test_a_submit_for_review_waits_for_an_in_flight_edit_and_is_then_stale(fx: Fixture) -> None:
    place, version = fx.location("Edit then submit")
    out = race(
        fx.engine,
        lambda c: fx.update(c, place, version),
        lambda c: submit_entity_for_review(
            c,
            campaign_id=fx.campaign_id,
            entity_id=place,
            actor_user_id=fx.owner,
            expected_row_version=version,
        ),
        ENTITY_LOCK,
    )
    assert isinstance(out["error"], StaleWriteError)


# --- hierarchy ---------------------------------------------------------------------------


def test_opposing_reparents_serialize_and_the_second_is_a_cycle(fx: Fixture) -> None:
    a, a_version = fx.location("A")
    b, b_version = fx.location("B")
    out = race(
        fx.engine,
        lambda c: fx.update(c, a, a_version, name="A", parent=b),
        lambda c: fx.update(c, b, b_version, name="B", parent=a),
        ENTITY_LOCK,
    )
    assert isinstance(out["error"], LocationHierarchyCycleError)
    assert fx.parent(a) == b and fx.parent(b) is None


def test_three_concurrent_reparents_never_commit_a_cycle(fx: Fixture) -> None:
    ids = [fx.location(name) for name in ("N1", "N2", "N3")]
    pairs = [(ids[0], ids[1]), (ids[1], ids[2]), (ids[2], ids[0])]
    barrier = threading.Barrier(3)

    def move(pair: tuple[tuple[uuid.UUID, int], tuple[uuid.UUID, int]]) -> str:
        (child, version), (parent, _) = pair
        barrier.wait()
        try:
            with fx.engine.begin() as connection:
                fx.update(connection, child, version, name="Moved", parent=parent)
            return "moved"
        except LocationHierarchyCycleError:
            return "cycle"

    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(move, pairs))
    assert sorted(outcomes) == ["cycle", "moved", "moved"]
    with fx.engine.connect() as verify:
        found = verify.execute(
            text("""
                WITH RECURSIVE walk AS (
                    SELECT location_id, parent_location_id FROM world.locations
                    WHERE location_id = ANY(CAST(:ids AS uuid[]))
                    UNION
                    SELECT l.location_id, l.parent_location_id
                    FROM world.locations l JOIN walk w ON l.location_id = w.parent_location_id
                )
                CYCLE location_id SET is_cycle USING path
                SELECT bool_or(is_cycle) FROM walk
            """),
            {"ids": [i for i, _ in ids]},
        ).scalar()
    assert not found


def test_a_child_waits_for_an_in_flight_parent_archive_and_is_refused(fx: Fixture) -> None:
    parent, parent_version = fx.location("Parent")
    out = race(
        fx.engine,
        lambda c: archive_entity(
            c,
            campaign_id=fx.campaign_id,
            entity_id=parent,
            actor_user_id=fx.owner,
            expected_row_version=parent_version,
        ),
        lambda c: create_location(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            category_code="region",
            name="Orphan",
            summary=None,
            parent_location_id=parent,
        ),
        ENTITY_LOCK,
    )
    assert isinstance(out["error"], ParentLocationInvalidError)
    assert fx.count("SELECT count(*) FROM core.entities WHERE canonical_name = 'Orphan'") == 0


def test_a_parent_archive_waits_for_an_in_flight_child_and_leaves_it_intact(fx: Fixture) -> None:
    parent, parent_version = fx.location("Parent")
    out = race(
        fx.engine,
        lambda c: create_location(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            category_code="region",
            name="Child",
            summary=None,
            parent_location_id=parent,
        ),
        lambda c: archive_entity(
            c,
            campaign_id=fx.campaign_id,
            entity_id=parent,
            actor_user_id=fx.owner,
            expected_row_version=parent_version,
        ),
        ENTITY_LOCK,
    )
    assert "error" not in out
    with fx.engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT l.parent_location_id, ls.code FROM core.entities c
                JOIN world.locations l ON l.location_id = c.entity_id
                JOIN core.entities p ON p.entity_id = l.parent_location_id
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = p.lifecycle_status_id
                WHERE c.canonical_name = 'Child'
            """)
        ).one()
    assert (row.parent_location_id, row.code) == (parent, "archived")


def test_a_child_waits_for_an_in_flight_draft_delete_and_is_refused(fx: Fixture) -> None:
    parent, parent_version = fx.location("Doomed parent")
    out = race(
        fx.engine,
        lambda c: delete_draft_entity(
            c,
            campaign_id=fx.campaign_id,
            entity_id=parent,
            actor_user_id=fx.owner,
            expected_row_version=parent_version,
            reason="mistake",
        ),
        lambda c: create_location(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            category_code="region",
            name="Child of nothing",
            summary=None,
            parent_location_id=parent,
        ),
        ENTITY_LOCK,
    )
    assert isinstance(out["error"], ParentLocationInvalidError)


def test_a_draft_delete_waits_for_an_in_flight_child_and_is_then_blocked(fx: Fixture) -> None:
    parent, parent_version = fx.location("Parent with child")
    out = race(
        fx.engine,
        lambda c: create_location(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            category_code="region",
            name="Late child",
            summary=None,
            parent_location_id=parent,
        ),
        lambda c: delete_draft_entity(
            c,
            campaign_id=fx.campaign_id,
            entity_id=parent,
            actor_user_id=fx.owner,
            expected_row_version=parent_version,
            reason="mistake",
        ),
        ENTITY_LOCK,
    )
    assert isinstance(out["error"], EntityReferencedError)
    assert (
        fx.count("SELECT count(*) FROM core.entities WHERE canonical_name = 'Parent with child'")
        == 1
    )


# --- scope and authority -------------------------------------------------------------------


def _deputy(fx: Fixture) -> tuple[uuid.UUID, uuid.UUID]:
    """A second `campaign_owner` member; returns `(user_id, membership_role_id)`."""
    with fx.engine.begin() as setup:
        user = make_user(setup, "Deputy GM")
        setup.execute(
            text("""
                INSERT INTO security.campaign_memberships
                    (campaign_id, user_id, membership_status_id, joined_at)
                VALUES (:c, :u, (SELECT membership_status_id FROM security.membership_statuses
                                 WHERE code = 'active'), now())
            """),
            {"c": fx.campaign_id, "u": user},
        )
        role = setup.execute(
            text("""
                INSERT INTO security.membership_roles (campaign_membership_id, role_id)
                SELECT cm.campaign_membership_id, r.role_id
                FROM security.campaign_memberships cm, security.roles r
                WHERE cm.campaign_id = :c AND cm.user_id = :u
                  AND r.code = 'campaign_owner' AND r.campaign_id IS NULL
                RETURNING membership_role_id
            """),
            {"c": fx.campaign_id, "u": user},
        ).scalar()
    assert isinstance(role, uuid.UUID)
    return user, role


def _create_as(fx: Fixture, user: uuid.UUID, name: str) -> Callable[[Connection], Any]:
    return lambda c: create_location(
        c,
        campaign_id=fx.campaign_id,
        actor_user_id=user,
        category_code="region",
        name=name,
        summary=None,
    )


def test_a_creation_waits_for_an_in_flight_role_revocation_and_is_refused(fx: Fixture) -> None:
    deputy, role = _deputy(fx)
    try:
        out = race(
            fx.engine,
            lambda c: revoke_membership_role(
                c, membership_role_id=role, campaign_id=fx.campaign_id
            ),
            _create_as(fx, deputy, "After revocation"),
            "query LIKE '%FOR SHARE OF mr, cm%'",
        )
        assert isinstance(out["error"], CampaignNotAuthorizedError)
        assert (
            fx.count("SELECT count(*) FROM core.entities WHERE canonical_name = 'After revocation'")
            == 0
        )
    finally:
        _drop_user(fx.engine, deputy)


def test_a_role_revocation_waits_for_an_in_flight_creation_and_the_write_stands(
    fx: Fixture,
) -> None:
    deputy, role = _deputy(fx)
    try:
        out = race(
            fx.engine,
            _create_as(fx, deputy, "Before revocation"),
            lambda c: revoke_membership_role(
                c, membership_role_id=role, campaign_id=fx.campaign_id
            ),
            "query LIKE '%FOR UPDATE OF mr%'",
        )
        assert "error" not in out
        assert (
            fx.count(
                "SELECT count(*) FROM core.entities WHERE canonical_name = 'Before revocation'"
            )
            == 1
        )
    finally:
        _drop_user(fx.engine, deputy)


def test_a_creation_waits_for_an_in_flight_campaign_archive_and_is_refused(fx: Fixture) -> None:
    out = race(
        fx.engine,
        lambda c: archive_campaign(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            expected_row_version=fx.campaign_version,
        ),
        _create_as(fx, fx.owner, "Too late"),
        "query LIKE '%FROM campaign.campaigns WHERE campaign_id = %FOR SHARE%'",
    )
    assert isinstance(out["error"], CampaignArchivedError)
    assert fx.count("SELECT count(*) FROM core.entities WHERE canonical_name = 'Too late'") == 0


def _drop_user(engine: Engine, user_id: uuid.UUID) -> None:
    with engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text(
                "DELETE FROM security.membership_roles WHERE campaign_membership_id IN "
                "(SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE user_id = :u)"
            ),
            {"u": user_id},
        )
        cleanup.execute(
            text("DELETE FROM security.campaign_memberships WHERE user_id = :u"), {"u": user_id}
        )
        cleanup.execute(
            text("DELETE FROM audit.change_log WHERE actor_user_id = :u"), {"u": user_id}
        )
        cleanup.execute(
            text(
                "UPDATE core.entities SET created_by_user_id = NULL WHERE created_by_user_id = :u"
            ),
            {"u": user_id},
        )
        cleanup.execute(
            text("UPDATE core.sources SET created_by_user_id = NULL WHERE created_by_user_id = :u"),
            {"u": user_id},
        )
        cleanup.execute(text("DELETE FROM security.users WHERE user_id = :u"), {"u": user_id})


# --- idempotency ----------------------------------------------------------------------------


def test_two_identical_creations_with_one_key_create_one_location(fx: Fixture) -> None:
    body = {"category": "region", "name": "Concurrent Place"}
    clients = [_client_for(fx.engine, fx.owner) for _ in range(2)]
    barrier = threading.Barrier(2)
    path = f"/campaigns/{fx.campaign_id}/authoring/locations"

    def fire(client: TestClient) -> Any:
        barrier.wait()
        return client.post(path, json=body, headers={"Idempotency-Key": "loc-race"})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(fire, clients))
    finally:
        for client in clients:
            client.__exit__(None, None, None)
    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    assert (
        fx.count("SELECT count(*) FROM core.entities WHERE canonical_name = 'Concurrent Place'")
        == 1
    )
    assert (
        fx.count("SELECT count(*) FROM audit.change_log WHERE command_name = 'create_location'")
        == 1
    )


def test_creations_with_different_keys_and_the_same_name_both_succeed(fx: Fixture) -> None:
    barrier = threading.Barrier(2)

    def create(_: int) -> uuid.UUID:
        barrier.wait()
        with fx.engine.begin() as connection:
            return create_location(
                connection,
                campaign_id=fx.campaign_id,
                actor_user_id=fx.owner,
                category_code="region",
                name="Twin",
                summary=None,
            ).entity_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(create, range(2)))
    assert len(set(ids)) == 2


# --- organizations --------------------------------------------------------------------------------


def _organization(fx: Fixture, name: str, parent: uuid.UUID | None = None) -> tuple[uuid.UUID, int]:
    with fx.engine.begin() as connection:
        result = create_organization(
            connection,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            kind_code="government",
            name=name,
            summary=None,
            parent_organization_id=parent,
            typed_fields={},
        )
    return result.entity_id, result.row_version


def _reparent_organization(
    fx: Fixture, connection: Connection, org: uuid.UUID, version: int, parent: uuid.UUID
) -> Any:
    return update_organization(
        connection,
        campaign_id=fx.campaign_id,
        organization_id=org,
        actor_user_id=fx.owner,
        expected_row_version=version,
        name="Moved",
        summary=None,
        parent_organization_id=parent,
        typed_fields={},
    )


def test_opposing_organization_reparents_serialize_and_the_second_is_a_cycle(fx: Fixture) -> None:
    a, a_version = _organization(fx, "OA")
    b, b_version = _organization(fx, "OB")
    out = race(
        fx.engine,
        lambda c: _reparent_organization(fx, c, a, a_version, b),
        lambda c: _reparent_organization(fx, c, b, b_version, a),
        ENTITY_LOCK,
    )
    assert isinstance(out["error"], OrganizationHierarchyCycleError)


def test_an_organization_headquarters_archive_wins_over_a_waiting_assignment(fx: Fixture) -> None:
    hq, hq_version = fx.location("Keep", "building")
    out = race(
        fx.engine,
        lambda c: archive_entity(
            c,
            campaign_id=fx.campaign_id,
            entity_id=hq,
            actor_user_id=fx.owner,
            expected_row_version=hq_version,
        ),
        lambda c: create_organization(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            kind_code="government",
            name="Garrison",
            summary=None,
            headquarters_location_id=hq,
            typed_fields={},
        ),
        ENTITY_LOCK,
    )
    assert isinstance(out["error"], HeadquartersLocationInvalidError)
    assert fx.count("SELECT count(*) FROM core.entities WHERE canonical_name = 'Garrison'") == 0


# --- quests -----------------------------------------------------------------------------------------


@dataclass
class CommittedQuest:
    quest_id: uuid.UUID
    version: int
    stage_id: uuid.UUID
    objective_id: uuid.UUID
    timeline_id: uuid.UUID
    world_time_id: uuid.UUID


def _published_quest(fx: Fixture) -> CommittedQuest:
    with fx.engine.begin() as c:
        quest = create_quest(
            c, campaign_id=fx.campaign_id, actor_user_id=fx.owner, name="Race quest", summary=None
        )
        stage = add_quest_stage(
            c,
            campaign_id=fx.campaign_id,
            quest_id=quest.entity_id,
            actor_user_id=fx.owner,
            expected_row_version=quest.row_version,
            name="Stage",
            description=None,
            stage_type="sequential",
        )
        assert stage.record_id is not None
        objective = add_quest_objective(
            c,
            campaign_id=fx.campaign_id,
            quest_id=quest.entity_id,
            quest_stage_id=stage.record_id,
            actor_user_id=fx.owner,
            expected_row_version=stage.row_version,
            name="Objective",
            description=None,
            objective_type="other",
            requirement_level="required",
            completion_mode="automatic",
            visibility_policy="visible",
            quantity_required=None,
            target_entity_id=None,
        )
        assert objective.record_id is not None
        timeline = c.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": fx.campaign_id},
        ).scalar()
        when = make_world_time(c, fx.world_id, 10)
    for command in (submit_entity_for_review, approve_entity, publish_entity_as_canon):
        with fx.engine.begin() as c:
            command(
                c,
                campaign_id=fx.campaign_id,
                entity_id=quest.entity_id,
                actor_user_id=fx.owner,
                expected_row_version=fx.version(quest.entity_id),
            )
    return CommittedQuest(
        quest_id=quest.entity_id,
        version=fx.version(quest.entity_id),
        stage_id=stage.record_id,
        objective_id=objective.record_id,
        timeline_id=timeline,
        world_time_id=when,
    )


def _advance(fx: Fixture, q: CommittedQuest) -> Callable[[Connection], Any]:
    return lambda c: _advance_objective_impl(
        c,
        quest_objective_id=q.objective_id,
        timeline_id=q.timeline_id,
        world_time_id=q.world_time_id,
        new_status_code="completed",
        campaign_id=fx.campaign_id,
    )


def _remove_objective(fx: Fixture, q: CommittedQuest) -> Callable[[Connection], Any]:
    return lambda c: remove_quest_objective(
        c,
        campaign_id=fx.campaign_id,
        quest_id=q.quest_id,
        quest_stage_id=q.stage_id,
        quest_objective_id=q.objective_id,
        actor_user_id=fx.owner,
        expected_row_version=q.version,
    )


def test_a_structural_edit_waits_for_an_in_flight_first_progress_write_and_is_refused(
    fx: Fixture,
) -> None:
    q = _published_quest(fx)
    out = race(fx.engine, _advance(fx, q), _remove_objective(fx, q), ENTITY_LOCK)
    assert isinstance(out["error"], QuestHasProgressError)
    assert (
        fx.count(
            "SELECT count(*) FROM narrative.quest_objectives WHERE quest_stage_id = :s",
            s=q.stage_id,
        )
        == 1
    )
    assert (
        fx.count(
            "SELECT count(*) FROM campaign.objective_state WHERE quest_objective_id = :o",
            o=q.objective_id,
        )
        == 1
    )


def test_a_first_progress_write_waits_for_an_in_flight_structural_edit_and_finds_it_gone(
    fx: Fixture,
) -> None:
    q = _published_quest(fx)
    out = race(fx.engine, _remove_objective(fx, q), _advance(fx, q), ENTITY_LOCK)
    assert isinstance(out["error"], ValueError)
    assert "does not exist" in str(out["error"])
    assert (
        fx.count(
            "SELECT count(*) FROM campaign.objective_state WHERE quest_objective_id = :o",
            o=q.objective_id,
        )
        == 0
    )
    assert (
        fx.count("SELECT count(*) FROM narrative.events WHERE timeline_id = :t", t=q.timeline_id)
        == 0
    )


def test_two_editors_of_the_same_quest_serialize_and_the_second_is_stale(fx: Fixture) -> None:
    q = _published_quest(fx)

    def rename(c: Connection) -> Any:
        return update_quest_stage(
            c,
            campaign_id=fx.campaign_id,
            quest_id=q.quest_id,
            quest_stage_id=q.stage_id,
            actor_user_id=fx.owner,
            expected_row_version=q.version,
            name="Renamed",
            description=None,
            stage_type="sequential",
        )

    out = race(fx.engine, rename, rename, ENTITY_LOCK)
    assert isinstance(out["error"], StaleWriteError)


# --- knowledge claims ----------------------------------------------------------------------------


@dataclass
class CommittedClaim:
    knowledge_item_id: uuid.UUID
    version: int
    party_id: uuid.UUID
    timeline_id: uuid.UUID
    world_time_id: uuid.UUID


def _published_claim(fx: Fixture) -> CommittedClaim:
    with fx.engine.begin() as c:
        claim = create_knowledge_item(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            statement="The duke is a vampire.",
            knowledge_type="secret",
            truth_status="true",
            sensitivity="secret",
        )
        timeline = c.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": fx.campaign_id},
        ).scalar()
        party = make_party(c, fx.world_id)
        make_campaign_party(c, fx.campaign_id, party)
        when = make_world_time(c, fx.world_id, 10)
    for command in (submit_entity_for_review, approve_entity, publish_entity_as_canon):
        with fx.engine.begin() as c:
            command(
                c,
                campaign_id=fx.campaign_id,
                entity_id=claim.entity_id,
                actor_user_id=fx.owner,
                expected_row_version=fx.version(claim.entity_id),
            )
    return CommittedClaim(
        knowledge_item_id=claim.entity_id,
        version=fx.version(claim.entity_id),
        party_id=party,
        timeline_id=timeline,
        world_time_id=when,
    )


def _reveal(fx_campaign: uuid.UUID, c: CommittedClaim) -> Callable[[Connection], Any]:
    return lambda conn: _reveal_knowledge_to_party_impl(
        conn,
        knowledge_item_id=c.knowledge_item_id,
        party_id=c.party_id,
        timeline_id=c.timeline_id,
        world_time_id=c.world_time_id,
        campaign_id=fx_campaign,
    )


def _reword(fx: Fixture, c: CommittedClaim) -> Callable[[Connection], Any]:
    return lambda conn: update_knowledge_item(
        conn,
        campaign_id=fx.campaign_id,
        knowledge_item_id=c.knowledge_item_id,
        actor_user_id=fx.owner,
        expected_row_version=c.version,
        statement="The duke is a werewolf.",
        knowledge_type="secret",
        truth_status="true",
        sensitivity="secret",
    )


def _statement(fx: Fixture, c: CommittedClaim) -> str:
    with fx.engine.connect() as conn:
        value = conn.execute(
            text(
                "SELECT canonical_statement FROM knowledge.knowledge_items "
                "WHERE knowledge_item_id = :k"
            ),
            {"k": c.knowledge_item_id},
        ).scalar()
    assert isinstance(value, str)
    return value


def test_a_reword_waits_for_an_in_flight_first_reveal_and_is_then_refused(fx: Fixture) -> None:
    c = _published_claim(fx)
    out = race(fx.engine, _reveal(fx.campaign_id, c), _reword(fx, c), ENTITY_LOCK)
    assert isinstance(out["error"], KnowledgeAlreadyKnownError)
    assert _statement(fx, c) == "The duke is a vampire."
    assert (
        fx.count(
            "SELECT count(*) FROM campaign.party_knowledge WHERE knowledge_item_id = :k",
            k=c.knowledge_item_id,
        )
        == 1
    )


def test_a_first_reveal_waits_for_an_in_flight_reword_and_reveals_the_new_statement(
    fx: Fixture,
) -> None:
    c = _published_claim(fx)
    out = race(fx.engine, _reword(fx, c), _reveal(fx.campaign_id, c), ENTITY_LOCK)
    assert "error" not in out
    assert _statement(fx, c) == "The duke is a werewolf."
    assert (
        fx.count(
            "SELECT count(*) FROM campaign.party_knowledge WHERE knowledge_item_id = :k",
            k=c.knowledge_item_id,
        )
        == 1
    )
