# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-D: the three post-write Foundry routes, over real HTTP on the migrated app and the real guard.

The routes are `DELETE .../foundry/devices/{id}`, `DELETE .../foundry/connections/{id}` and
`POST .../integration/external-systems/{id}/foundry-identities`. They are *post-write*: the command (and
for the link, its audit row) runs first and `plan.finalize` is the last statement before COMMIT. The
request-start policy for explicit Foundry credential revocation (ACCESS_CONTROL, plan 6.21.7) is not
changed: a Foundry credential's own state is judged when the request starts, never at the final statement.

The three differ where it matters (and these tests do not assume they behave alike):

- *device revoke*: one conditional UPDATE of a device; a second revocation is a no-op (204); a device of
  another campaign is the foreign-device refusal found by a classification SELECT.
- *connection revoke*: one conditional UPDATE of a connection plus the bulk UPDATE of its devices, and the
  same no-op and foreign-scope classification.
- *identity link*: an `INSERT ... ON CONFLICT (issuer, subject) WHERE revoked_at IS NULL DO UPDATE` (an
  UPSERT: linking again reassigns, and is not a no-op) and an audit row; it is non-idempotent by design.

Evidence classes (labelled in each docstring): *route* = real HTTP through the guard; *sql* = the recorded
statement stream of the request.
"""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.domain.authorization import AuthorizationPlan
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    FINAL_RE,
    ROW_LOCK_RE,
    Recorder,
    idle_in_transaction,
    pooled,
    pooled_factory,
)
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixtures used by name
    World,
    code,
    error_of,
    w,
)
from tests.factories import (
    make_campaign_membership,
    make_external_system,
    make_foundry_connection,
    make_foundry_device,
    make_user,
)
from tests.r01_s5d_support import (
    Managers,
    make_managers,
    revoke_role,
    run_with_role_lapsing_before_final,
)

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]


@dataclass
class Foundry:
    """A Foundry connection with one device, of a member of the campaign, and the campaign's external
    system (in the campaign's world)."""

    member: uuid.UUID
    connection_id: uuid.UUID
    device_id: uuid.UUID
    second_device_id: uuid.UUID
    external_system_id: uuid.UUID
    other_campaign_device_id: uuid.UUID


@pytest.fixture
def m(w: World) -> Managers:
    return make_managers(w.engine, w.campaign_id, label="S5D Foundry")


@pytest.fixture
def f(w: World) -> Iterator[Foundry]:
    with w.engine.begin() as setup:
        member = make_user(setup, "S5D Foundry Member")
        make_campaign_membership(setup, w.campaign_id, member)
        system = make_external_system(setup, w.world_id)
        connection = make_foundry_connection(
            setup, user_id=member, campaign_id=w.campaign_id, external_system_id=system
        )
        device = make_foundry_device(setup, connection)
        second = make_foundry_device(setup, connection)
        # a device whose connection belongs to a *different* campaign: the scope check must refuse it
        from tests.builders import make_authored_campaign, make_authored_world

        other_world = make_authored_world(setup, owner_user_id=w.owner, name="S5D Other World")
        other_campaign = make_authored_campaign(setup, other_world, name="S5D Other Campaign")
        other_system = make_external_system(setup, other_world.world_id)
        other_member = make_user(setup, "S5D Other Member")
        make_campaign_membership(setup, other_campaign, other_member)
        other_connection = make_foundry_connection(
            setup, user_id=other_member, campaign_id=other_campaign, external_system_id=other_system
        )
        other_device = make_foundry_device(setup, other_connection)
    yield Foundry(member, connection, device, second, system, other_device)
    with w.engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text(
                "DELETE FROM security.external_identities WHERE issuer LIKE 'foundry:%' "
                "AND user_id = :u"
            ),
            {"u": w.owner},
        )


# --- one case per route ---------------------------------------------------------------------------------------------


@dataclass
class Case:
    name: str
    call: Callable[[Factory, uuid.UUID], Any]
    ok: int
    persisted: Callable[[Engine], tuple[Any, ...]]


def _device_state(f: Foundry) -> Callable[[Engine], tuple[Any, ...]]:
    def read(engine: Engine) -> tuple[Any, ...]:
        with engine.connect() as c:
            return tuple(
                c.execute(
                    text(
                        "SELECT foundry_device_id, revoked_at IS NOT NULL, revoked_by_user_id "
                        "FROM security.foundry_devices WHERE foundry_connection_id = :c "
                        "ORDER BY foundry_device_id"
                    ),
                    {"c": f.connection_id},
                ).all()
            )

    return read


def _link_state(f: Foundry, world_id: uuid.UUID) -> Callable[[Engine], tuple[Any, ...]]:
    def read(engine: Engine) -> tuple[Any, ...]:
        with engine.connect() as c:
            identities = c.execute(
                text(
                    "SELECT user_id, issuer, subject FROM security.external_identities "
                    "WHERE issuer = :i ORDER BY subject"
                ),
                {"i": f"foundry:{f.external_system_id}"},
            ).all()
            audit = c.execute(
                text(
                    "SELECT count(*) FROM audit.change_log "
                    "WHERE command_name = 'link_foundry_identity' "
                    "AND table_name = 'external_identities' AND world_id = :w"
                ),
                {"w": world_id},
            ).scalar_one()
        return (tuple(identities), audit)

    return read


def case(name: str, w: World, f: Foundry) -> Case:
    if name == "device":
        return Case(
            name,
            lambda factory, user: _delete(factory, user, f"{w.base}/foundry/devices/{f.device_id}"),
            204,
            _device_state(f),
        )
    if name == "connection":
        return Case(
            name,
            lambda factory, user: _delete(
                factory, user, f"{w.base}/foundry/connections/{f.connection_id}"
            ),
            204,
            _device_state(f),
        )
    assert name == "link"
    body = {"foundry_user_id": "s5d-foundry-user", "user_id": str(w.owner)}
    return Case(
        name,
        lambda factory, user: _post_link(
            factory,
            user,
            f"{w.base}/integration/external-systems/{f.external_system_id}/foundry-identities",
            body,
        ),
        200,
        _link_state(f, w.world_id),
    )


def _delete(factory: Factory, user: uuid.UUID, path: str) -> Any:
    with factory(user) as client:
        return client.delete(path)


def _post_link(factory: Factory, user: uuid.UUID, path: str, body: dict[str, Any]) -> Any:
    with factory(user) as client:
        return client.post(path, json=body)


CASES = ("device", "connection", "link")

#: The statement each route's command starts with: a point after the route's early check and before any lock
#: that a role update would conflict with (these routes take no explicit lock at all).
_FIRST_GATE = {
    "device": r"^UPDATE security\.foundry_devices",
    "connection": r"^UPDATE security\.foundry_connections",
    "link": r"^INSERT INTO security\.external_identities",
}


# --- success, no-op and non-idempotent behavior ---------------------------------------------------------------------


def test_a_device_revocation_revokes_that_device_only_and_a_second_one_is_a_no_op(
    w: World, f: Foundry, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the first request revokes exactly the named device (and records the revoker); the second
    succeeds (204) and changes nothing; a sibling device is untouched."""
    c = case("device", w, f)
    first = c.call(pooled_factory, m.manager_user)
    assert code(first) == 204 and first.content == b""
    state = c.persisted(w.engine)
    revoked = {row[0]: (row[1], row[2]) for row in state}
    assert revoked[f.device_id] == (True, m.manager_user)
    assert revoked[f.second_device_id] == (False, None)
    again = c.call(pooled_factory, m.manager_user)
    assert code(again) == 204
    assert c.persisted(w.engine) == state


def test_a_connection_revocation_cascades_to_its_devices_and_a_second_one_is_a_no_op(
    w: World, f: Foundry, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    c = case("connection", w, f)
    assert code(c.call(pooled_factory, m.manager_user)) == 204
    state = c.persisted(w.engine)
    assert {row[0]: row[1] for row in state} == {f.device_id: True, f.second_device_id: True}
    with w.engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT revoked_at IS NOT NULL, revoked_by_user_id "
                "FROM security.foundry_connections WHERE foundry_connection_id = :c"
            ),
            {"c": f.connection_id},
        ).one() == (True, m.manager_user)
    assert code(c.call(pooled_factory, m.manager_user)) == 204
    assert c.persisted(w.engine) == state


def test_a_foreign_campaign_device_or_connection_is_still_refused_and_unchanged(
    w: World, f: Foundry, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the classification SELECT runs after the conditional UPDATE and before the final statement;
    the refusal and its status are unchanged by the plan."""
    other_state = lambda: _state_of_device(w.engine, f.other_campaign_device_id)  # noqa: E731
    before = other_state()
    response = _delete(
        pooled_factory, m.manager_user, f"{w.base}/foundry/devices/{f.other_campaign_device_id}"
    )
    assert code(response) in (403, 404), response.text
    assert other_state() == before == (False,)
    assert idle_in_transaction(w.engine) == 0


def _state_of_device(engine: Engine, device: uuid.UUID) -> tuple[Any, ...]:
    with engine.connect() as c:
        return tuple(
            c.execute(
                text(
                    "SELECT revoked_at IS NOT NULL FROM security.foundry_devices "
                    "WHERE foundry_device_id = :d"
                ),
                {"d": device},
            ).one()
        )


def test_an_identity_link_is_an_upsert_and_is_not_idempotent_by_design(
    w: World, f: Foundry, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the first link inserts; a repeat for the same (system, foundry user) reassigns the row's
    user (here the same user again) and writes a second audit row. No receipt, no key: unchanged."""
    c = case("link", w, f)
    first = c.call(pooled_factory, m.manager_user)
    assert code(first) == 200, first.text
    identities, audit = c.persisted(w.engine)
    assert len(identities) == 1 and audit == 1
    second = c.call(pooled_factory, m.manager_user)
    assert code(second) == 200
    assert first.json() == second.json()  # the same row, updated in place
    identities2, audit2 = c.persisted(w.engine)
    assert identities2 == identities and audit2 == 2


# --- authority loss and expiry --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", CASES)
def test_a_role_that_lapses_before_the_final_statement_refuses_the_route_and_rolls_everything_back(
    name: str, w: World, f: Foundry, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the GM's role is valid for every early check and has lapsed (a DATABASE condition, polled)
    by the final authority statement. The command's UPDATE or UPSERT and the link's audit row are rolled
    back, the pooled connection returns clean, and the next request commits only its own work."""
    c = case(name, w, f)
    before = c.persisted(w.engine)
    response = run_with_role_lapsing_before_final(
        w.engine,
        pooled,
        m.manager_role,
        lambda: c.call(pooled_factory, m.manager_user),
        first_gate=_FIRST_GATE[name],
    )
    assert code(response) in (403, 404), (name, response.text)
    assert c.persisted(w.engine) == before, name
    assert idle_in_transaction(w.engine) == 0
    # the next request on the same one-connection pool commits only its own work
    with pooled_factory(w.owner) as client:
        assert code(client.get(f"{w.base}/foundry/devices")) in (200, 403, 404)
    assert c.persisted(w.engine) == before, name


@pytest.mark.parametrize("name", CASES)
def test_a_role_revoked_before_the_request_is_refused_early_and_writes_nothing(
    name: str, w: World, f: Foundry, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    c = case(name, w, f)
    before = c.persisted(w.engine)
    revoke_role(w.engine, m.manager_role)
    response = c.call(pooled_factory, m.manager_user)
    assert code(response) in (403, 404), (name, response.text)
    assert c.persisted(w.engine) == before
    assert idle_in_transaction(w.engine) == 0


# --- finalization ordering, and the missing finalize ----------------------------------------------------------------


@pytest.mark.parametrize("name", CASES)
def test_the_final_statement_is_the_last_before_commit_and_takes_no_row_lock(
    name: str, w: World, f: Foundry, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql*: every write of the request (the command, the bulk cascade, the audit row) precedes the one
    final authority statement, and nothing but COMMIT follows it."""
    c = case(name, w, f)
    with Recorder(pooled) as recorded:
        response = c.call(pooled_factory, m.manager_user)
    assert code(response) == c.ok, (name, response.text)
    finals = [s for s in recorded.events if FINAL_RE.search(s)]
    assert len(finals) == 1, (name, len(finals))
    assert recorded.events[-2:] == [finals[0], "COMMIT"], (name, recorded.events[-4:])
    assert ROW_LOCK_RE.search(finals[0]) is None
    writes = [i for i, s in enumerate(recorded.events) if s.startswith(("INSERT", "UPDATE"))]
    assert writes and max(writes) < recorded.events.index(finals[0]), name


@pytest.mark.parametrize("name", CASES)
def test_a_handler_that_forgets_to_finalize_is_a_sanitized_500_that_persists_nothing(
    name: str,
    w: World,
    f: Foundry,
    m: Managers,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = case(name, w, f)
    before = c.persisted(w.engine)
    monkeypatch.setattr(AuthorizationPlan, "finalize", lambda self, connection: None)
    refused = c.call(pooled_factory, m.manager_user)
    assert code(refused) == 500
    assert error_of(refused) == "internal_error"
    assert c.persisted(w.engine) == before
    assert idle_in_transaction(w.engine) == 0
    monkeypatch.undo()


# --- confidentiality ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", CASES)
def test_a_refused_request_discloses_none_of_the_protected_ids(
    name: str, w: World, f: Foundry, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: an unauthorized caller (a campaign member without `access.manage`) learns nothing: the
    refusal body names neither the device, the connection, the external system nor the Foundry user."""
    outsider = f.member  # an active member with no management role
    c = case(name, w, f)
    before = c.persisted(w.engine)
    response = c.call(pooled_factory, outsider)
    assert code(response) in (403, 404), (name, response.text)
    body = response.text
    for secret in (
        str(f.device_id),
        str(f.connection_id),
        str(f.external_system_id),
        "s5d-foundry-user",
    ):
        assert secret not in body, (name, secret)
    assert c.persisted(w.engine) == before
    assert idle_in_transaction(w.engine) == 0


def test_the_request_start_credential_policy_is_unchanged_for_a_revoked_connections_own_device(
    w: World, f: Foundry, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: revoking the connection first, then asking to revoke its device, is still a 204 no-op for
    an authorized manager: the plan added a final authority check for the *manager*, not a new rule about
    the credential's own state."""
    assert code(case("connection", w, f).call(pooled_factory, m.manager_user)) == 204
    again = case("device", w, f).call(pooled_factory, m.manager_user)
    assert code(again) == 204, again.text
    with w.engine.connect() as connection:
        receipts = connection.execute(
            text("SELECT count(*) FROM security.idempotent_requests WHERE campaign_id = :c"),
            {"c": w.campaign_id},
        ).scalar_one()
    assert receipts == 0  # the routes are unkeyed: no reservation, no receipt
