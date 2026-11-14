# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S4b: the real guard on the route-capability-only write routes, over real HTTP.

Plan sections 4.2, 6.3, 6.5, 6.6, 7.3, 12.3, 12.5 and 12.6 (V-T1). These 21 routes call no scope helper and
hold no actor row (S0 finding F-1), so the request's one authority decision is the route dependency's:
`route.<capability>`, plus, for the five Foundry-callable routes, the credential's scope and campaign
binding in the same decision. Everything here goes through the actual migrated routes of `create_app()` on a
migrated database with the real commit guard installed on a one-connection pool.

One case per distinct authorization family (the other 12 routes share a family with a driven one and are
pinned by `tests/unit/test_r01_s4b_route_shape.py` and by their existing API tests, which now pass through
the final statement):

| family | case | route |
|---|---|---|
| idempotent, audited, `canon.edit` | `event`, `external_system` | 11, 17 |
| idempotent, audited, Foundry `character_state_sync` | `hit_points` (browser), `hit_points_foundry` | 3 |
| no idempotency, no audit, `canon.edit` | `encounter_start` | 8 |
| no idempotency, audited, Foundry `combat_sync` | `identifier_foundry` | 18 |
| no idempotency, audited, `rules_source.manage` | `source_register`, `source_remove` | 19, 20 |
| no idempotency, no audit, `campaign.view` | `pairing_code` | 21 |

What is shown, and what is not:

- **Freshness.** A role that lapses after the request's writes and before its final statement refuses the
  route with the refusal the early check gives, and nothing persists: no row, no audit row, no receipt, and
  the key is reusable. The expiry is set in the database while the request waits at the final statement,
  and the test polls the database until it has passed.
- **Concurrent change (plan 4.2 and 7.3).** These routes stabilise nothing, so a revocation is not made to
  wait. One committed before the final statement is seen (the request is refused); one committed after it,
  before COMMIT, is serialised after the request (both commit; the next request is refused).
- **Replay (R-D4).** A lapse during a replay's key-lock wait, and a role revoked or a membership ended
  before it, refuse it like a fresh key and return nothing from the receipt; an authorized replay returns the
  stored receipt after one final statement.
- **Foundry (S4b-4).** The scope and campaign binding are facts of the authenticated principal, captured at
  the start of the request and judged again in the final decision, in the dependency's own order. They are
  not database inputs of the final statement: explicit device or connection revocation follows plan 2.1's
  recommended decision (judged at the start of the request) and natural expiry R-D3. So no test revokes a
  device mid-request, and none claims that this is refused.
- **Ordering and cleanup.** On every success path the final statement is the last before COMMIT and takes no
  row lock; a handler that forgets it is a sanitized 500 that persists nothing and returns a clean pooled
  connection.
- **V-T1.** No S4b route updates `narrative.events.event_status_id`, so none fires the deferred trigger; the
  bounded competitor probe is repeated on the event route and that fact is asserted from the statements.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.api.access import FoundryRouteFacts, route_capability_requirement
from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.api.errors import ForbiddenError, NotFoundError
from dnd_ai.api.idempotency import lock_idempotency_key
from dnd_ai.commands.memberships import revoke_membership_role
from dnd_ai.domain.access import FOUNDRY_ACCESS_AUTH_METHOD, AuthenticatedPrincipal
from dnd_ai.domain.authorization import AuthorizationPlan
from dnd_ai.domain.data_classification import replay_body
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    FINAL,
    FINAL_RE,
    ROW_LOCK_RE,
    Recorder,
    idle_in_transaction,
    pooled,
    wait_lapsed,
)
from tests.database.test_r01_s4_operation_routes import (  # noqa: F401 - fixtures used by name
    RECEIPT,
    World,
    _end_membership,
    _receipt_ids,
    _sample_blockers,
    _time,
    code,
    error_of,
    w,
)
from tests.factories import (
    lookup_id,
    make_character,
    make_character_state,
    make_external_system,
    make_foundry_connection,
    make_foundry_device,
    make_membership_role,
    make_role,
    make_role_capability,
    oidc_principal,
)
from tests.http_race_support import (
    StatementGate,
    new_key,
    run_in_thread,
    wait_until_pid_blocks,
)

pytestmark = pytest.mark.database


# --- the app, with a browser client and a Foundry client on the one-connection pool ---------------------------------


class Clients:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _client(self, principal: AuthenticatedPrincipal) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: self.engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: principal
        return TestClient(app, raise_server_exceptions=False)

    def browser(self, user_id: uuid.UUID) -> TestClient:
        return self._client(oidc_principal(user_id))

    def foundry(self, principal: AuthenticatedPrincipal) -> TestClient:
        return self._client(principal)


@pytest.fixture
def clients(pooled: Engine) -> Clients:
    return Clients(pooled)


# --- the world's extra facts: a character with state, an external system, a source-managing role ---------------------


@dataclass
class Ctx:
    w: World
    timeline_id: uuid.UUID
    ruleset_version_id: uuid.UUID
    character: uuid.UUID
    external_system: uuid.UUID
    world_time: str
    manage_role: uuid.UUID  # a membership role of the GM holding `rules_source.manage`


@pytest.fixture
def ctx(w: World, clients: Clients) -> Ctx:
    with w.engine.begin() as connection:
        timeline_id, ruleset_version_id = connection.execute(
            text(
                "SELECT timeline_id, ruleset_version_id FROM campaign.campaigns "
                "WHERE campaign_id = :c"
            ),
            {"c": w.campaign_id},
        ).one()
        character = make_character(connection, w.world_id, name="S4b Hero")
        make_character_state(
            connection, timeline_id, character, current_hit_points=10, maximum_hit_points=20
        )
        external_system = make_external_system(connection, w.world_id)
        capability = lookup_id(
            connection, "security", "capabilities", "capability_id", "rules_source.manage"
        )
        role = make_role(connection, campaign_id=w.campaign_id)
        make_role_capability(connection, role, capability)
        manage_role = make_membership_role(connection, w.gm_membership, role)
    world_time = _time(w, clients.browser, "S4b time")
    return Ctx(
        w, timeline_id, ruleset_version_id, character, external_system, world_time, manage_role
    )


def foundry_principal(
    c: Ctx, *, scopes: frozenset[str], campaign_id: uuid.UUID | None = None
) -> AuthenticatedPrincipal:
    """A Foundry access principal for the GM, paired with the world's external system. The audit rows of
    these routes name the connection and device, so they are real rows."""
    with c.w.engine.begin() as connection:
        connection_id = make_foundry_connection(
            connection,
            user_id=c.w.gm_user,
            campaign_id=c.w.campaign_id,
            external_system_id=c.external_system,
        )
        device_id = make_foundry_device(connection, connection_id)
    return AuthenticatedPrincipal(
        user_id=c.w.gm_user,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=c.external_system,
        foundry_world_id=c.w.world_id,
        campaign_id=campaign_id or c.w.campaign_id,
        foundry_connection_id=connection_id,
        foundry_device_id=device_id,
        foundry_scopes=scopes,
    )


# --- one case per authorization family ------------------------------------------------------------------------------------


@dataclass
class Case:
    name: str
    call: Callable[[str | None], Any]
    ok: int
    idempotent: bool
    role: uuid.UUID  # the membership role whose lapse must refuse the route
    requirement: str  # the one requirement of the request's plan
    audited: bool = True


CASES = (
    "event",
    "external_system",
    "hit_points",
    "hit_points_foundry",
    "encounter_start",
    "identifier_foundry",
    "source_register",
    "source_remove",
    "pairing_code",
)
IDEMPOTENT = ("event", "external_system", "hit_points", "hit_points_foundry")


def build_case(name: str, c: Ctx, clients: Clients) -> Case:
    w = c.w
    base = w.base
    tag = uuid.uuid4().hex[:8]

    def browser(
        path: str, body: dict[str, Any], method: str = "POST"
    ) -> Callable[[str | None], Any]:
        def call(key: str | None) -> Any:
            headers = {"Idempotency-Key": key} if key else {}
            with clients.browser(w.gm_user) as client:
                return client.request(method, f"{base}{path}", json=body, headers=headers)

        return call

    def foundry(
        path: str, body: dict[str, Any], scopes: frozenset[str]
    ) -> Callable[[str | None], Any]:
        principal = foundry_principal(c, scopes=scopes)

        def call(key: str | None) -> Any:
            headers = {"Idempotency-Key": key} if key else {}
            with clients.foundry(principal) as client:
                return client.post(f"{base}{path}", json=body, headers=headers)

        return call

    hp = {"world_time_id": c.world_time, "delta": -1}
    hp_path = f"/characters/{c.character}/hit-points"
    if name == "event":
        body = {"world_time_id": c.world_time, "event_type_code": "other", "name": f"S4b {tag}"}
        return Case(name, browser("/events", body), 201, True, w.gm_role, "route.canon.edit")
    if name == "external_system":
        body = {"system_type": "foundry", "display_name": f"S4b {tag}"}
        return Case(
            name, browser("/integration/external-systems", body), 201, True, w.gm_role,
            "route.canon.edit",
        )  # fmt: skip
    if name == "hit_points":
        return Case(name, browser(hp_path, hp), 200, True, w.gm_role, "route.canon.edit")
    if name == "hit_points_foundry":
        call = foundry(hp_path, hp, frozenset({"character_state_sync"}))
        return Case(name, call, 200, True, w.gm_role, "route.canon.edit.foundry")
    if name == "encounter_start":
        body = {"world_time_id": c.world_time, "participant_entity_ids": [str(c.character)]}
        return Case(
            name, browser("/encounters", body), 201, False, w.gm_role, "route.canon.edit",
            audited=False,
        )  # fmt: skip
    if name == "identifier_foundry":
        body = {"entity_id": str(c.character), "external_kind": "actor", "external_id": tag}
        path = f"/integration/external-systems/{c.external_system}/identifiers"
        call = foundry(path, body, frozenset({"combat_sync"}))
        return Case(name, call, 200, False, w.gm_role, "route.canon.edit.foundry")
    if name == "pairing_code":
        body = {
            "external_system_id": str(c.external_system),
            "requested_scopes": ["character_state_sync"],
        }
        return Case(
            name, browser("/foundry/pairing-codes", body), 201, False, w.gm_role,
            "route.campaign.view", audited=False,
        )  # fmt: skip
    register = {
        "source_type_code": "rulebook",
        "ruleset_version_id": str(c.ruleset_version_id),
        "title": f"S4b {tag}",
        "classification": "srd",
        "file_hash": uuid.uuid4().hex,
        "source_version_label": "v1",
        "visibility": "general",
    }
    if name == "source_register":
        return Case(
            name, browser("/reference-corpus/sources", register), 201, False, c.manage_role,
            "route.rules_source.manage",
        )  # fmt: skip
    assert name == "source_remove"
    with clients.browser(w.gm_user) as client:
        seeded = client.post(f"{base}/reference-corpus/sources", json=register)
    assert seeded.status_code == 201, seeded.text
    source = seeded.json()["source_document_id"]
    return Case(
        name, browser(f"/reference-corpus/sources/{source}", {}, method="DELETE"), 204, False,
        c.manage_role, "route.rules_source.manage",
    )  # fmt: skip


def state(c: Ctx, key: str | None = None) -> tuple[Any, ...]:
    """What a refused protected write must leave alone: the tables the 21 routes write, for this campaign,
    plus the audit log, the pairing codes and the key's receipt."""
    queries = (
        "SELECT count(*) FROM narrative.events WHERE timeline_id = :t",
        "SELECT count(*) FROM narrative.encounters WHERE campaign_id = :c",
        "SELECT count(*) FROM integration.external_systems WHERE world_id = :w",
        "SELECT count(*) FROM integration.external_identifiers i JOIN integration.external_systems s "
        "USING (external_system_id) WHERE s.world_id = :w",
        "SELECT count(*), count(*) FILTER (WHERE status = 'removed') FROM core.source_documents "
        "WHERE ruleset_version_id = :rv",
        "SELECT count(*) FROM security.foundry_pairing_codes WHERE campaign_id = :c",
        "SELECT current_hit_points FROM campaign.character_state WHERE timeline_id = :t "
        "AND character_id = :ch",
        "SELECT count(*) FROM audit.change_log WHERE actor_user_id = :u",
    )
    parameters = {
        "t": c.timeline_id,
        "c": c.w.campaign_id,
        "w": c.w.world_id,
        "rv": c.ruleset_version_id,
        "ch": c.character,
        "u": c.w.gm_user,
    }
    with c.w.engine.connect() as connection:
        values = tuple(tuple(connection.execute(text(q), parameters).one()) for q in queries)
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
    return (*values, receipt)


def revoke_role(c: Ctx, case: Case) -> None:
    """Revokes the membership role the case's route depends on (the GM's, or the one holding
    `rules_source.manage`)."""
    with c.w.engine.begin() as connection:
        revoke_membership_role(
            connection, membership_role_id=case.role, campaign_id=c.w.campaign_id
        )


def end_membership(c: Ctx, case: Case) -> None:
    _end_membership(c.w)


REVOKERS = pytest.mark.parametrize(
    "revoke", (revoke_role, end_membership), ids=("role", "membership")
)


# --- freshness: a role lapses between the request's writes and its final statement -----------------------------------


#: The request's first write: it has judged its early checks and holds no row lock that a role update
#: needs. (A write that references the campaign holds `KEY SHARE` on its row until the request ends, and
#: any update of a membership role takes that row `FOR UPDATE` at its own COMMIT, through the access-manager
#: retention trigger: such an update waits for the request. S4b's routes hold no scope lock, but a campaign
#: row lock still comes with any row that references the campaign.)
FIRST_WRITE = r"^(INSERT|UPDATE|DELETE) "


def run_lapsing_before_final(
    c: Ctx, app_engine: Engine, role: uuid.UUID, call: Callable[[], Any]
) -> Any:
    """Runs `call` (an HTTP request) so that the route's authority is valid for every early check and has
    lapsed by the final authority statement, with no dependence on how fast the request runs.

    1. The request is paused at its first write: its early checks (judged at its transaction start) are done
       and it holds no row lock, so the test's `UPDATE` of the role row waits for nothing. The update runs
       under a `lock_timeout`, so an unexpected conflict is an error, not a hang.
    2. `expires_at` is set in the database one second ahead of the database clock.
    3. The request runs on, command, audit row and receipt included, and is paused again immediately before
       its final statement. The test polls the DATABASE condition `expires_at <= clock_timestamp()` and
       only then releases it."""
    with StatementGate(app_engine, FIRST_WRITE) as first, StatementGate(app_engine, FINAL) as final:
        request = run_in_thread("s4b-request", call)
        first.wait_reached()
        with c.w.engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            moved = connection.execute(
                text(
                    "UPDATE security.membership_roles SET expires_at = clock_timestamp() + interval "
                    "'1 second' WHERE membership_role_id = :r AND revoked_at IS NULL"
                ),
                {"r": role},
            ).rowcount
            assert moved == 1
        first.release()
        final.wait_reached()
        wait_lapsed(c.w.engine, role)
        final.release()
        return request.wait("the gated request finishes")


@pytest.mark.parametrize("name", CASES)
def test_a_role_that_lapses_before_the_final_statement_refuses_the_route_and_persists_nothing(
    name: str, ctx: Ctx, pooled: Engine, clients: Clients
) -> None:
    case = build_case(name, ctx, clients)
    key = new_key()
    before = state(ctx, key)
    response = run_lapsing_before_final(ctx, pooled, case.role, lambda: case.call(key))
    refused = (code(response), error_of(response))
    assert refused[0] in (403, 404), (name, refused, response.text)
    # nothing persisted: no row, state change, audit row, pairing code or receipt
    assert state(ctx, key) == before, name
    # no protected data left with the refusal
    assert "raw_code" not in response.text and "source_document_id" not in response.text
    # the pooled connection is clean, and the next request on it commits only its own work
    assert idle_in_transaction(ctx.w.engine) == 0
    with clients.browser(ctx.w.owner) as client:
        assert code(client.get(f"{ctx.w.base}/sessions")) in (200, 404)
    assert state(ctx, key) == before, name
    # the early refusal of the same caller (the role gone before the request) is the same refusal
    with ctx.w.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": case.role},
        )
    early = case.call(new_key())
    assert (code(early), error_of(early)) == refused, (name, early.text)


@pytest.mark.parametrize("name", ("event", "hit_points_foundry"))
def test_the_key_of_a_refused_request_is_reusable_once_the_actor_is_authorized_again(
    name: str, ctx: Ctx, pooled: Engine, clients: Clients
) -> None:
    case = build_case(name, ctx, clients)
    key = new_key()
    refused = run_lapsing_before_final(ctx, pooled, case.role, lambda: case.call(key))
    assert code(refused) in (403, 404)
    assert state(ctx, key)[-1] == 0
    with ctx.w.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = NULL WHERE membership_role_id = :r"
            ),
            {"r": case.role},
        )
    again = case.call(key)
    assert code(again) == case.ok, (name, again.text)
    assert state(ctx, key)[-1] == 1


# --- concurrent change (plan 4.2, 7.3): nothing is held, so a revocation is seen or serialised after ------------------


def revoke_in_thread(c: Ctx, case: Case, revoke: Callable[[Ctx, Case], None]) -> Any:
    return run_in_thread("s4b-revoke", lambda: revoke(c, case))


@REVOKERS
@pytest.mark.parametrize("name", ("event", "source_register", "pairing_code"))
def test_a_revocation_committed_before_the_request_holds_the_campaign_is_seen_by_its_final_statement(
    name: str,
    revoke: Callable[[Ctx, Case], None],
    ctx: Ctx,
    pooled: Engine,
    clients: Clients,
) -> None:
    """(a) of plan 12.3 item 5. The request is paused at its first write, holding nothing; the revocation
    commits (it waits for nothing); the request runs on and its final statement sees the revocation: it is
    refused with nothing persisted."""
    case = build_case(name, ctx, clients)
    key = new_key()
    before = state(ctx, key)
    with StatementGate(pooled, FIRST_WRITE) as gate:
        request = run_in_thread("s4b-request", lambda: case.call(key))
        gate.wait_reached()
        revoke(ctx, case)  # returns only once it has committed
        gate.release()
        response = request.wait("the gated request finishes")
    assert code(response) in (403, 404), (name, response.text)
    assert state(ctx, key) == before
    assert idle_in_transaction(ctx.w.engine) == 0


#: The cases whose request holds a row that references the campaign by its final statement (the key's
#: receipt, an audit row, a pairing code): a role update takes the campaign row `FOR UPDATE` at its COMMIT,
#: so it waits for the request.
HOLDS_THE_CAMPAIGN = ("event", "pairing_code")


def _blocked_or_finished(engine: Engine, holder_pid: int, revocation: Any) -> bool:
    """Waits until the revocation is either blocked behind `holder_pid` (returns True) or has finished
    (returns False). Both are observed, never assumed."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if revocation.finished():
            return False
        with engine.connect() as connection:
            blocked = connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid))"
                ),
                {"pid": holder_pid},
            ).scalar_one()
        if blocked:
            return True
        time.sleep(0.02)
    raise AssertionError("the revocation neither waited for the request nor finished")


@REVOKERS
@pytest.mark.parametrize("name", ("event", "pairing_code", "source_register"))
def test_a_revocation_requested_after_the_request_has_written_is_serialised_after_it_or_seen_by_it(
    name: str,
    revoke: Callable[[Ctx, Case], None],
    ctx: Ctx,
    pooled: Engine,
    clients: Clients,
) -> None:
    """(b) of plan 12.3 item 5, observed rather than assumed. The request is paused before its final
    statement, its writes done. The revocation is requested; whichever happens first decides the outcome and
    the test checks the outcome against it:

    - the revocation is blocked behind the request (it needs the campaign row `FOR UPDATE` at COMMIT, which
      conflicts with the request's `KEY SHARE`): the request commits and the revocation commits after it,
      and the next request is refused;
    - the revocation committed first: the final statement sees it and refuses the request."""
    case = build_case(name, ctx, clients)
    key = new_key()
    before = state(ctx, key)
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread("s4b-request", lambda: case.call(key))
        gate.wait_reached()
        assert gate.pid is not None
        revocation = revoke_in_thread(ctx, case, revoke)
        waited = _blocked_or_finished(ctx.w.engine, gate.pid, revocation)
        gate.release()
        response = request.wait("the gated request finishes")
    revocation.wait("the revocation finishes")
    if name in HOLDS_THE_CAMPAIGN:
        assert waited, f"{name}: the revocation was not held behind the request"
    else:
        # the source routes write nothing that names the campaign: the revocation commits at once, so the
        # final statement sees it (plan 4.2: seen if it commits before S)
        assert not waited, f"{name}: the revocation unexpectedly waited"
    if waited:
        assert code(response) == case.ok, (name, response.text)
        if case.idempotent:
            assert state(ctx, key)[-1] == 1
        after = case.call(new_key())
        assert code(after) in (403, 404), (name, after.text)
    else:
        assert code(response) in (403, 404), (name, response.text)
        assert state(ctx, key) == before


# --- replay (R-D4) -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", IDEMPOTENT)
def test_a_lapse_during_a_replays_key_lock_wait_refuses_it_and_returns_nothing_from_the_receipt(
    name: str, ctx: Ctx, pooled: Engine, clients: Clients
) -> None:
    case = build_case(name, ctx, clients)
    key = new_key()
    first = case.call(key)
    assert code(first) == case.ok, first.text
    stored = state(ctx, key)
    assert stored[-1] == 1
    with ctx.w.engine.connect() as holder:
        transaction = holder.begin()
        lock_idempotency_key(
            holder, actor_user_id=ctx.w.gm_user, campaign_id=ctx.w.campaign_id, idempotency_key=key
        )
        pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
        replay = run_in_thread("replay", lambda: case.call(key))
        wait_until_pid_blocks(ctx.w.engine, pid)
        with ctx.w.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE security.membership_roles SET expires_at = clock_timestamp() + interval "
                    "'1 second' WHERE membership_role_id = :r"
                ),
                {"r": case.role},
            )
        wait_lapsed(ctx.w.engine, case.role)
        transaction.commit()
    response = replay.wait("the replay finishes")
    assert code(response) in (403, 404), response.text
    assert response.text != first.text, "a receipt leaked to a lapsed caller"
    assert not any(v in response.text for v in _receipt_ids(first))
    assert state(ctx, key) == stored
    assert idle_in_transaction(ctx.w.engine) == 0


@REVOKERS
@pytest.mark.parametrize("name", IDEMPOTENT)
def test_a_replay_after_the_authority_is_gone_is_refused_exactly_as_a_fresh_key_is(
    name: str, revoke: Callable[[Ctx, Case], None], ctx: Ctx, pooled: Engine, clients: Clients
) -> None:
    case = build_case(name, ctx, clients)
    key = new_key()
    first = case.call(key)
    assert code(first) == case.ok, (name, first.text)
    # still authorized: the stored receipt, unchanged (an unchanged replay of the first answer)
    replay = case.call(key)
    assert code(replay) == code(first), name
    assert replay.json() == replay_body(first.json()) or replay.json() == first.json(), name
    stored = state(ctx, key)
    assert stored[-1] == 1

    revoke(ctx, case)

    again = case.call(key)
    fresh_key = new_key()
    fresh = case.call(fresh_key)
    assert code(again) in (403, 404), (name, again.text)
    assert (code(again), error_of(again)) == (code(fresh), error_of(fresh)), name
    receipt_values = _receipt_ids(first)
    assert receipt_values, "the receipt names no id to look for"
    assert not any(v in again.text for v in receipt_values), "a stored receipt leaked"
    assert state(ctx, key) == stored, name
    assert state(ctx, fresh_key)[-1] == 0
    assert idle_in_transaction(ctx.w.engine) == 0


@pytest.mark.parametrize("name", IDEMPOTENT)
def test_a_still_authorized_replay_returns_the_receipt_after_one_final_statement(
    name: str, ctx: Ctx, pooled: Engine, clients: Clients
) -> None:
    case = build_case(name, ctx, clients)
    key = new_key()
    first = case.call(key)
    assert code(first) == case.ok
    with Recorder(pooled) as recorded:
        replay = case.call(key)
    assert code(replay) == code(first)
    finals = [s for s in recorded.events if FINAL_RE.search(s)]
    assert len(finals) == 1 and recorded.events[-2:] == [finals[0], "COMMIT"]
    # a replay runs no command: no row lock, and no write beyond the key's own no-op insert
    assert not any(ROW_LOCK_RE.search(s) for s in recorded.events), recorded.events
    writes = [s for s in recorded.events if s.startswith(("INSERT", "UPDATE", "DELETE"))]
    assert all("security.idempotent_requests" in s and "ON CONFLICT" in s for s in writes), writes


@pytest.mark.parametrize("name", CASES)
def test_the_requirements_a_request_and_its_replay_judge(
    name: str, ctx: Ctx, pooled: Engine, clients: Clients, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fresh request judges the route's one requirement, registered by the dependency, and nothing else:
    no command registers one (the 21 commands call no scope helper). A replay judges that same requirement."""
    seen: list[list[str]] = []
    original = AuthorizationPlan.finalize

    def spy(self: AuthorizationPlan, connection: Any) -> Any:
        seen.append([r.name for r in self.requirements])
        return original(self, connection)

    monkeypatch.setattr(AuthorizationPlan, "finalize", spy)
    case = build_case(name, ctx, clients)
    seen.clear()  # the seeding requests are not under test
    key = new_key()
    assert code(case.call(key)) == case.ok
    assert seen == [[case.requirement]], (name, seen)
    if case.idempotent:
        seen.clear()
        assert code(case.call(key)) == case.ok
        assert seen == [[case.requirement]], (name, seen)


# --- ordering: the final statement is the last statement before COMMIT, and takes no row lock ------------------------


@pytest.mark.parametrize("name", CASES)
def test_the_final_statement_is_the_last_before_commit_and_takes_no_row_lock(
    name: str, ctx: Ctx, pooled: Engine, clients: Clients
) -> None:
    case = build_case(name, ctx, clients)
    with Recorder(pooled) as recorded:
        response = case.call(new_key() if case.idempotent else None)
    assert code(response) == case.ok, (name, response.text)
    finals = [s for s in recorded.events if FINAL_RE.search(s)]
    assert len(finals) == 1, (name, len(finals))
    assert recorded.events[-2:] == [finals[0], "COMMIT"], (name, recorded.events[-4:])
    assert ROW_LOCK_RE.search(finals[0]) is None
    # it followed the command, the audit row and the receipt: those writes all precede it
    writes = [
        i for i, s in enumerate(recorded.events) if s.startswith(("INSERT", "UPDATE", "DELETE"))
    ]
    assert writes and max(writes) < recorded.events.index(finals[0]), name
    # S4b adds no lock: the statements before the final one take none of the scope helper's locks
    assert not any("FOR SHARE OF mr" in s or "FOR SHARE OF cm" in s for s in recorded.events), name


@pytest.mark.parametrize("name", CASES)
def test_a_handler_that_forgets_to_finalize_is_a_sanitized_500_that_persists_nothing(
    name: str, ctx: Ctx, pooled: Engine, clients: Clients, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = build_case(name, ctx, clients)
    key = new_key() if case.idempotent else None
    before = state(ctx, key)
    monkeypatch.setattr(AuthorizationPlan, "finalize", lambda self, connection: None)
    refused = case.call(key)
    assert code(refused) == 500
    assert error_of(refused) == "internal_error"
    assert "raw_code" not in refused.text and "source_document_id" not in refused.text
    assert state(ctx, key) == before
    assert idle_in_transaction(ctx.w.engine) == 0
    monkeypatch.undo()
    # the pooled connection is clean: the same request now commits its own work and nothing else
    assert code(case.call(key)) == case.ok
    if key:
        assert state(ctx, key)[-1] == 1


# --- Foundry (S4b-4): scope and campaign binding ----------------------------------------------------------------------


def test_a_foundry_credential_without_the_routes_scope_is_refused_and_persists_nothing(
    ctx: Ctx, clients: Clients
) -> None:
    principal = foundry_principal(
        ctx, scopes=frozenset({"combat_sync"})
    )  # not character_state_sync
    before = state(ctx)
    with clients.foundry(principal) as client:
        response = client.post(
            f"{ctx.w.base}/characters/{ctx.character}/hit-points",
            json={"world_time_id": ctx.world_time, "delta": -1},
        )
    assert code(response) == 403, response.text
    assert state(ctx) == before


def test_a_foundry_credential_bound_to_another_campaign_is_refused_as_not_found(
    ctx: Ctx, clients: Clients
) -> None:
    principal = foundry_principal(
        ctx, scopes=frozenset({"character_state_sync"}), campaign_id=uuid.uuid4()
    )
    before = state(ctx)
    with clients.foundry(principal) as client:
        response = client.post(
            f"{ctx.w.base}/characters/{ctx.character}/hit-points",
            json={"world_time_id": ctx.world_time, "delta": -1},
        )
    assert code(response) == 404, response.text
    assert state(ctx) == before


@pytest.mark.parametrize("name", ("event", "encounter_start", "pairing_code", "source_register"))
def test_a_foundry_credential_is_refused_on_a_route_that_does_not_accept_one(
    name: str, ctx: Ctx, clients: Clients
) -> None:
    principal = foundry_principal(ctx, scopes=frozenset({"character_state_sync", "combat_sync"}))
    bodies = {
        "event": (
            "/events",
            {"world_time_id": ctx.world_time, "event_type_code": "other", "name": "x"},
        ),
        "encounter_start": (
            "/encounters",
            {"world_time_id": ctx.world_time, "participant_entity_ids": [str(ctx.character)]},
        ),
        "pairing_code": (
            "/foundry/pairing-codes",
            {"external_system_id": str(ctx.external_system), "requested_scopes": ["combat_sync"]},
        ),
        "source_register": ("/reference-corpus/sources", {}),
    }
    path, body = bodies[name]
    before = state(ctx)
    with clients.foundry(principal) as client:
        response = client.post(f"{ctx.w.base}{path}", json=body)
    assert code(response) == 403, (name, response.text)
    assert state(ctx) == before


def test_the_final_decision_judges_scope_and_binding_against_a_real_snapshot(
    ctx: Ctx, pooled: Engine
) -> None:
    """The plan's own final statement, over the real database, with the facts of a request that no longer
    holds the scope or binding. The route requirement is the one the dependency registers; the plan raises
    the refusal the dependency raised at the start. (A credential's scope and binding cannot change during a
    request: they are read from the authenticated principal; plan 2.1.)"""
    campaign = ctx.w.campaign_id

    def finalize(facts: FoundryRouteFacts | None) -> BaseException | None:
        with pooled.connect() as connection:
            connection.begin()
            plan = AuthorizationPlan.begin(
                connection, actor_user_id=ctx.w.gm_user, campaign_id=campaign, pending=False
            )
            plan.require(
                connection,
                route_capability_requirement(
                    capability_code="canon.edit",
                    allow_archived_campaign=False,
                    world_capability=None,
                    world_id=None,
                    actor_user_id=ctx.w.gm_user,
                    foundry=facts,
                ),
            )
            try:
                plan.finalize(connection)
            except BaseException as exc:  # noqa: BLE001 - the refusal is the result
                return exc
            finally:
                connection.rollback()
        return None

    held = FoundryRouteFacts(
        route_campaign_id=campaign,
        bound_campaign_id=campaign,
        route_scope="character_state_sync",
        granted_scopes=frozenset({"character_state_sync"}),
    )
    assert finalize(held) is None
    assert finalize(None) is None
    wrong_scope = FoundryRouteFacts(
        route_campaign_id=campaign,
        bound_campaign_id=campaign,
        route_scope="character_state_sync",
        granted_scopes=frozenset(),
    )
    assert isinstance(finalize(wrong_scope), ForbiddenError)
    wrong_binding = FoundryRouteFacts(
        route_campaign_id=campaign,
        bound_campaign_id=uuid.uuid4(),
        route_scope="character_state_sync",
        granted_scopes=frozenset({"character_state_sync"}),
    )
    assert isinstance(finalize(wrong_binding), NotFoundError)


# --- V-T1 (bounded): the deferred events trigger and a route that creates an event ------------------------------------


def test_v_t1_no_s4b_route_updates_an_event_status_and_the_event_route_commits_unblocked(
    ctx: Ctx, pooled: Engine, clients: Clients
) -> None:
    """Plan 12.6 V-T1 asked S4b to repeat the proof with one section 7.3 route. The deferred trigger
    `ctr_events_status_has_correction` fires only `AFTER UPDATE OF event_status_id`. The event route inserts
    an event and updates no status, and none of the 21 commands does, so **no S4b route fires the trigger**:
    the proof cannot be repeated on a route that exercises it, and this test does not claim to. What it
    shows is bounded:

    - the statements of the event route contain no `UPDATE narrative.events` (the trigger's event);
    - with a competitor holding the strongest row locks it can on the event-status and correction rows
      the trigger would read, the request commits while the competitor stays open, and its backend is never
      observed blocked.

    It does not exercise the trigger's relation locks, and it is not a general nonblocking guarantee."""
    # an earlier committed correction gives the competitor a correction row to lock (as in S4's V-T1)
    seed = build_case("event", ctx, clients)
    first = seed.call(new_key())
    assert code(first) == 201
    event_id = first.json()["event_id"]
    with clients.browser(ctx.w.gm_user) as client:
        voided = client.post(
            f"{ctx.w.base}/events/{event_id}/void",
            json={"reason": "S4b V-T1"},
            headers={"Idempotency-Key": new_key()},
        )
    assert voided.status_code == 200, voided.text
    case = build_case("event", ctx, clients)
    with Recorder(pooled) as recorded, StatementGate(pooled, FINAL) as gate:
        request = run_in_thread("s4b-request", lambda: case.call(new_key()))
        gate.wait_reached()
        assert gate.pid is not None
        with ctx.w.engine.connect() as competitor:
            transaction = competitor.begin()
            statuses = competitor.execute(
                text("SELECT event_status_id FROM narrative.event_statuses FOR NO KEY UPDATE")
            ).all()
            corrections = competitor.execute(
                text("SELECT event_correction_id FROM narrative.event_corrections FOR UPDATE")
            ).all()
            assert statuses and corrections
            gate.release()
            blockers = _sample_blockers(ctx.w.engine, gate.pid, request)
            response = request.wait("the request commits while the competitor holds its locks")
            assert code(response) == 201, response.text
            transaction.rollback()
    assert blockers, "the request was never observed"
    assert all(b == [] for b in blockers), blockers
    assert not any(s.startswith("UPDATE narrative.events") for s in recorded.events), (
        "an S4b route updated an event row"
    )
