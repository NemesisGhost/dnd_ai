# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E2 F-4: the S5-E2 change/revoke role routes against the legacy reveal-delegation grant, by application path.

The design review (2026-11-14, finding F-4) predicted a cycle: the S5-E2 revoke and change routes lock the actor's
unrevoked role rows *and* the target role row in one ordered `FOR UPDATE` statement, and the legacy grant locks the
grantor's owner row `FOR SHARE` and then the grantee's built-in `gm` rows `FOR UPDATE`. With the grantee's `gm`
row ordered **before** the grantor's owner row, the two requests hold what the other wants:

- the grant (owner C -> grantee X) holds C's owner row `r_C` `FOR SHARE` and wants X's `gm` row `g_X` `FOR UPDATE`;
- the revoke (actor X revoking `r_C`) holds `g_X` (X's own row, locked first, lower id) and wants `r_C` `FOR UPDATE`.

The scene fixes the ids so the order is deterministic (`g_X` < `r_C`), the grant is parked at its `gm` lock
statement (it holds `r_C`), the revoke is started and observed queued behind it (`pg_blocking_pids`), then the grant
is released. The test reports what happened (SQLSTATE of each failure from the driver error, the deadlock counter,
each response) and asserts the outcome in `EXPECTED`, so the same file can be run against any source tree.
"""

import json
import os
import re
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.domain.authorization import install_authorization_guard
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixture by name
    World,
    code,
    w,
)
from tests.factories import (
    make_campaign_membership,
    make_user,
    oidc_principal,
    system_role_id,
)
from tests.http_race_support import (
    StatementGate,
    deadlock_count,
    run_in_thread,
    wait_for_deadlock_count,
)
from tests.lock_race_support import LockRace
from tests.r01_s5d_support import make_managers

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]
G_X = uuid.UUID("00000000-0000-4000-8000-0000000000a1")  # X's gm row: orders before ...
R_C = uuid.UUID("ffffffff-ffff-4fff-bfff-fffffffffff1")  # ... C's owner row
GM_LOCK = (
    r"r\.code = 'gm' AND mr\.revoked_at IS NULL ORDER BY mr\.membership_role_id FOR UPDATE OF mr"
)
OBSERVED: dict[str, Any] = {}


class Failures:
    """SQLSTATEs of the statements that failed, from the driver (`handle_error`), registered before any plan."""

    def __init__(self, engine: Engine) -> None:
        self.codes: list[tuple[str | None, str]] = []
        event.listen(engine, "handle_error", self._hook)

    def _hook(self, context: Any) -> None:
        original = context.original_exception
        self.codes.append(
            (
                getattr(original, "sqlstate", None),
                " ".join(str(context.statement or "").split())[:140],
            )
        )


@pytest.fixture
def pooled2(postgres_engine: Engine) -> Any:
    engine = create_engine(
        postgres_engine.url, pool_size=2, max_overflow=0, isolation_level="READ COMMITTED"
    )
    install_authorization_guard(engine)
    OBSERVED["failures"] = Failures(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def pooled2_factory(pooled2: Engine) -> Factory:
    def make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: pooled2
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return make


def _scene(w: World) -> dict[str, Any]:
    m = make_managers(w.engine, w.campaign_id, label="F4")
    with w.engine.begin() as c:
        gm = system_role_id(c, "gm")
        owner = system_role_id(c, "campaign_owner")
        c_user = make_user(c, "F4 Owner C")
        c_membership = make_campaign_membership(c, w.campaign_id, c_user)
        for row, membership, role in (
            (G_X, m.manager_membership, gm),
            (R_C, c_membership, owner),
        ):
            c.execute(
                text(
                    "INSERT INTO security.membership_roles (membership_role_id, campaign_membership_id, role_id) "
                    "VALUES (:r, :m, :role)"
                ),
                {"r": row, "m": membership, "role": role},
            )
    return {"m": m, "c_user": c_user, "c_membership": c_membership}


def _statement_of(engine: Engine, holder_pid: int) -> str:
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    r"SELECT regexp_replace(query, '\s+', ' ', 'g') FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND :p = ANY(pg_blocking_pids(pid))"
                ),
                {"p": holder_pid},
            )
            .scalars()
            .all()
        )
    return str(rows[0]) if rows else ""


@pytest.mark.parametrize("route", ("revoke", "change"))
def test_the_grant_against_the_role_routes_reports_its_lock_edges_and_sqlstate(
    route: str, w: World, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race* (deterministic, application paths on both sides). Reports the outcome of the predicted cycle."""
    scene = _scene(w)
    m = scene["m"]
    deadlocks = deadlock_count(w.engine)
    base = w.base
    observer = None
    with w.engine.connect() as c:
        observer = c.execute(
            text(
                "SELECT role_id FROM security.roles WHERE code = 'observer' AND campaign_id IS NULL"
            )
        ).scalar_one()

    def grant() -> Any:
        with pooled2_factory(scene["c_user"]) as client:
            return client.post(
                f"{base}/reveal-delegations",
                json={
                    "grantee_campaign_membership_id": str(m.manager_membership),
                    "reason": "f4",
                },
            )

    def role_route() -> Any:
        with pooled2_factory(m.manager_user) as client:
            if route == "revoke":
                return client.post(f"{base}/memberships/roles/{R_C}/revoke", json={})
            return client.post(
                f"{base}/memberships/roles/{R_C}/change", json={"new_role_id": str(observer)}
            )

    with StatementGate(pooled2, GM_LOCK) as gate:
        granting = run_in_thread("grant", grant)
        gate.wait_reached()
        assert gate.pid is not None
        revoking = run_in_thread(route, role_route)
        with LockRace(w.engine) as race:
            race.wait_blocked_by(gate, expected=1)
        waiting = _statement_of(w.engine, gate.pid)
        gate.release()
        grant_response = granting.wait("the grant finishes")
        route_response = revoking.wait("the role route finishes")
    after = wait_for_deadlock_count(w.engine, deadlocks)
    failures = OBSERVED["failures"].codes
    OBSERVED[route] = {
        "blocked_statement_of_the_role_route": waiting[:200],
        "grant_status": code(grant_response),
        "role_route_status": code(route_response),
        "deadlocks_counted": after - deadlocks,
        "failed_statements": [
            {"sqlstate": sqlstate, "statement": statement} for sqlstate, statement in failures
        ],
    }
    print("F4-OBSERVED " + json.dumps({route: OBSERVED[route]}, default=str))  # noqa: T201
    expected = os.environ.get("F4_EXPECT")
    if expected == "deadlock":
        assert after - deadlocks == 1
        assert any(sqlstate == "40P01" for sqlstate, _ in failures)
    elif expected == "none":
        assert after - deadlocks == 0 and not failures
        assert code(grant_response) == 200
    assert re.search(r"FOR UPDATE|FOR KEY SHARE|FOR SHARE", waiting or "FOR UPDATE")
