# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S2: the real guard on the six migrated profile and revelation routes, over real HTTP.

Plan sections 6.3, 6.5, 6.6, 12.3 and 12.5. S1's evidence was synthetic (a scratch table and a toy
route). Everything here goes through the actual migrated routes of `create_app()` on a migrated
database, with the real commit guard installed on the engine, so it shows what the plan promises about
the routes themselves:

- **Freshness.** A role that lapses after the request's last lock wait, but before its final statement,
  refuses every one of the six routes with the refusal the early check gives, and nothing persists:
  no draft, release, revelation or revocation, no audit row, no receipt, and the key is reusable.
- **Command requirements.** A deny that commits after the last lock but before the final statement
  (written directly, the way no application command can while the request holds its locks) is refused
  with the error class of the early check (403 `public_profile_edit_denied`, 404 for a whole-character
  deny).
- **Cleanup.** The refused request returns its pooled connection clean, and the next request on the same
  one-connection pool commits only its own work (T0).
- **Replay.** A lapse during the key-lock wait of a replay refuses it and returns nothing from the
  receipt; a still-authorized replay returns the stored receipt unchanged.
- **Ordering.** On every success path the final authority statement is the last one before COMMIT and takes
  no row lock; a handler that forgets to finalize is a sanitized 5xx that persists nothing.
- **Coherence.** A group-keyed deny and the actor's removal from that group, committed in one
  transaction, are seen together.
"""

import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.api.idempotency import lock_idempotency_key
from dnd_ai.commands.character_public_profile import save_character_public_profile_draft
from dnd_ai.commands.character_revelations import create_character_revelation
from dnd_ai.domain.authorization import AuthorizationPlan, install_authorization_guard
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (
    body,
    code,
    deny,
    error_code,
    release,
    save,
)
from tests.database.test_character_public_profile_copy import _describe, copy
from tests.database.test_character_public_profile_restrictions import npc  # noqa: F401 - fixture
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_character_revelations import create as create_revelation
from tests.database.test_character_revelations import member_body
from tests.database.test_player_profile_copy import copy_pp
from tests.factories import make_access_group, make_access_group_membership, oidc_principal
from tests.http_race_support import (
    StatementGate,
    new_key,
    run_in_thread,
    wait_until_pid_blocks,
)
from tests.player_profile_support import markers, seed_player_profile
from tests.r01_support import fixture_plan

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

#: The R01 final statement: the single-statement authority reader at a fresh instant. The early
#: checks use `now()`, so this text names only the final check (and a replay's re-check).
FINAL = r"^WITH clock AS MATERIALIZED \(SELECT clock_timestamp\(\) AS t_auth\)"
FINAL_RE = re.compile(FINAL)
ROW_LOCK_RE = re.compile(r"\bFOR (UPDATE|SHARE|KEY SHARE|NO KEY UPDATE)\b")
LAPSE_SECONDS = 10

PROFILE_COMMANDS = (
    "save_character_public_profile_draft",
    "copy_legacy_text_to_public_profile_draft",
    "copy_player_profile_field_to_public_profile_draft",
    "release_character_public_profile",
    "create_character_revelation",
    "revoke_character_revelation",
)


# --- the app, on a one-connection pool ----------------------------------------------------------------------------


@pytest.fixture
def pooled(postgres_engine: Engine) -> Iterator[Engine]:
    """The application's engine for these tests: one connection, no overflow, READ COMMITTED enforced
    and the real guard installed (what `get_engine` does). A connection a refusal leaves in a
    transaction would be reused by the very next request."""
    engine = create_engine(
        postgres_engine.url, pool_size=1, max_overflow=0, isolation_level="READ COMMITTED"
    )
    install_authorization_guard(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def pooled_factory(pooled: Engine) -> Factory:
    def make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: pooled
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return make


# --- one case per migrated route -----------------------------------------------------------------------------------


@dataclass
class Case:
    name: str
    character: uuid.UUID
    actor_user_id: uuid.UUID
    actor_membership: uuid.UUID
    role: uuid.UUID
    call: Callable[[Factory, str | None], Any]
    ok: int
    # what a `canon.edit` deny and a `campaign.view` deny on the character must produce
    edit_deny: tuple[int, str] | None
    view_deny: tuple[int, str] | None


CASES = (
    "save",
    "legacy_copy",
    "player_profile_copy",
    "release",
    "revelation_create",
    "revelation_revoke",
)


def _seed_release(engine: Engine, g: Gate, character: uuid.UUID) -> None:
    """A draft and one release of it, written by the owner through the commands (pending plans:
    this is fixture seeding, not what is under test)."""
    with engine.begin() as connection:
        save_character_public_profile_draft(
            connection,
            campaign_id=g.campaign_id,
            character_id=character,
            actor_user_id=g.o1_user_id,
            expected_row_version=None,
            fields={"public_summary": "A released summary"},
            plan=fixture_plan(connection, g.campaign_id),
        )
    with engine.begin() as connection:
        from dnd_ai.commands.character_public_profile import release_character_public_profile

        release_character_public_profile(
            connection,
            campaign_id=g.campaign_id,
            character_id=character,
            actor_membership_id=g.o1,
            expected_draft_row_version=1,
            release_note=None,
            plan=fixture_plan(connection, g.campaign_id),
        )


def build_case(name: str, engine: Engine, g: Gate, m: Members, npc: uuid.UUID) -> Case:
    """The seeded state and the HTTP call of one migrated route. The GM (`m`) is the actor: it holds
    `canon.edit` through its `gm` role and `character.reveal` through a live delegation bound to that
    role, so one lapse of the role removes everything the request relies on."""
    gm = m.gm_user_id
    common: dict[str, Any] = {
        "name": name,
        "character": npc,
        "actor_user_id": gm,
        "actor_membership": m.gm,
        "role": m.gm_role,
        "ok": 201,
        "edit_deny": None,
        "view_deny": None,
    }
    edit = (403, "public_profile_edit_denied")
    whole = (404, "not_found")
    if name == "save":
        return Case(
            **{**common, "edit_deny": edit},
            call=lambda f, key: save(
                f,
                gm,
                g,
                npc,
                {"expected_row_version": None, "public_summary": "S2 summary"},
                key=key,
            ),
        )
    if name == "legacy_copy":
        _describe(engine, npc, appearance="Legacy appearance text for S2")
        return Case(
            **{**common, "edit_deny": edit},
            call=lambda f, key: copy(f, gm, g, npc, None, "appearance", key=key),
        )
    if name == "player_profile_copy":
        seed_player_profile(
            engine,
            campaign_id=g.campaign_id,
            character_id=npc,
            editor_membership_id=g.o1,
            fields=markers("S2"),
        )
        return Case(
            **{**common, "edit_deny": edit},
            call=lambda f, key: copy_pp(f, gm, g, npc, key=key),
        )
    if name == "release":
        with engine.begin() as connection:
            save_character_public_profile_draft(
                connection,
                campaign_id=g.campaign_id,
                character_id=npc,
                actor_user_id=g.o1_user_id,
                expected_row_version=None,
                fields={"public_summary": "A summary to release"},
                plan=fixture_plan(connection, g.campaign_id),
            )
        return Case(
            **{**common, "view_deny": whole},
            call=lambda f, key: release(f, gm, g, npc, 1, key=key),
        )
    _seed_release(engine, g, npc)
    if name == "revelation_create":
        return Case(
            **{**common, "view_deny": whole},
            call=lambda f, key: create_revelation(f, gm, g, npc, member_body(g.player), key=key),
        )
    assert name == "revelation_revoke"
    with engine.begin() as connection:
        made = create_character_revelation(
            connection,
            campaign_id=g.campaign_id,
            character_id=npc,
            actor_membership_id=g.o1,
            audience_kind="member",
            target_campaign_membership_id=g.player,
            target_access_group_id=None,
            reason="Seeded",
            reserve=lambda: False,
            plan=fixture_plan(connection, g.campaign_id),
        )
    assert made is not None
    revelation = made.character_revelation_id

    def revoke(f: Factory, key: str | None) -> Any:
        headers = {"Idempotency-Key": key} if key else {}
        with f(gm) as client:
            return client.post(
                f"/campaigns/{g.campaign_id}/characters/{npc}/revelations/{revelation}/revoke",
                json={"reason": "S2 revoke"},
                headers=headers,
            )

    return Case(**{**common, "ok": 200, "view_deny": whole}, call=revoke)


def state(engine: Engine, g: Gate, character: uuid.UUID, key: str | None = None) -> tuple[Any, ...]:
    """Everything a refused protected write must leave alone."""
    with engine.connect() as connection:
        draft = connection.execute(
            text("""
                SELECT row_version, public_appearance, public_background, public_summary
                FROM campaign.character_public_profiles WHERE campaign_id = :c AND character_id = :ch
            """),
            {"c": g.campaign_id, "ch": character},
        ).one_or_none()
        releases = connection.execute(
            text("""
                SELECT version_number FROM campaign.character_public_profile_releases
                WHERE campaign_id = :c AND character_id = :ch ORDER BY version_number
            """),
            {"c": g.campaign_id, "ch": character},
        ).all()
        revelations = connection.execute(
            text("""
                SELECT character_revelation_id, ended_at IS NOT NULL FROM security.character_revelations
                WHERE campaign_id = :c AND character_id = :ch ORDER BY character_revelation_id
            """),
            {"c": g.campaign_id, "ch": character},
        ).all()
        audit = connection.execute(
            text("""
                SELECT count(*) FROM audit.change_log
                WHERE world_id = :w AND command_name = ANY(:names)
            """),
            {"w": g.world_id, "names": list(PROFILE_COMMANDS)},
        ).scalar_one()
        receipts = (
            connection.execute(
                text(
                    "SELECT count(*) FROM security.idempotent_requests WHERE idempotency_key = :k"
                ),
                {"k": key},
            ).scalar_one()
            if key
            else None
        )
    return (
        None if draft is None else tuple(draft),
        [tuple(r) for r in releases],
        [tuple(r) for r in revelations],
        audit,
        receipts,
    )


def idle_in_transaction(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("""
                    SELECT count(*) FROM pg_stat_activity
                    WHERE datname = current_database() AND state LIKE 'idle in transaction%'
                """)
            ).scalar_one()
        )


def set_lapse(engine: Engine, role: uuid.UUID, seconds: int = LAPSE_SECONDS) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = now() + make_interval(secs => :s) "
                "WHERE membership_role_id = :r"
            ),
            {"s": seconds, "r": role},
        )


def wait_lapsed(engine: Engine, role: uuid.UUID) -> None:
    """Polls the DATABASE condition (never a sleep for a fixed time): the role's `expires_at` is past."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            if connection.execute(
                text(
                    "SELECT expires_at <= clock_timestamp() FROM security.membership_roles "
                    "WHERE membership_role_id = :r"
                ),
                {"r": role},
            ).scalar_one():
                return
        threading.Event().wait(0.1)
    raise AssertionError("the role never lapsed")


def run_gated_before_final(
    engine: Engine, app_engine: Engine, call: Callable[[], Any], *, during: Callable[[], None]
) -> Any:
    """Runs `call` (an HTTP request) to the instant before its final authority statement, runs `during`
    (a change that commits now), releases the request and returns its response."""
    with StatementGate(app_engine, FINAL) as gate:
        request = run_in_thread("s2-request", call)
        gate.wait_reached()
        during()
        gate.release()
        return request.wait("the gated request finishes")


#: The idempotency key lock: the request's first lock, taken after the route's early checks.
KEY_LOCK_RE = r"pg_advisory_xact_lock"


def run_lapsing_before_final(
    engine: Engine, app_engine: Engine, role: uuid.UUID, call: Callable[[], Any]
) -> Any:
    """Runs `call` (an HTTP request) so that `role` is valid for every early check and has lapsed by the
    final authority statement, however fast or slow the request runs.

    The request is paused at its idempotency key lock (it has passed its early checks and holds no row
    lock), `expires_at` is set to the request's own transaction start plus one second (every early check
    judges at `now()`, that start; the final check judges at `clock_timestamp()`), and the request is
    then paused again at its final statement until the database reports the role lapsed. A window that
    starts before the request does can expire before the request enters, which refuses it early and never
    reaches the final statement (the failure mode of the first version of these tests)."""
    with StatementGate(app_engine, KEY_LOCK_RE) as first, StatementGate(app_engine, FINAL) as final:
        request = run_in_thread("s2-request", call)
        try:
            first.wait_reached()
        except AssertionError as missed:
            # say what the request did instead of reaching its key lock (a refusal before it, an error)
            outcome = (
                f"{request.result.status_code} {request.result.text}"
                if request.finished() and request.result is not None
                else repr(request.error)
                if request.finished()
                else "still running"
            )
            raise AssertionError(f"{missed}; the request: {outcome}") from None
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            moved = connection.execute(
                text("""
                    UPDATE security.membership_roles
                    SET expires_at = (
                        SELECT xact_start FROM pg_stat_activity WHERE pid = :pid
                    ) + interval '1 second'
                    WHERE membership_role_id = :r AND revoked_at IS NULL
                """),
                {"pid": first.pid, "r": role},
            ).rowcount
            assert moved == 1
        first.release()
        final.wait_reached()
        wait_lapsed(engine, role)
        final.release()
        return request.wait("the gated request finishes")


# --- freshness: the role lapses between the last lock wait and the final statement -----------------------------------


@pytest.mark.parametrize("name", CASES)
def test_a_role_that_lapses_before_the_final_statement_refuses_the_route_and_persists_nothing(
    name: str,
    postgres_engine: Engine,
    pooled: Engine,
    pooled_factory: Factory,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    case = build_case(name, postgres_engine, g, m, npc)
    key = new_key()
    before = state(postgres_engine, g, case.character, key)
    response = run_lapsing_before_final(
        postgres_engine, pooled, case.role, lambda: case.call(pooled_factory, key)
    )
    # The refusal is the one the early check gives a caller whose role is gone.
    refused = (code(response), error_code(response))
    assert refused[0] in (403, 404), (name, refused, response.text)
    # Nothing persisted: no row, no audit row, no receipt.
    assert state(postgres_engine, g, case.character, key) == before
    # The pooled connection is clean: not idle in a transaction, and the next request on it commits
    # only its own work (a leaked transaction would commit the refused write here).
    assert idle_in_transaction(postgres_engine) == 0
    with pooled_factory(g.o1_user_id) as client:
        read_back = client.get(
            f"/campaigns/{g.campaign_id}/characters/{case.character}/public-profile"
        )
    assert code(read_back) in (200, 404), (name, body(read_back))
    assert state(postgres_engine, g, case.character, key) == before
    # The early refusal of the same caller (role revoked before the request) is the same refusal.
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": case.role},
        )
    early = case.call(pooled_factory, new_key())
    assert (code(early), error_code(early)) == refused, (name, early.text)


@pytest.mark.parametrize("name", CASES)
def test_the_key_of_a_refused_request_is_reusable_once_the_actor_is_authorized_again(
    name: str,
    postgres_engine: Engine,
    pooled: Engine,
    pooled_factory: Factory,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    case = build_case(name, postgres_engine, g, m, npc)
    key = new_key()
    refused = run_lapsing_before_final(
        postgres_engine, pooled, case.role, lambda: case.call(pooled_factory, key)
    )
    assert code(refused) in (403, 404)
    assert state(postgres_engine, g, case.character, key)[4] == 0
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = NULL WHERE membership_role_id = :r"
            ),
            {"r": case.role},
        )
    again = case.call(pooled_factory, key)
    assert code(again) == case.ok, (name, again.text)
    assert state(postgres_engine, g, case.character, key)[4] == 1


# --- command requirements: a deny committed after the last lock, before the final statement ------------------------


@pytest.mark.parametrize("name", CASES)
def test_a_deny_committed_before_the_final_statement_is_refused_with_the_early_checks_error(
    name: str,
    postgres_engine: Engine,
    pooled: Engine,
    pooled_factory: Factory,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    case = build_case(name, postgres_engine, g, m, npc)
    denies = [
        (capability, expected)
        for capability, expected in (
            ("canon.edit", case.edit_deny),
            ("campaign.view", case.view_deny),
        )
        if expected is not None
    ]
    assert len(denies) == 1, name
    capability, (status, error) = denies[0]
    key = new_key()
    before = state(postgres_engine, g, case.character, key)
    response = run_gated_before_final(
        postgres_engine,
        pooled,
        lambda: case.call(pooled_factory, key),
        during=lambda: deny(postgres_engine, g, case.actor_membership, capability, case.character),
    )
    assert (code(response), error_code(response)) == (status, error), (name, response.text)
    assert state(postgres_engine, g, case.character, key) == before
    assert idle_in_transaction(postgres_engine) == 0


# --- coherence: one snapshot sees a group-keyed deny and the removal of the actor from that group together ------------


def test_a_group_deny_and_the_actors_removal_from_the_group_are_seen_together(
    postgres_engine: Engine,
    pooled: Engine,
    pooled_factory: Factory,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    """The actor is in group G. In ONE transaction, committed while the save waits at its final
    statement, G receives a `canon.edit` deny on the character and the actor leaves G. The decision must
    see both (the deny no longer reaches the actor: allowed) or neither (allowed). Seeing the deny
    without the removal would refuse a caller no state ever refused."""
    from tests.factories import lookup_id

    with postgres_engine.begin() as connection:
        group = make_access_group(connection, g.campaign_id, name="Coherence Group")
        membership = make_access_group_membership(connection, group, m.gm)
    case = build_case("save", postgres_engine, g, m, npc)
    key = new_key()

    def commit_both() -> None:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO security.resource_grants
                        (campaign_id, timeline_id, capability_id, grantee_access_group_id, entity_id,
                         effect, grant_source)
                    VALUES (:c, :t, :cap, :grp, :e, 'deny', 'test')
                """),
                {
                    "c": g.campaign_id,
                    "t": g.timeline_id,
                    "cap": lookup_id(
                        connection, "security", "capabilities", "capability_id", "canon.edit"
                    ),
                    "grp": group,
                    "e": npc,
                },
            )
            connection.execute(
                text(
                    "UPDATE security.access_group_memberships SET removed_at = now() "
                    "WHERE access_group_membership_id = :m"
                ),
                {"m": membership},
            )

    response = run_gated_before_final(
        postgres_engine, pooled, lambda: case.call(pooled_factory, key), during=commit_both
    )
    assert code(response) == case.ok, response.text


# --- replay (R-D4) -------------------------------------------------------------------------------------------------


def test_a_lapse_during_a_replays_key_lock_wait_refuses_it_and_returns_nothing_from_the_receipt(
    postgres_engine: Engine,
    pooled: Engine,
    pooled_factory: Factory,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    case = build_case("save", postgres_engine, g, m, npc)
    key = new_key()
    first = case.call(pooled_factory, key)
    assert code(first) == 201, first.text
    stored = state(postgres_engine, g, case.character, key)
    assert stored[4] == 1

    # The test holds the same key lock the request takes inside `begin_idempotent_request`, so the
    # replay genuinely waits there. The key lock precedes every row lock of the request, so the role
    # can be set to lapse once the replay is observed waiting (no dependence on request speed).
    with postgres_engine.connect() as holder:
        transaction = holder.begin()
        lock_idempotency_key(
            holder, actor_user_id=case.actor_user_id, campaign_id=g.campaign_id, idempotency_key=key
        )
        pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
        replay = run_in_thread("replay", lambda: case.call(pooled_factory, key))
        wait_until_pid_blocks(postgres_engine, pid)
        set_lapse(postgres_engine, case.role, 1)
        wait_lapsed(postgres_engine, case.role)
        transaction.commit()
    response = replay.wait("the replay finishes")
    assert code(response) in (403, 404), response.text
    assert "character_public_profile_id" not in response.text, "a receipt leaked to a lapsed caller"
    assert state(postgres_engine, g, case.character, key) == stored
    assert idle_in_transaction(postgres_engine) == 0


def test_a_still_authorized_replay_returns_the_receipt_unchanged_after_one_final_statement(
    postgres_engine: Engine,
    pooled: Engine,
    pooled_factory: Factory,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    case = build_case("save", postgres_engine, g, m, npc)
    key = new_key()
    first = case.call(pooled_factory, key)
    assert code(first) == 201
    with Recorder(pooled) as recorded:
        replay = case.call(pooled_factory, key)
    assert (code(replay), replay.json()) == (code(first), first.json())
    finals = [s for s in recorded.events if FINAL_RE.search(s)]
    assert len(finals) == 1 and recorded.events[-2] == finals[0] and recorded.events[-1] == "COMMIT"
    # A replay runs no command: no scope lock, no write.
    assert not any(ROW_LOCK_RE.search(s) for s in recorded.events), recorded.events
    # The only write statement is the receipt lookup, `INSERT ... ON CONFLICT DO NOTHING`, which
    # inserts no row on a replay (plan 6.6); no command or profile table is written.
    writes = [s for s in recorded.events if s.startswith(("INSERT", "UPDATE", "DELETE"))]
    assert all("security.idempotent_requests" in s and "ON CONFLICT" in s for s in writes), writes


# --- ordering: the final statement is the last statement before COMMIT, and takes no row lock -------------------------


class Recorder:
    """Every statement the application engine executes and every COMMIT, in order."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.events: list[str] = []

    def _statement(self, _conn: Any, _cursor: Any, statement: Any, *_: Any) -> None:
        self.events.append(" ".join(str(statement).split()))

    def _commit(self, _conn: Any) -> None:
        self.events.append("COMMIT")

    def __enter__(self) -> "Recorder":
        event.listen(self.engine, "before_cursor_execute", self._statement)
        event.listen(self.engine, "commit", self._commit)
        return self

    def __exit__(self, *_: object) -> None:
        event.remove(self.engine, "before_cursor_execute", self._statement)
        event.remove(self.engine, "commit", self._commit)


@pytest.mark.parametrize("name", CASES)
def test_the_final_statement_is_the_last_before_commit_and_takes_no_row_lock(
    name: str,
    postgres_engine: Engine,
    pooled: Engine,
    pooled_factory: Factory,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    case = build_case(name, postgres_engine, g, m, npc)
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
    postgres_engine: Engine,
    pooled: Engine,
    pooled_factory: Factory,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_case("save", postgres_engine, g, m, npc)
    before = state(postgres_engine, g, case.character)
    monkeypatch.setattr(AuthorizationPlan, "finalize", lambda self, connection: None)
    refused = case.call(pooled_factory, new_key())
    assert code(refused) == 500
    assert error_code(refused) == "internal_error"
    assert "plan" not in refused.text.lower() and "finalize" not in refused.text.lower()
    assert state(postgres_engine, g, case.character) == before
    assert idle_in_transaction(postgres_engine) == 0
    monkeypatch.undo()
    assert code(case.call(pooled_factory, new_key())) == 201


# --- the revelation requirement does not depend on the rows its command writes (plan 6.3) ---------------------------


def test_a_revelation_naming_the_actor_is_created_and_revoked_through_the_final_check(
    postgres_engine: Engine,
    pooled: Engine,
    pooled_factory: Factory,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    """`resolve_access_context` reads `security.character_revelations`, which the create and the revoke
    write. The reveal requirement must not depend on them: a revelation whose audience is the actor
    itself still passes the final check, whether it is created or revoked."""
    _seed_release(postgres_engine, g, npc)
    with pooled_factory(m.gm_user_id) as client:
        created = client.post(
            f"/campaigns/{g.campaign_id}/characters/{npc}/revelations",
            json=member_body(m.gm),
            headers={"Idempotency-Key": new_key()},
        )
        assert code(created) == 201, created.text
        revelation = created.json()["character_revelation_id"]
        revoked = client.post(
            f"/campaigns/{g.campaign_id}/characters/{npc}/revelations/{revelation}/revoke",
            json={"reason": "No longer needed"},
            headers={"Idempotency-Key": new_key()},
        )
        assert code(revoked) == 200, revoked.text
    assert state(postgres_engine, g, npc)[2] == [(uuid.UUID(revelation), True)]
