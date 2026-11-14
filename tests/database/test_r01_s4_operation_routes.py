# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S4: the real guard on the campaign operation routes, over real HTTP.

Plan sections 4.1, 6.3, 6.5, 6.6, 12.3, 12.5 and 12.6 (V-T1). S4's single declared authority source is
the actor's campaign role rows (`canon.edit`, time-based through `expires_at` and revocable). No S4
route registers a world capability, a Foundry scope or a targeted grant: the route dependency's
decision (`route.canon.edit`) and the command scope's (`campaign.canon.edit`) read the same
capability from the same snapshot, the route's first. Everything here goes through the actual migrated
routes of `create_app()` on a migrated database, with the real commit guard installed on a
one-connection pool:

- **Freshness.** A campaign role that lapses after the request's last lock wait, but before its final
  statement, refuses the route with the refusal the early check gives a caller whose role is gone, and
  nothing persists: no row, no event, no audit row, no receipt, and the key is reusable.
- **Concurrent change (plan 4.2).** A revocation requested while the request holds its locks waits for it;
  both commit; the request is not refused and the next request is.
- **Cleanup.** The refused request returns its pooled connection clean (T0).
- **Replay.** A lapse during the key-lock wait of a replay refuses it, and so does a role revoked before
  it, with the same refusal a fresh key gets and nothing from the receipt; a still-authorized replay
  returns the stored receipt unchanged after one final statement.
- **Ordering.** On every success path the final authority statement is the last one before COMMIT and takes
  no row lock.
- **V-T1.** The deferred events trigger (`ctr_events_status_has_correction`) takes no row lock at COMMIT.
"""

import secrets
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.api.idempotency import lock_idempotency_key
from dnd_ai.commands.memberships import end_campaign_membership, revoke_membership_role
from dnd_ai.domain.authorization import AuthorizationPlan
from dnd_ai.domain.data_classification import replay_body
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_api_campaign_clock import CALENDAR
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    FINAL,
    FINAL_RE,
    ROW_LOCK_RE,
    Recorder,
    idle_in_transaction,
    pooled,
    pooled_factory,
    set_lapse,
    wait_lapsed,
)
from tests.factories import make_campaign_membership, make_membership_role, make_user
from tests.http_race_support import (
    WAIT_SECONDS,
    StatementGate,
    new_key,
    run_in_thread,
    wait_until_pid_blocks,
)

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]


# --- a committed world, its campaign, an owner, and a revocable GM -----------------------------------------------


@dataclass
class World:
    engine: Engine
    owner: uuid.UUID
    gm_user: uuid.UUID
    gm_membership: uuid.UUID
    gm_role: uuid.UUID
    world_id: uuid.UUID
    campaign_id: uuid.UUID
    calendar_id: str | None = None

    @property
    def base(self) -> str:
        return f"/campaigns/{self.campaign_id}"


@pytest.fixture
def w(postgres_engine: Engine) -> Iterator[World]:
    """The GM holds `canon.edit` through the template `gm` role (revocable and expirable) and nothing
    else: no world role, so a route that asked for one would be refused."""
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "S4 Owner")
        authored = make_authored_world(setup, owner_user_id=owner, name="S4 World")
        campaign_id = make_authored_campaign(setup, authored, name="S4 Campaign")
        gm_user = make_user(setup, "S4 GM")
        membership = make_campaign_membership(setup, campaign_id, gm_user)
        template = setup.execute(
            text("SELECT role_id FROM security.roles WHERE code = 'gm' AND campaign_id IS NULL")
        ).scalar_one()
        role = make_membership_role(setup, membership, template)
    try:
        yield World(
            postgres_engine, owner, gm_user, membership, role, authored.world_id, campaign_id
        )
    finally:
        _purge_user_worlds(postgres_engine, owner)


# --- one case per representative route of each module group -------------------------------------------------------


@dataclass
class Case:
    name: str
    call: Callable[[Factory, str | None], Any]
    ok: int = 200


def _post(w: World, path: str, body: dict[str, Any]) -> Callable[[Factory, str | None], Any]:
    def call(factory: Factory, key: str | None) -> Any:
        headers = {"Idempotency-Key": key} if key else {}
        with factory(w.gm_user) as client:
            return client.post(f"{w.base}{path}", json=body, headers=headers)

    return call


def _seed(w: World, factory: Factory, path: str, body: dict[str, Any], ok: int = 201) -> Any:
    """A committed fixture, written as the owner through the real route."""
    with factory(w.owner) as client:
        response = client.post(f"{w.base}{path}", json=body, headers={"Idempotency-Key": new_key()})
    assert response.status_code == ok, (path, response.text)
    return response.json()


def _calendar(w: World, factory: Factory) -> str:
    if w.calendar_id is None:
        with factory(w.owner) as client:
            response = client.post(
                f"/worlds/{w.world_id}/calendars",
                json=CALENDAR,
                headers={"Idempotency-Key": new_key()},
            )
        assert response.status_code == 201, response.text
        w.calendar_id = str(response.json()["calendar_id"])
    return w.calendar_id


def _year() -> int:
    return secrets.randbelow(9000) + 1


def _time(w: World, factory: Factory, label: str) -> str:
    body = {"calendar_id": _calendar(w, factory), "year": _year()}
    return str(_seed(w, factory, "/world-times", body)["world_time_id"])


def _session(w: World, factory: Factory) -> dict[str, Any]:
    return _seed(w, factory, "/sessions", {"title": "S4 seeded " + uuid.uuid4().hex[:6]})


def _clock(w: World, factory: Factory) -> None:
    """The campaign clock, which starting a session and preparing an encounter default to."""
    at = _time(w, factory, "S4 clock")
    _seed(w, factory, "/clock/advance", {"world_time_id": at, "expected_row_version": 0}, ok=200)


def _party(w: World, factory: Factory) -> dict[str, Any]:
    return _seed(w, factory, "/parties", {"name": "S4 party " + uuid.uuid4().hex[:6]})


def _event(w: World, factory: Factory) -> str:
    at = _time(w, factory, "S4 event time " + uuid.uuid4().hex[:6])
    return str(
        _seed(
            w,
            factory,
            "/events",
            {"world_time_id": at, "event_type_code": "other", "name": "S4 event"},
        )["event_id"]
    )


CASES = (
    "world_time",
    "session_schedule",
    "session_update",
    "session_archive",
    "session_start",
    "party_create",
    "party_update",
    "party_archive",
    "clock_advance",
    "event_void",
    "event_correct",
    "encounter_prepare",
)


def build_case(name: str, w: World, factory: Factory) -> Case:
    tag = uuid.uuid4().hex[:6]
    if name == "world_time":
        body = {"calendar_id": _calendar(w, factory), "year": _year()}
        return Case(name, _post(w, "/world-times", body), ok=201)
    if name == "session_schedule":
        return Case(name, _post(w, "/sessions", {"title": f"S4 {tag}"}), ok=201)
    if name == "party_create":
        return Case(name, _post(w, "/parties", {"name": f"S4 {tag}"}), ok=201)
    if name == "clock_advance":
        at = _time(w, factory, f"S4 clock {tag}")
        return Case(
            name, _post(w, "/clock/advance", {"world_time_id": at, "expected_row_version": 0})
        )
    if name == "event_void":
        event = _event(w, factory)
        return Case(name, _post(w, f"/events/{event}/void", {"reason": f"S4 void {tag}"}))
    if name == "event_correct":
        event = _event(w, factory)
        body = {
            "reason": f"S4 correct {tag}",
            "replacement": {"event_type_code": "other", "name": f"S4 replacement {tag}"},
        }
        return Case(name, _post(w, f"/events/{event}/correct", body))
    if name == "encounter_prepare":
        _clock(w, factory)
        session = _session(w, factory)
        return Case(
            name,
            _post(w, "/encounters/prepare", {"session_id": str(session["session_id"])}),
            ok=201,
        )
    if name in ("party_update", "party_archive"):
        party = _party(w, factory)
        base = f"/parties/{party['party_id']}"
        if name == "party_update":
            body = {"expected_row_version": party["row_version"], "name": f"S4 renamed {tag}"}
            return Case(name, _post(w, base + "/update", body))
        return Case(
            name, _post(w, base + "/archive", {"expected_row_version": party["row_version"]})
        )
    session = _session(w, factory)
    base = f"/sessions/{session['session_id']}"
    version = session["row_version"]
    if name == "session_update":
        return Case(
            name,
            _post(w, base + "/update", {"expected_row_version": version, "title": f"S4 {tag}"}),
        )
    if name == "session_archive":
        return Case(name, _post(w, base + "/archive", {"expected_row_version": version}))
    assert name == "session_start"
    _clock(w, factory)
    return Case(name, _post(w, base + "/start", {"expected_row_version": version}))


#: Tables whose rows a refused protected write must leave alone, counted for this campaign's world or
#: timeline, plus the audit log and the key's receipt.
_COUNTS = (
    ("campaign.sessions", "campaign_id = :c"),
    ("campaign.parties", "world_id = :w"),
    ("narrative.encounters", "campaign_id = :c"),
    (
        "narrative.events",
        "timeline_id = (SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c)",
    ),
    ("narrative.event_corrections", "true"),
    ("core.world_times", "world_id = :w"),
    ("campaign.timeline_clocks", "true"),
    ("audit.change_log", "world_id = :w"),
)


def state(w: World, key: str | None = None) -> tuple[Any, ...]:
    with w.engine.connect() as connection:
        counts = tuple(
            connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE {where}"),  # noqa: S608 - fixed table names
                {"c": w.campaign_id, "w": w.world_id},
            ).scalar_one()
            for table, where in _COUNTS
        )
        versions = connection.execute(
            text(
                "SELECT COALESCE(sum(row_version), 0) FROM campaign.sessions WHERE campaign_id = :c"
            ),
            {"c": w.campaign_id},
        ).scalar_one()
        receipt = (
            connection.execute(
                text(
                    "SELECT count(*) FROM security.idempotent_requests WHERE idempotency_key = :k"
                ),
                {"k": key},
            ).scalar_one()
            if key
            else None
        )
    return (*counts, versions, receipt)


RECEIPT = -1  # the index of the key's receipt count in `state`


def code(response: Any) -> int:
    return int(response.status_code)


def error_of(response: Any) -> str | None:
    try:
        return str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return None


#: The idempotency key lock: the request's first lock, taken after the route's early check.
KEY_LOCK_RE = r"pg_advisory_xact_lock"


def run_with_role_expiring_before_final(
    w: World, app_engine: Engine, call: Callable[[], Any]
) -> Any:
    """Runs `call` (an HTTP request) so that the GM's role is valid for every early check and has lapsed
    by the final authority statement, with no dependence on how fast the request runs.

    1. The request is paused *at its idempotency key lock*, before any row lock. It has passed the route's
       early check and holds nothing, so the test's `UPDATE` of the role row waits for nothing (the update
       runs under a `lock_timeout`: an unexpected conflict is an error, not a hang).
    2. `expires_at` is set to the request's own transaction start (`pg_stat_activity.xact_start`) plus one
       second. Every early check judges at `now()`, which is that start, so it passes however long the
       request takes; the final check judges at `clock_timestamp()` and fails once the second has gone.
    3. The request runs on and is paused again at its final authority statement; the test polls the
       DATABASE condition `expires_at <= clock_timestamp()` and only then releases it."""
    with (
        StatementGate(app_engine, KEY_LOCK_RE) as first,
        StatementGate(app_engine, FINAL) as final,
    ):
        request = run_in_thread("s4-request", call)
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
    case = build_case(name, w, pooled_factory)
    key = new_key()
    before = state(w, key)
    response = run_with_role_expiring_before_final(
        w, pooled, lambda: case.call(pooled_factory, key)
    )
    refused = (code(response), error_of(response))
    assert refused[0] in (403, 404), (name, refused, response.text)
    # Nothing persisted: no row, version bump, event, audit row or receipt.
    assert state(w, key) == before, name
    # The pooled connection is clean, and the next request on it commits only its own work.
    assert idle_in_transaction(w.engine) == 0
    with pooled_factory(w.owner) as client:
        assert code(client.get(f"{w.base}/sessions")) in (200, 404)
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


@pytest.mark.parametrize("name", ("session_schedule", "event_void", "party_update"))
def test_the_key_of_a_refused_request_is_reusable_once_the_actor_is_authorized_again(
    name: str, w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    case = build_case(name, w, pooled_factory)
    key = new_key()
    refused = run_with_role_expiring_before_final(w, pooled, lambda: case.call(pooled_factory, key))
    assert code(refused) in (403, 404)
    assert state(w, key)[RECEIPT] == 0
    with w.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = NULL WHERE membership_role_id = :r"
            ),
            {"r": w.gm_role},
        )
    again = case.call(pooled_factory, key)
    assert code(again) == case.ok, (name, again.text)
    assert state(w, key)[RECEIPT] == 1


# --- concurrent change (plan 4.2): a revocation requested during the request waits for it ---------------------------


def _revoke_campaign_role(w: World) -> None:
    with w.engine.begin() as connection:
        revoke_membership_role(connection, membership_role_id=w.gm_role, campaign_id=w.campaign_id)


def _end_membership(w: World) -> None:
    with w.engine.begin() as connection:
        owner_membership = connection.execute(
            text(
                "SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u AND ended_at IS NULL"
            ),
            {"c": w.campaign_id, "u": w.owner},
        ).scalar_one()
        end_campaign_membership(
            connection,
            campaign_membership_id=w.gm_membership,
            campaign_id=w.campaign_id,
            ended_by_membership_id=owner_membership,
        )


@pytest.mark.parametrize(
    "revoke", (_revoke_campaign_role, _end_membership), ids=("role", "membership")
)
@pytest.mark.parametrize("name", ("session_schedule", "event_void", "party_archive"))
def test_a_revocation_requested_during_the_request_waits_for_it_and_is_seen_by_the_next(
    name: str,
    revoke: Callable[[World], None],
    w: World,
    pooled: Engine,
    pooled_factory: Factory,
) -> None:
    """(b) of plan 12.3 item 5: the request holds the role and membership rows (`FOR SHARE`); a
    revocation takes them `FOR UPDATE` and so waits behind it. The request commits, the revocation then
    commits, and the next request is refused."""
    case = build_case(name, w, pooled_factory)
    key = new_key()
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread("s4-request", lambda: case.call(pooled_factory, key))
        gate.wait_reached()
        assert gate.pid is not None
        revocation = run_in_thread("s4-revoke", lambda: revoke(w))
        # the revocation is genuinely waiting on the request, which holds the rows it needs `FOR UPDATE`
        wait_until_pid_blocks(w.engine, gate.pid)
        gate.release()
        response = request.wait("the gated request finishes")
    revocation.wait("the revocation finishes")
    assert code(response) == case.ok, (name, response.text)
    assert state(w, key)[RECEIPT] == 1
    after = case.call(pooled_factory, new_key())
    assert code(after) in (403, 404), (name, after.text)


# --- replay (R-D4) -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ("session_schedule", "event_void"))
def test_a_lapse_during_a_replays_key_lock_wait_refuses_it_and_returns_nothing_from_the_receipt(
    name: str, w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    case = build_case(name, w, pooled_factory)
    key = new_key()
    first = case.call(pooled_factory, key)
    assert code(first) == case.ok, first.text
    stored = state(w, key)
    assert stored[RECEIPT] == 1
    # The test holds the same key lock the request takes inside `begin_idempotent_request`, so the replay
    # genuinely waits there; the role is set to lapse once the replay is observed waiting.
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


def _receipt_ids(response: Any) -> set[str]:
    return {v for v in response.json().values() if isinstance(v, str) and len(v) >= 32}


@pytest.mark.parametrize(
    "revoke", (_revoke_campaign_role, _end_membership), ids=("role", "membership")
)
@pytest.mark.parametrize("name", CASES)
def test_a_replay_after_the_authority_is_gone_is_refused_exactly_as_a_fresh_key_is(
    name: str,
    revoke: Callable[[World], None],
    w: World,
    pooled: Engine,
    pooled_factory: Factory,
) -> None:
    """The replay judges the same decision a fresh request does, so for every actor state it returns the
    same refusal, from the same plan, and nothing from the stored receipt."""
    case = build_case(name, w, pooled_factory)
    key = new_key()
    first = case.call(pooled_factory, key)
    assert code(first) == case.ok, (name, first.text)
    # still authorized: the replay is the stored receipt, unchanged
    replay = case.call(pooled_factory, key)
    assert (code(replay), replay.json()) == (code(first), replay_body(first.json())), name
    stored = state(w, key)
    assert stored[RECEIPT] == 1

    revoke(w)

    again = case.call(pooled_factory, key)
    fresh_key = new_key()
    fresh = case.call(pooled_factory, fresh_key)
    assert code(again) in (403, 404), (name, again.text)
    assert (code(again), error_of(again)) == (code(fresh), error_of(fresh)), name
    receipt_values = _receipt_ids(first)
    assert receipt_values, "the receipt names no id to look for"
    assert not any(v in again.text for v in receipt_values), "a stored receipt leaked"
    assert state(w, key) == stored, name
    assert state(w, fresh_key)[RECEIPT] == 0
    assert idle_in_transaction(w.engine) == 0


@pytest.mark.parametrize("name", ("session_schedule", "event_void"))
def test_a_still_authorized_replay_returns_the_receipt_unchanged_after_one_final_statement(
    name: str, w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    case = build_case(name, w, pooled_factory)
    key = new_key()
    first = case.call(pooled_factory, key)
    assert code(first) == case.ok
    with Recorder(pooled) as recorded:
        replay = case.call(pooled_factory, key)
    assert (code(replay), replay.json()) == (code(first), replay_body(first.json()))
    finals = [s for s in recorded.events if FINAL_RE.search(s)]
    assert len(finals) == 1 and recorded.events[-2:] == [finals[0], "COMMIT"]
    # A replay runs no command: no scope lock, no write beyond the key's own no-op insert.
    assert not any(ROW_LOCK_RE.search(s) for s in recorded.events), recorded.events
    writes = [s for s in recorded.events if s.startswith(("INSERT", "UPDATE", "DELETE"))]
    assert all("security.idempotent_requests" in s and "ON CONFLICT" in s for s in writes), writes


@pytest.mark.parametrize("name", CASES)
def test_a_replay_judges_the_same_requirements_as_the_fresh_request(
    name: str, w: World, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What a replay judges is what the fresh request's first decision judged: the route's `canon.edit`
    requirement, registered by the dependency before the handler (so before any replay can answer). The
    command adds `campaign.canon.edit` under its locks; both read `canon.edit` from the same snapshot
    and the route's is registered first, so the command's can never be the first to refuse. No S4 route
    registers a world, Foundry or targeted requirement."""
    seen: list[list[str]] = []
    original = AuthorizationPlan.finalize

    def spy(self: AuthorizationPlan, connection: Any) -> Any:
        seen.append([r.name for r in self.requirements])
        return original(self, connection)

    monkeypatch.setattr(AuthorizationPlan, "finalize", spy)
    case = build_case(name, w, pooled_factory)
    seen.clear()  # the seeding requests are not under test
    key = new_key()
    assert code(case.call(pooled_factory, key)) == case.ok
    assert code(case.call(pooled_factory, key)) == case.ok
    fresh, replayed = seen
    assert fresh == ["route.canon.edit", "campaign.canon.edit"], (name, fresh)
    assert replayed == fresh[:1], (name, fresh, replayed)
    assert len(set(fresh)) == len(fresh)


# --- ordering: the final statement is the last statement before COMMIT, and takes no row lock -------------------------


@pytest.mark.parametrize("name", CASES)
def test_the_final_statement_is_the_last_before_commit_and_takes_no_row_lock(
    name: str, w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    case = build_case(name, w, pooled_factory)
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


@pytest.mark.parametrize("name", ("session_schedule", "event_void"))
def test_a_handler_that_forgets_to_finalize_is_a_sanitized_500_that_persists_nothing(
    name: str, w: World, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = build_case(name, w, pooled_factory)
    key = new_key()
    before = state(w, key)
    monkeypatch.setattr(AuthorizationPlan, "finalize", lambda self, connection: None)
    refused = case.call(pooled_factory, key)
    assert code(refused) == 500
    assert error_of(refused) == "internal_error"
    assert state(w, key) == before
    assert idle_in_transaction(w.engine) == 0
    monkeypatch.undo()
    # the pooled connection is clean: the same key now commits its own work and nothing else
    assert code(case.call(pooled_factory, key)) == case.ok
    assert state(w, key)[RECEIPT] == 1


# --- V-T1: the events trigger takes no row lock at COMMIT --------------------------------------------------------------


def _sample_blockers(engine: Engine, pid: int, request: Any) -> list[list[int]]:
    """The backends blocking `pid`, sampled until the request returns. A request that waits on a lock
    shows up here and also cannot return while the competitor holds it."""
    seen: list[list[int]] = []
    deadline = time.monotonic() + WAIT_SECONDS
    while not request.finished() and time.monotonic() < deadline:
        with engine.connect() as connection:
            blockers = connection.execute(
                text("SELECT pg_blocking_pids(:p)"), {"p": pid}
            ).scalar_one()
        seen.append(list(blockers))
        time.sleep(0.01)
    return seen


@pytest.mark.parametrize("name", ("event_void", "event_correct"))
def test_v_t1_the_deferred_events_trigger_takes_no_row_lock_at_commit(
    name: str, w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    """Plan 12.6 V-T1 for the two S4 routes that update an event's status (the only writers of
    `event_status_id`, which fires `ctr_events_status_has_correction` at COMMIT).

    The request is held before its final statement, so its event update, the correction insert, the audit
    row and the receipt are done and only the final statement and COMMIT remain. A competitor then takes
    the strongest row locks it can on the rows the trigger reads and on the other correction rows, and
    stays open while the request is released. The competitor cannot lock the request's own event or its
    new correction row (the request holds them), and `FOR UPDATE` on a status row would wait behind the
    request's own foreign-key `KEY SHARE`, so it takes `FOR NO KEY UPDATE` there.

    The request must commit while the competitor still holds everything, and its backend must never be
    blocked. What this establishes is that this trigger's reads wait for no row lock held by others, on
    these two routes; it does not establish anything about the trigger's relation locks (plan 5, item
    2), which are `AccessShareLock`s."""
    # an earlier, committed correction gives the competitor a correction row of this world to lock
    earlier = build_case("event_void", w, pooled_factory)
    assert code(earlier.call(pooled_factory, new_key())) == 200
    case = build_case(name, w, pooled_factory)
    key = new_key()
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread("s4-request", lambda: case.call(pooled_factory, key))
        gate.wait_reached()
        assert gate.pid is not None
        with w.engine.connect() as competitor:
            transaction = competitor.begin()
            statuses = competitor.execute(
                text("SELECT event_status_id FROM narrative.event_statuses FOR NO KEY UPDATE")
            ).all()
            corrections = competitor.execute(
                text("SELECT event_correction_id FROM narrative.event_corrections FOR UPDATE")
            ).all()
            assert statuses and corrections
            gate.release()
            blockers = _sample_blockers(w.engine, gate.pid, request)
            response = request.wait("the request commits while the competitor holds its locks")
            assert code(response) == 200, (name, response.text)
            transaction.rollback()
    assert blockers, "the request was never observed"
    assert all(b == [] for b in blockers), blockers
    assert state(w, key)[RECEIPT] == 1
