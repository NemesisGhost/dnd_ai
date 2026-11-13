# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S3: the real guard on the definition authoring and lifecycle routes, over real HTTP.

Plan sections 4.1, 6.3, 6.5, 6.6, 12.3 and 12.5. S3's declared authority sources are the actor's
campaign role rows (`canon.edit`) and, for every definition type but player-character identity, the
world role (`world.canon.edit`; `world.canon.review` for the review lifecycle). Everything here goes
through the actual migrated routes of `create_app()` on a migrated database, with the real commit guard
installed on a one-connection pool, so it shows what the plan promises about the routes themselves:

- **Freshness.** A campaign role that lapses after the request's last lock wait, but before its final
  statement, refuses the route with the refusal the early check gives a caller whose role is gone, and
  nothing persists: no definition row, no audit row, no receipt, and the key is reusable.
- **Concurrent change (plan 4.2).** A revocation of the campaign role or of the world role, requested
  while the request holds its locks, waits for it; both commit; the request is not refused, and the
  next request is.
- **Cleanup.** The refused request returns its pooled connection clean, and the next request on the same
  one-connection pool commits only its own work (T0).
- **Replay.** A lapse during the key-lock wait of a replay refuses it and returns nothing from the
  receipt; a still-authorized replay returns the stored receipt unchanged after one final statement.
- **Ordering.** On every success path the final authority statement is the last one before COMMIT and takes
  no row lock.
"""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.api.idempotency import lock_idempotency_key
from dnd_ai.commands.dungeons import create_dungeon
from dnd_ai.commands.entity_lifecycle import (
    approve_entity,
    publish_entity_as_canon,
    submit_entity_for_review,
)
from dnd_ai.commands.locations import create_location
from dnd_ai.commands.memberships import revoke_membership_role
from dnd_ai.commands.quest_definitions import create_quest
from dnd_ai.commands.sources import create_source
from dnd_ai.commands.world_access import end_world_role
from dnd_ai.commands.world_relationships import ParticipantInput, create_relationship
from dnd_ai.domain.authorization import AuthorizationPlan
from dnd_ai.domain.data_classification import replay_body
from dnd_ai.queries.npc_authoring import list_species_options
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    FINAL,
    FINAL_RE,
    ROW_LOCK_RE,
    Recorder,
    idle_in_transaction,
    pooled,
    pooled_factory,
    run_gated_before_final,
    set_lapse,
    wait_lapsed,
)
from tests.factories import (
    make_campaign_membership,
    make_membership_role,
    make_user,
    make_world_role_assignment,
)
from tests.http_race_support import StatementGate, new_key, run_in_thread, wait_until_pid_blocks
from tests.r01_support import fixture_plan

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]


# --- a committed world, its campaign, an owner, and a revocable GM ------------------------------------------------


@dataclass
class World:
    engine: Engine
    owner: uuid.UUID
    gm_user: uuid.UUID
    gm_membership: uuid.UUID
    gm_role: uuid.UUID
    gm_world_membership: uuid.UUID
    gm_reviewer_membership: uuid.UUID
    world_id: uuid.UUID
    campaign_id: uuid.UUID
    species: uuid.UUID

    @property
    def base(self) -> str:
        return f"/campaigns/{self.campaign_id}"


@pytest.fixture
def w(postgres_engine: Engine) -> Iterator[World]:
    """The GM holds `canon.edit` through the template `gm` role (revocable and expirable) and
    `world.canon.edit` through an open `world_editor` assignment, so each source can lapse alone."""
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "S3 Owner")
        authored = make_authored_world(setup, owner_user_id=owner, name="S3 World")
        campaign_id = make_authored_campaign(setup, authored, name="S3 Campaign")
        gm_user = make_user(setup, "S3 GM")
        membership = make_campaign_membership(setup, campaign_id, gm_user)
        template = setup.execute(
            text("SELECT role_id FROM security.roles WHERE code = 'gm' AND campaign_id IS NULL")
        ).scalar_one()
        role = make_membership_role(setup, membership, template)
        world_membership = make_world_role_assignment(
            setup, authored.world_id, gm_user, "world_editor", granted_by_user_id=owner
        )
        # archive, restore, approve, publish and supersede need `world.canon.review` (record_authoring)
        reviewer_membership = make_world_role_assignment(
            setup, authored.world_id, gm_user, "world_reviewer", granted_by_user_id=owner
        )
        species = list_species_options(setup, world_id=authored.world_id)[0].species_id
    try:
        yield World(
            postgres_engine,
            owner,
            gm_user,
            membership,
            role,
            world_membership,
            reviewer_membership,
            authored.world_id,
            campaign_id,
            species,
        )
    finally:
        _purge_user_worlds(postgres_engine, owner)


# --- one case per representative route of each module group -------------------------------------------------------


@dataclass
class Case:
    name: str
    call: Callable[[Factory, str | None], Any]
    ok: int = 201


def _post(w: World, path: str, body: dict[str, Any]) -> Callable[[Factory, str | None], Any]:
    def call(factory: Factory, key: str | None) -> Any:
        headers = {"Idempotency-Key": key} if key else {}
        with factory(w.gm_user) as client:
            return client.post(f"{w.base}{path}", json=body, headers=headers)

    return call


def _location(w: World) -> tuple[uuid.UUID, int]:
    with w.engine.begin() as connection:
        made = create_location(
            connection,
            campaign_id=w.campaign_id,
            actor_user_id=w.owner,
            category_code="region",
            name="Seeded place " + uuid.uuid4().hex[:6],
            summary=None,
            plan=fixture_plan(connection, w.campaign_id),
        )
    return made.entity_id, made.row_version


CASES = (
    "location",
    "npc",
    "player_character",
    "organization",
    "religion",
    "knowledge",
    "item_definition",
    "quest",
    "quest_stage",
    "quest_outcome",
    "dungeon",
    "dungeon_area",
    "source",
    "source_attach",
    "lifecycle_submit",
    "lifecycle_archive",
    "relationship_archive",
)


def build_case(name: str, w: World) -> Case:
    tag = uuid.uuid4().hex[:6]
    npc_body = {
        "name": f"S3 {tag}",
        "summary": None,
        "species_id": str(w.species),
        "size_category": "medium",
    }
    if name == "location":
        return Case(
            name, _post(w, "/authoring/locations", {"category": "region", "name": f"S3 {tag}"})
        )
    if name == "npc":
        return Case(name, _post(w, "/authoring/npcs", npc_body))
    if name == "player_character":
        return Case(name, _post(w, "/authoring/player-characters", npc_body))
    if name == "organization":
        return Case(
            name,
            _post(
                w,
                "/authoring/organizations",
                {"kind": "organization", "organization_type": "guild", "name": f"S3 {tag}"},
            ),
        )
    if name == "religion":
        return Case(name, _post(w, "/authoring/religions", {"name": f"S3 {tag}"}))
    if name == "knowledge":
        return Case(
            name,
            _post(
                w,
                "/authoring/knowledge",
                {
                    "statement": f"S3 fact {tag}",
                    "knowledge_type": "secret",
                    "truth_status": "true",
                    "sensitivity": "secret",
                },
            ),
        )
    if name == "item_definition":
        return Case(
            name,
            _post(w, "/authoring/item-definitions", {"name": f"S3 {tag}", "category": "weapon"}),
        )
    if name == "quest":
        return Case(name, _post(w, "/authoring/quests", {"name": f"S3 {tag}"}))
    if name in ("quest_stage", "quest_outcome"):
        with w.engine.begin() as connection:
            quest = create_quest(
                connection,
                campaign_id=w.campaign_id,
                actor_user_id=w.owner,
                name=f"S3 seeded quest {tag}",
                summary=None,
                plan=fixture_plan(connection, w.campaign_id),
            )
        if name == "quest_stage":
            body = {
                "expected_row_version": quest.row_version,
                "name": "Stage",
                "description": None,
                "stage_type": "sequential",
            }
            return Case(name, _post(w, f"/authoring/quests/{quest.entity_id}/stages", body), ok=200)
        body = {
            "expected_row_version": quest.row_version,
            "code": "found_it",
            "name": "Found it",
            "outcome_category": "success",
        }
        return Case(name, _post(w, f"/authoring/quests/{quest.entity_id}/outcomes", body), ok=200)
    if name in ("dungeon", "dungeon_area"):
        if name == "dungeon":
            return Case(
                name,
                _post(w, "/authoring/dungeons", {"name": f"S3 {tag}", "summary": None}),
            )
        with w.engine.begin() as connection:
            dungeon = create_dungeon(
                connection,
                campaign_id=w.campaign_id,
                actor_user_id=w.owner,
                name=f"S3 seeded dungeon {tag}",
                summary=None,
                plan=fixture_plan(connection, w.campaign_id),
            )
        return Case(
            name,
            _post(
                w,
                f"/authoring/dungeons/{dungeon.entity_id}/areas",
                {"name": "Hall"},
            ),
        )
    if name == "source":
        return Case(
            name,
            _post(w, "/sources", {"source_type": "gm_entry", "title": f"S3 {tag}"}),
        )
    if name == "relationship_archive":
        with w.engine.begin() as connection:
            places = []
            for label in ("North", "South"):
                made = create_location(
                    connection,
                    campaign_id=w.campaign_id,
                    actor_user_id=w.owner,
                    category_code="region",
                    name=f"S3 {label} {tag}",
                    summary=None,
                    plan=fixture_plan(connection, w.campaign_id),
                )
                version = made.row_version
                for step in (submit_entity_for_review, approve_entity, publish_entity_as_canon):
                    version = step(
                        connection,
                        campaign_id=w.campaign_id,
                        entity_id=made.entity_id,
                        actor_user_id=w.owner,
                        expected_row_version=version,
                        plan=fixture_plan(connection, w.campaign_id),
                    ).row_version
                places.append(made.entity_id)
            relationship = create_relationship(
                connection,
                campaign_id=w.campaign_id,
                actor_user_id=w.owner,
                kind="general",
                relationship_type="adjacency",
                participants=[
                    ParticipantInput(places[0], "subject"),
                    ParticipantInput(places[1], "object"),
                ],
                plan=fixture_plan(connection, w.campaign_id),
            )
        return Case(
            name,
            _post(
                w,
                f"/authoring/relationships/{relationship.relationship_id}/archive",
                {"expected_row_version": relationship.row_version},
            ),
            ok=200,
        )
    place, version = _location(w)
    if name == "source_attach":
        with w.engine.begin() as connection:
            source = create_source(
                connection,
                campaign_id=w.campaign_id,
                actor_user_id=w.owner,
                source_type="gm_entry",
                title=f"S3 source {tag}",
                reference=None,
                plan=fixture_plan(connection, w.campaign_id),
            )
        return Case(
            name,
            _post(w, f"/entities/{place}/sources/attach", {"source_id": str(source.source_id)}),
            ok=200,
        )
    if name == "lifecycle_submit":
        return Case(
            name,
            _post(
                w,
                f"/entities/{place}/lifecycle/submit-for-review",
                {"expected_row_version": version},
            ),
            ok=200,
        )
    assert name == "lifecycle_archive"
    return Case(
        name,
        _post(w, f"/entities/{place}/lifecycle/archive", {"expected_row_version": version}),
        ok=200,
    )


def state(w: World, key: str | None = None) -> tuple[Any, ...]:
    """Everything a refused protected write must leave alone: the world's definition rows and their
    versions, sources and links, the audit rows, and the key's receipt."""
    with w.engine.connect() as connection:
        scalar = lambda sql, **p: connection.execute(text(sql), p).scalar_one()  # noqa: E731
        return (
            scalar(
                "SELECT count(*) || '/' || COALESCE(sum(row_version), 0) FROM core.entities "
                "WHERE world_id = :w",
                w=w.world_id,
            ),
            scalar("SELECT count(*) FROM core.sources WHERE world_id = :w", w=w.world_id),
            scalar(
                "SELECT count(*) FROM core.entity_source_links l JOIN core.entities e "
                "ON e.entity_id = l.entity_id WHERE e.world_id = :w",
                w=w.world_id,
            ),
            scalar(
                "SELECT count(*) || '/' || COALESCE(sum(row_version), 0) FROM world.relationships "
                "WHERE world_id = :w",
                w=w.world_id,
            ),
            scalar("SELECT count(*) FROM audit.change_log WHERE world_id = :w", w=w.world_id),
            scalar(
                "SELECT count(*) FROM security.idempotent_requests WHERE idempotency_key = :k",
                k=key,
            )
            if key
            else None,
        )


def code(response: Any) -> int:
    return int(response.status_code)


def error_of(response: Any) -> str | None:
    try:
        return str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return None


#: The idempotency key lock: the request's first lock, taken "before any row lock, row write or other
#: advisory lock of the request" (`lock_idempotency_key`), after the route's early check.
KEY_LOCK_RE = r"pg_advisory_xact_lock"


def run_with_role_expiring_before_final(
    w: World, app_engine: Engine, call: Callable[[], Any]
) -> Any:
    """Runs `call` (an HTTP request) so that the GM's role is valid for every early check and has
    lapsed by the final authority statement, with no dependence on how fast the request runs.

    1. The request is paused *at its idempotency key lock*, before any row lock. It has passed the
       route's early check and holds nothing, so the test's `UPDATE` of the role row neither waits for
       it nor, through the access-manager retention trigger (which takes the campaign row `FOR UPDATE`
       at commit), waits for the campaign `FOR KEY SHARE` the reservation takes later. A pause after
       either lock would deadlock the test against the paused request; the update runs under a
       `lock_timeout`, so an unexpected conflict is an error, not a hang.
    2. `expires_at` is set to the request's own transaction start (from `pg_stat_activity`) plus one
       second. Every early check judges at `now()`, which is that start, so it passes however long the
       request takes; the final check judges at `clock_timestamp()` and fails once the second has gone.
    3. The request runs on and is paused again at its final authority statement; the test polls the
       DATABASE condition `expires_at <= clock_timestamp()`, and only then releases it."""
    with (
        StatementGate(app_engine, KEY_LOCK_RE) as first,
        StatementGate(app_engine, FINAL) as final,
    ):
        request = run_in_thread("s3-request", call)
        first.wait_reached()
        with w.engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            moved = connection.execute(
                text("""
                    UPDATE security.membership_roles
                    SET expires_at = (
                        SELECT xact_start FROM pg_stat_activity WHERE pid = :pid
                    ) + interval '1 second'
                    WHERE membership_role_id = :r AND revoked_at IS NULL
                """),
                {"pid": first.pid, "r": w.gm_role},
            ).rowcount
            assert moved == 1
        first.release()
        final.wait_reached()
        wait_lapsed(w.engine, w.gm_role)
        final.release()
        return request.wait("the gated request finishes")


# --- freshness: the campaign role lapses between the last lock wait and the final statement ------------------------


@pytest.mark.parametrize("name", CASES)
def test_a_role_that_lapses_before_the_final_statement_refuses_the_route_and_persists_nothing(
    name: str, w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    case = build_case(name, w)
    key = new_key()
    before = state(w, key)
    response = run_with_role_expiring_before_final(
        w, pooled, lambda: case.call(pooled_factory, key)
    )
    refused = (code(response), error_of(response))
    assert refused[0] in (403, 404), (name, refused, response.text)
    # Nothing persisted: no definition row, version bump, audit row or receipt.
    assert state(w, key) == before, name
    # The pooled connection is clean, and the next request on it commits only its own work.
    assert idle_in_transaction(w.engine) == 0
    with pooled_factory(w.owner) as client:
        assert code(client.get(f"{w.base}/authoring/npcs/options")) in (200, 404)
    assert state(w, key) == before, name
    # The early refusal of the same caller (role revoked before the request) is the same refusal.
    with w.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": w.gm_role},
        )
    early = case.call(pooled_factory, new_key())
    assert (code(early), error_of(early)) == refused, (name, early.text)


@pytest.mark.parametrize("name", ("location", "quest_stage", "lifecycle_submit"))
def test_the_key_of_a_refused_request_is_reusable_once_the_actor_is_authorized_again(
    name: str, w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    case = build_case(name, w)
    key = new_key()
    refused = run_with_role_expiring_before_final(w, pooled, lambda: case.call(pooled_factory, key))
    assert code(refused) in (403, 404)
    assert state(w, key)[5] == 0
    with w.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = NULL WHERE membership_role_id = :r"
            ),
            {"r": w.gm_role},
        )
    again = case.call(pooled_factory, key)
    assert code(again) == case.ok, (name, again.text)
    assert state(w, key)[5] == 1


# --- concurrent change (plan 4.2): a revocation requested during the request waits for it ---------------------------


def _revoke_campaign_role(w: World) -> None:
    with w.engine.begin() as connection:
        revoke_membership_role(connection, membership_role_id=w.gm_role, campaign_id=w.campaign_id)


def _end_world_role(w: World) -> None:
    with w.engine.begin() as connection:
        end_world_role(
            connection,
            actor_user_id=w.owner,
            world_id=w.world_id,
            world_membership_id=w.gm_world_membership,
        )


@pytest.mark.parametrize(
    ("revoke", "early_error"),
    ((_revoke_campaign_role, None), (_end_world_role, "world_authority_required")),
    ids=("campaign_role", "world_role"),
)
@pytest.mark.parametrize("name", ("location", "quest_stage", "lifecycle_submit"))
def test_a_revocation_requested_during_the_request_waits_for_it_and_is_seen_by_the_next(
    name: str,
    revoke: Callable[[World], None],
    early_error: str | None,
    w: World,
    pooled: Engine,
    pooled_factory: Factory,
) -> None:
    """(b) of plan 12.3 item 5: the request holds the role rows (`FOR SHARE`) and the world (`FOR
    SHARE`); a revocation takes them `FOR UPDATE` and so waits behind it. The request commits, the
    revocation then commits, and the next request is refused."""
    case = build_case(name, w)
    key = new_key()
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread("s3-request", lambda: case.call(pooled_factory, key))
        gate.wait_reached()
        assert gate.pid is not None
        revocation = run_in_thread("s3-revoke", lambda: revoke(w))
        # the revocation is genuinely waiting on the request, which holds the rows it needs `FOR UPDATE`
        wait_until_pid_blocks(w.engine, gate.pid)
        gate.release()
        response = request.wait("the gated request finishes")
    revocation.wait("the revocation finishes")
    assert code(response) == case.ok, (name, response.text)
    assert state(w, key)[5] == 1
    after = case.call(pooled_factory, new_key())
    assert code(after) in (403, 404), (name, after.text)
    if early_error is not None:
        assert error_of(after) == early_error


# --- replay (R-D4) -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ("location", "lifecycle_submit"))
def test_a_lapse_during_a_replays_key_lock_wait_refuses_it_and_returns_nothing_from_the_receipt(
    name: str, w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    case = build_case(name, w)
    key = new_key()
    first = case.call(pooled_factory, key)
    assert code(first) == case.ok, first.text
    stored = state(w, key)
    assert stored[5] == 1
    # The test holds the same key lock the request takes inside `begin_idempotent_request`, so the
    # replay genuinely waits there; the role is set to lapse once the replay is observed waiting.
    with w.engine.connect() as holder:
        transaction = holder.begin()
        lock_idempotency_key(
            holder, actor_user_id=w.gm_user, campaign_id=w.campaign_id, idempotency_key=key
        )
        pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
        replay = run_in_thread("replay", lambda: case.call(pooled_factory, key))
        wait_until_pid_blocks(w.engine, pid)
        set_lapse(w.engine, w.gm_role, 1)
        wait_lapsed(w.engine, w.gm_role)
        transaction.commit()
    response = replay.wait("the replay finishes")
    assert code(response) in (403, 404), response.text
    assert response.text != first.text, "a receipt leaked to a lapsed caller"
    assert state(w, key) == stored
    assert idle_in_transaction(w.engine) == 0


@pytest.mark.parametrize("name", ("location", "lifecycle_submit"))
def test_a_still_authorized_replay_returns_the_receipt_unchanged_after_one_final_statement(
    name: str, w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    case = build_case(name, w)
    key = new_key()
    first = case.call(pooled_factory, key)
    assert code(first) == case.ok
    with Recorder(pooled) as recorded:
        replay = case.call(pooled_factory, key)
    assert (code(replay), replay.json()) == (code(first), replay_body(first.json()))
    finals = [s for s in recorded.events if FINAL_RE.search(s)]
    assert len(finals) == 1 and recorded.events[-2:] == [finals[0], "COMMIT"]
    # A replay runs no command: no scope lock, no definition write.
    assert not any(ROW_LOCK_RE.search(s) for s in recorded.events), recorded.events
    writes = [s for s in recorded.events if s.startswith(("INSERT", "UPDATE", "DELETE"))]
    assert all("security.idempotent_requests" in s and "ON CONFLICT" in s for s in writes), writes


# --- ordering: the final statement is the last statement before COMMIT, and takes no row lock -------------------------


@pytest.mark.parametrize("name", CASES)
def test_the_final_statement_is_the_last_before_commit_and_takes_no_row_lock(
    name: str, w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    case = build_case(name, w)
    with Recorder(pooled) as recorded:
        response = case.call(pooled_factory, new_key())
    assert code(response) == case.ok, (name, response.text)
    finals = [s for s in recorded.events if FINAL_RE.search(s)]
    assert len(finals) == 1, (name, len(finals))
    assert recorded.events[-2:] == [finals[0], "COMMIT"], (name, recorded.events[-4:])
    assert ROW_LOCK_RE.search(finals[0]) is None
    # It followed the command, the audit row and the receipt: those writes all precede it.
    writes = [i for i, s in enumerate(recorded.events) if s.startswith(("INSERT", "UPDATE"))]
    assert writes and max(writes) < recorded.events.index(finals[0]), name


def test_a_handler_that_forgets_to_finalize_is_a_sanitized_500_that_persists_nothing(
    w: World, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = build_case("location", w)
    before = state(w)
    monkeypatch.setattr(AuthorizationPlan, "finalize", lambda self, connection: None)
    refused = case.call(pooled_factory, new_key())
    assert code(refused) == 500
    assert error_of(refused) == "internal_error"
    assert state(w) == before
    assert idle_in_transaction(w.engine) == 0
    monkeypatch.undo()
    assert code(case.call(pooled_factory, new_key())) == 201


# --- the dungeon child routes no other route test drives -------------------------------------------------------------


def test_every_dungeon_child_route_finalizes_last_through_the_real_guard(
    w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    """`features`, `hazards` and `interactables` share one parameterised handler set (`_child_routes`);
    four of its nine routes (feature update, hazard remove, interactable update and remove) have no
    other HTTP test. Each of the nine runs here on the real guard, and its final authority statement is
    the last before COMMIT."""
    base = f"{w.base}/authoring/dungeons"

    def post(client: TestClient, path: str, body: dict[str, Any]) -> Any:
        with Recorder(pooled) as recorded:
            response = client.post(path, json=body, headers={"Idempotency-Key": new_key()})
        finals = [s for s in recorded.events if FINAL_RE.search(s)]
        assert len(finals) == 1, (path, len(finals))
        assert recorded.events[-2:] == [finals[0], "COMMIT"], (path, recorded.events[-3:])
        return response

    with pooled_factory(w.gm_user) as client:
        made = post(client, base, {"name": "S3 children", "summary": None})
        assert code(made) == 201, made.text
        dungeon = made.json()["dungeon_id"]
        version = made.json()["row_version"]
        area = post(client, f"{base}/{dungeon}/areas", {"name": "Hall"})
        assert code(area) == 201, area.text
        area_id, version = area.json()["dungeon_area_id"], area.json()["dungeon_row_version"]
        for kind in ("features", "hazards", "interactables"):
            added = post(
                client,
                f"{base}/{dungeon}/{kind}",
                {
                    "expected_row_version": version,
                    "dungeon_area_id": area_id,
                    "child_type": "plain",
                    "description": f"S3 {kind}",
                },
            )
            assert code(added) == 201, (kind, added.text)
            child, version = added.json()["record_id"], added.json()["row_version"]
            updated = post(
                client,
                f"{base}/{dungeon}/{kind}/{child}/update",
                {"expected_row_version": version, "description": f"S3 {kind} edited"},
            )
            assert code(updated) == 200, (kind, updated.text)
            version = updated.json()["row_version"]
            removed = post(
                client,
                f"{base}/{dungeon}/{kind}/{child}/remove",
                {"expected_row_version": version},
            )
            assert code(removed) == 200, (kind, removed.text)
            version = removed.json()["row_version"]


# --- replay (R-D4): the stored receipt leaves only under the world capability the command needs -----------------------


def _end_world_assignment(w: World, membership: uuid.UUID) -> None:
    with w.engine.begin() as connection:
        end_world_role(
            connection,
            actor_user_id=w.owner,
            world_id=w.world_id,
            world_membership_id=membership,
        )


#: (case, the world assignment the route's command needs). `world_editor` carries `world.canon.edit`,
#: `world_reviewer` carries `world.canon.review` (archive, restore, approve, publish, supersede).
REPLAY_CASES = (
    ("location", "editor"),
    ("npc", "editor"),
    ("quest_stage", "editor"),
    ("source", "editor"),
    ("lifecycle_submit", "editor"),  # the entity lifecycle's own idempotency branch
    ("lifecycle_archive", "reviewer"),  # ... under the review capability
    ("relationship_archive", "editor"),  # a closure-built route
)


@pytest.mark.parametrize(("name", "needs"), REPLAY_CASES)
def test_a_replay_and_a_fresh_request_are_refused_once_the_required_world_role_is_gone(
    name: str, needs: str, w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    """The actor keeps campaign `canon.edit`; only the world capability the command needs is ended. The
    same key must not return the stored receipt, a fresh key must be refused the same way, and neither
    changes a definition, audit or receipt row."""
    case = build_case(name, w)
    key = new_key()
    first = case.call(pooled_factory, key)
    assert code(first) == case.ok, (name, first.text)
    # still authorized: the replay is the stored receipt, unchanged
    replay = case.call(pooled_factory, key)
    assert (code(replay), replay.json()) == (code(first), replay_body(first.json())), name
    stored = state(w, key)
    assert stored[5] == 1

    _end_world_assignment(
        w, w.gm_reviewer_membership if needs == "reviewer" else w.gm_world_membership
    )

    again = case.call(pooled_factory, key)
    assert (code(again), error_of(again)) == (403, "world_authority_required"), (name, again.text)
    receipt_values = {v for v in first.json().values() if isinstance(v, str) and len(v) >= 32}
    assert receipt_values, "the receipt names no id to look for"
    assert not any(v in again.text for v in receipt_values), "a stored receipt leaked"
    fresh_key = new_key()
    fresh = case.call(pooled_factory, fresh_key)
    assert (code(fresh), error_of(fresh)) == (403, "world_authority_required"), (name, fresh.text)
    assert state(w, key) == stored, name
    assert state(w, fresh_key)[5] == 0
    assert idle_in_transaction(w.engine) == 0


def test_the_other_world_role_does_not_authorize_or_refuse_a_review_replay(
    w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    """Archive needs `world.canon.review`, not `world.canon.edit`: ending only the editor assignment
    leaves its replay authorized. The replay judges the command's own requirement, no broader."""
    case = build_case("lifecycle_archive", w)
    key = new_key()
    first = case.call(pooled_factory, key)
    assert code(first) == 200, first.text
    _end_world_assignment(w, w.gm_world_membership)
    replay = case.call(pooled_factory, key)
    assert (code(replay), replay.json()) == (code(first), replay_body(first.json()))


@pytest.mark.parametrize("name", ("player_character", "item_definition"))
def test_a_campaign_originated_replay_needs_no_world_role(
    name: str, w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    """Player-character identity registers no world capability (D8): its replay is unchanged by the
    end of the GM's world assignment. (The item definition is world canon and is refused.)"""
    case = build_case(name, w)
    key = new_key()
    first = case.call(pooled_factory, key)
    assert code(first) == 201, first.text
    _end_world_assignment(w, w.gm_world_membership)
    replay = case.call(pooled_factory, key)
    if name == "player_character":
        assert (code(replay), replay.json()) == (code(first), replay_body(first.json()))
    else:
        assert (code(replay), error_of(replay)) == (403, "world_authority_required")


@pytest.mark.parametrize("name", CASES)
def test_a_replay_judges_the_same_requirements_as_the_fresh_request(
    name: str, w: World, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The structural safeguard: whatever a route's command registers on a fresh request is already in
    the plan, in the same order and without duplicates, when a replay finalizes it."""
    seen: list[list[str]] = []
    original = AuthorizationPlan.finalize

    def spy(self: AuthorizationPlan, connection: Any) -> Any:
        seen.append([r.name for r in self.requirements])
        return original(self, connection)

    monkeypatch.setattr(AuthorizationPlan, "finalize", spy)
    case = build_case(name, w)
    key = new_key()
    assert code(case.call(pooled_factory, key)) == case.ok
    assert code(case.call(pooled_factory, key)) == case.ok
    fresh, replayed = seen
    assert fresh == replayed, (name, fresh, replayed)
    assert len(set(fresh)) == len(fresh), (name, fresh)
    assert fresh[0].startswith("route.") and "campaign.canon.edit" in fresh
