# ruff: noqa: F811, SIM117 - nested `with` keeps the expected failure separate; the imported `g` is a pytest fixture used by parameter name
"""R01 S1: `AuthorizationPlan` and the fail-closed commit guard (plan sections 6.2, 6.5, 12.2).

Every test runs against PostgreSQL with real committed data (the owner-gate campaign), a scratch
`marker` table the synthetic commands write, and a one-connection `QueuePool`, so a connection the
guard leaves in a transaction would be reused by the next request.

Covered here: open, violated, cross-transaction and cross-connection plans; the registry cleared by a
rollback; post-write enforcement (a `SELECT`, a write, `SET`, an advisory call, `executemany`,
`RETURNING`, a second `finalize`); the fixed mode (pre-write enforcement lives in test_authorization_pre_write.py); a
pending plan; the refusal's error class and sanitized 5xx; T0's refusal/reuse verification with the
REAL guard, through a request and through `authorized_transaction`.
"""

import uuid
from collections.abc import Iterator
from typing import Annotated, Any, cast

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, text

import dnd_ai.api.deps as deps
from dnd_ai.api.errors import install_error_handlers
from dnd_ai.commands._content import canon_edit_requirement
from dnd_ai.commands.authorized_transaction import authorized_transaction
from dnd_ai.domain.authoring import CampaignNotAuthorizedError
from dnd_ai.domain.authorization import (
    AuthorizationPlan,
    AuthorizationPlanBindingError,
    AuthorizationPlanNotFinalizedError,
    AuthorizationPlanStateError,
    AuthorizationPlanViolationError,
    PlanMode,
)
from tests.database.test_campaign_owner_gate import Gate, drop_gate, g  # noqa: F401

pytestmark = pytest.mark.database

SCHEMA = "r01_s1_guard"


@pytest.fixture
def scratch(postgres_engine: Engine) -> Iterator[Engine]:
    admin = postgres_engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        connection.execute(text(f"CREATE TABLE {SCHEMA}.marker (n int)"))
        connection.execute(text(f"CREATE TABLE {SCHEMA}.other (n int)"))
    try:
        yield postgres_engine
    finally:
        with admin.connect() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))


@pytest.fixture
def one(scratch: Engine) -> Iterator[Engine]:
    engine = create_engine(scratch.url, pool_size=1, max_overflow=0)
    try:
        yield engine
    finally:
        engine.dispose()


def _rows(engine: Engine, table: str = "marker") -> list[int]:
    with engine.connect() as connection:
        return [
            int(r[0])
            for r in connection.execute(text(f"SELECT n FROM {SCHEMA}.{table} ORDER BY n")).all()  # noqa: S608
        ]


def _idle_in_transaction(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND state LIKE 'idle in transaction%'"
                )
            ).scalar_one()
        )


def _write(connection: Connection, n: int, table: str = "marker") -> None:
    connection.execute(text(f"INSERT INTO {SCHEMA}.{table} VALUES (:n)"), {"n": n})  # noqa: S608


def _begin(
    engine: Engine, g: Gate, *, user: uuid.UUID | None = None, **options: Any
) -> tuple[Connection, AuthorizationPlan]:
    connection = engine.connect()
    connection.begin()
    plan = AuthorizationPlan.begin(
        connection,
        actor_user_id=user or g.o1_user_id,
        campaign_id=g.campaign_id,
        **options,
    )
    return connection, plan


def _require_canon_edit(connection: Connection, plan: AuthorizationPlan, g: Gate) -> None:
    plan.require(connection, canon_edit_requirement(g.o1_user_id, g.campaign_id))


# --- the error class ----------------------------------------------------------------------------


def test_the_guard_error_is_a_direct_runtime_error_subclass_and_never_a_4xx_class() -> None:
    from dnd_ai.api.errors import ApiError
    from dnd_ai.domain.errors import SafeMessageError

    assert AuthorizationPlanViolationError.__mro__[1:] == (
        RuntimeError,
        Exception,
        BaseException,
        object,
    )
    assert AuthorizationPlanNotFinalizedError.__mro__[1:] == (
        RuntimeError,
        Exception,
        BaseException,
        object,
    )
    for cls in (
        AuthorizationPlanNotFinalizedError,
        AuthorizationPlanViolationError,
        AuthorizationPlanBindingError,
        AuthorizationPlanStateError,
    ):
        assert issubclass(cls, RuntimeError)
        assert not issubclass(cls, (ValueError, SafeMessageError, ApiError))


# --- common: open, violated, cross-transaction, cross-connection -------------------------------


def test_an_open_plan_refuses_the_commit_and_nothing_persists(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    connection, plan = _begin(one, g)
    try:
        _require_canon_edit(connection, plan, g)
        _write(connection, 1)
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
        # The guard rolled the DBAPI connection back before raising (defence in depth).
        assert connection.connection.driver_connection.info.transaction_status.name == "IDLE"
    finally:
        deps._discard(connection)
    assert _rows(scratch) == []
    assert _idle_in_transaction(scratch) == 0


def test_a_failed_requirement_raises_its_own_error_and_leaves_the_plan_open(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    connection, plan = _begin(one, g, user=g.player_user_id)
    try:
        plan.require(connection, canon_edit_requirement(g.player_user_id, g.campaign_id))
        _write(connection, 1)
        with pytest.raises(CampaignNotAuthorizedError):
            plan.finalize(connection)
        assert not plan.finalised
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)
    assert _rows(scratch) == []


def test_a_finalized_plan_commits(scratch: Engine, one: Engine, g: Gate) -> None:
    connection, plan = _begin(one, g)
    _require_canon_edit(connection, plan, g)
    _write(connection, 1)
    snapshot = plan.finalize(connection)
    assert snapshot is not None and plan.finalised and snapshot.access is not None
    deps.finish_connection_transaction(connection, commit=True)
    assert _rows(scratch) == [1]


def test_a_plan_bound_to_another_transaction_raises(one: Engine, g: Gate) -> None:
    connection, plan = _begin(one, g)
    try:
        _require_canon_edit(connection, plan, g)
        connection.rollback()
        connection.begin()
        with pytest.raises(AuthorizationPlanBindingError):
            plan.finalize(connection)
        with pytest.raises(AuthorizationPlanBindingError):
            _require_canon_edit(connection, plan, g)
    finally:
        deps._discard(connection)


def test_a_plan_bound_to_another_connection_raises(scratch: Engine, one: Engine, g: Gate) -> None:
    connection, plan = _begin(one, g)
    other = scratch.connect()
    other.begin()
    try:
        with pytest.raises(AuthorizationPlanBindingError):
            plan.finalize(other)
        with pytest.raises(AuthorizationPlanBindingError):
            plan.require(other, canon_edit_requirement(g.o1_user_id, g.campaign_id))
    finally:
        other.close()
        deps._discard(connection)


def test_a_plan_needs_a_transaction(one: Engine, g: Gate) -> None:
    connection = one.connect()
    try:
        with pytest.raises(AuthorizationPlanBindingError):
            AuthorizationPlan.begin(
                connection, actor_user_id=g.o1_user_id, campaign_id=g.campaign_id
            )
    finally:
        connection.close()


def test_a_rollback_clears_the_registry_so_a_later_transaction_is_unaffected(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    connection, plan = _begin(one, g)
    try:
        _require_canon_edit(connection, plan, g)
        connection.rollback()
        connection.begin()
        _write(connection, 5)
        connection.commit()  # the old, never-finalized plan does not refuse this transaction
    finally:
        deps._discard(connection)
    assert _rows(scratch) == [5]


def test_registering_after_finalize_is_out_of_sequence_and_violates_the_plan(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    connection, plan = _begin(one, g)
    try:
        _require_canon_edit(connection, plan, g)
        plan.finalize(connection)
        with pytest.raises(AuthorizationPlanStateError):
            _require_canon_edit(connection, plan, g)
        assert plan.violated
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)


def test_a_pending_plan_is_admitted_unfinalized_and_an_open_one_is_not(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    connection, plan = _begin(one, g, pending=True)
    try:
        _require_canon_edit(connection, plan, g)
        _write(connection, 1)
        connection.commit()
    finally:
        deps._discard(connection)
    assert _rows(scratch) == [1]
    assert plan.pending and not plan.finalised  # admitted, and protected nothing


# --- the mode is fixed ---------------------------------------------------------------------------


def test_the_mode_is_fixed_when_the_plan_is_created(one: Engine, g: Gate) -> None:
    connection, plan = _begin(one, g)
    try:
        assert plan.mode is PlanMode.POST_WRITE
        with pytest.raises(AttributeError):
            plan.mode = PlanMode.PRE_WRITE  # type: ignore[misc]
        with pytest.raises(AttributeError):
            plan.nonexistent = 1  # type: ignore[attr-defined]  # __slots__: no new attributes
        with pytest.raises(ValueError, match="no pre-write steps"):
            AuthorizationPlan.begin(
                connection,
                actor_user_id=g.o1_user_id,
                campaign_id=g.campaign_id,
                mode=PlanMode.POST_WRITE,
                pre_write=cast(Any, object()),
            )
        with pytest.raises(ValueError, match="must declare"):
            AuthorizationPlan.begin(
                connection,
                actor_user_id=g.o1_user_id,
                campaign_id=g.campaign_id,
                mode=PlanMode.PRE_WRITE,
            )
    finally:
        deps._discard(connection)


# --- post-write: nothing may follow the final statement -----------------------------------------

_AFTER_FINALIZE = {
    "select": lambda c: c.execute(text("SELECT 1")),
    "write": lambda c: _write(c, 9),
    "set": lambda c: c.execute(text("SET LOCAL lock_timeout = '5s'")),
    "advisory": lambda c: c.execute(text("SELECT pg_advisory_xact_lock(42)")),
    "executemany": lambda c: c.execute(
        text(f"INSERT INTO {SCHEMA}.marker VALUES (:n)"), [{"n": 1}, {"n": 2}]
    ),
    "returning": lambda c: c.execute(text(f"INSERT INTO {SCHEMA}.marker VALUES (3) RETURNING n")),
    "for_update": lambda c: c.execute(text(f"SELECT n FROM {SCHEMA}.marker FOR UPDATE")),
    "exec_driver_sql": lambda c: c.exec_driver_sql("SELECT 1"),
    "begin_nested": lambda c: c.begin_nested(),
}


@pytest.mark.parametrize("kind", sorted(_AFTER_FINALIZE))
def test_any_statement_after_the_final_one_violates_a_post_write_plan(
    scratch: Engine, one: Engine, g: Gate, kind: str
) -> None:
    connection, plan = _begin(one, g)
    try:
        _require_canon_edit(connection, plan, g)
        _write(connection, 1)
        plan.finalize(connection)
        assert not plan.violated
        _AFTER_FINALIZE[kind](connection)
        assert plan.violated
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)
    assert _rows(scratch) == []


def test_a_second_finalize_violates_the_plan_and_refuses_the_commit(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    connection, plan = _begin(one, g)
    try:
        _require_canon_edit(connection, plan, g)
        plan.finalize(connection)
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            plan.finalize(connection)
        assert plan.violated
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)


def test_statements_before_the_final_one_are_free_including_executemany(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    connection, plan = _begin(one, g)
    _require_canon_edit(connection, plan, g)
    connection.execute(text(f"INSERT INTO {SCHEMA}.marker VALUES (:n)"), [{"n": 1}, {"n": 2}])
    connection.execute(text("SELECT 1"))
    plan.finalize(connection)
    deps.finish_connection_transaction(connection, commit=True)
    assert _rows(scratch) == [1, 2]


def test_finalize_is_exactly_one_statement(scratch: Engine, one: Engine, g: Gate) -> None:
    from sqlalchemy import event

    connection, plan = _begin(one, g)
    try:
        seen: list[str] = []
        event.listen(
            connection, "before_cursor_execute", lambda _c, _k, stmt, *_a: seen.append(stmt)
        )
        _require_canon_edit(connection, plan, g)
        plan.finalize(connection)
        assert len(seen) == 1
    finally:
        deps._discard(connection)


# --- the real guard in a request (T0.1, T0.2 and T0.6 with the real guard) -----------------------


def _request_app(engine: Engine, g: Gate, *, finalize: bool, extra: bool = False) -> FastAPI:
    from fastapi import Request

    app = FastAPI(dependencies=[Depends(deps.commit_request_transaction, scope="function")])
    install_error_handlers(app)

    @app.post("/write/{n}")
    def write(
        n: int, connection: Annotated[Connection, Depends(deps.get_connection)]
    ) -> dict[str, Any]:
        plan = AuthorizationPlan.begin(
            connection, actor_user_id=g.o1_user_id, campaign_id=g.campaign_id
        )
        _require_canon_edit(connection, plan, g)
        _write(connection, n)
        if finalize:
            plan.finalize(connection)
        if extra:
            connection.execute(text("SELECT 1"))  # a statement after the final one
        pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one() if extra else None
        return {"pid": pid}

    @app.post("/early/{n}")
    def early(
        n: int, request: Request, connection: Annotated[Connection, Depends(deps.get_connection)]
    ) -> dict[str, bool]:
        plan = AuthorizationPlan.begin(
            connection, actor_user_id=g.o1_user_id, campaign_id=g.campaign_id
        )
        _require_canon_edit(connection, plan, g)
        _write(connection, n)
        deps.end_request_transaction(request)  # the guard refuses here, before any engine effect
        return {"ok": True}

    app.dependency_overrides[deps.get_engine] = lambda: engine
    return app


def test_an_unfinalized_plan_in_a_request_is_a_sanitized_500_and_the_next_request_is_clean(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    pids: list[int] = []

    def backend() -> int:
        with one.connect() as connection:
            return int(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())

    with TestClient(_request_app(one, g, finalize=False), raise_server_exceptions=False) as client:
        pids.append(backend())
        refused = client.post("/write/1")
        assert refused.status_code == 500
        assert refused.json()["error"]["code"] == "internal_error"
        assert "plan" not in refused.text.lower() and "finalize" not in refused.text.lower()
        assert _rows(scratch) == []
        assert _idle_in_transaction(scratch) == 0
        pids.append(backend())
    assert pids[0] == pids[1], "the pooled backend was not reused"

    with TestClient(_request_app(one, g, finalize=True), raise_server_exceptions=False) as client:
        allowed = client.post("/write/2")
        assert allowed.status_code == 200
    assert _rows(scratch) == [2]


def test_a_statement_after_the_final_one_in_a_request_is_a_500_and_persists_nothing(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    with TestClient(
        _request_app(one, g, finalize=True, extra=True), raise_server_exceptions=False
    ) as client:
        refused = client.post("/write/1")
        assert refused.status_code == 500
        assert refused.json()["error"]["code"] == "internal_error"
        assert _rows(scratch) == []
        assert _idle_in_transaction(scratch) == 0
    with TestClient(_request_app(one, g, finalize=True), raise_server_exceptions=False) as client:
        assert client.post("/write/2").status_code == 200
    assert _rows(scratch) == [2]


def test_a_refusal_through_end_request_transaction_is_cleaned_up(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    with TestClient(_request_app(one, g, finalize=False), raise_server_exceptions=False) as client:
        refused = client.post("/early/1")
        assert refused.status_code == 500
        assert _rows(scratch) == []
        assert _idle_in_transaction(scratch) == 0
    with TestClient(_request_app(one, g, finalize=True), raise_server_exceptions=False) as client:
        assert client.post("/write/2").status_code == 200
    assert _rows(scratch) == [2]


# --- the real guard for direct callers -----------------------------------------------------------


def test_authorized_transaction_finalizes_and_commits(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    with authorized_transaction(one, g.o1_user_id, g.campaign_id) as (connection, plan):
        _require_canon_edit(connection, plan, g)
        _write(connection, 1)
        assert not plan.finalised
    assert plan.finalised
    assert _rows(scratch) == [1]


def test_authorized_transaction_with_no_requirement_commits_nothing_unjudged(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    with authorized_transaction(one, g.o1_user_id, g.campaign_id) as (connection, plan):
        _write(connection, 1)
    assert plan.finalised and plan.snapshot is None
    assert _rows(scratch) == [1]


def test_authorized_transaction_refuses_and_abandons_cleanly_on_a_failed_requirement(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    with pytest.raises(CampaignNotAuthorizedError):  # the early counterpart's own class
        with authorized_transaction(one, g.player_user_id, g.campaign_id) as (connection, plan):
            plan.require(connection, canon_edit_requirement(g.player_user_id, g.campaign_id))
            _write(connection, 1)
    assert _rows(scratch) == []
    assert _idle_in_transaction(scratch) == 0
    with authorized_transaction(one, g.o1_user_id, g.campaign_id) as (connection, plan):
        _require_canon_edit(connection, plan, g)
        _write(connection, 2)
    assert _rows(scratch) == [2]


def test_authorized_transaction_with_a_violating_body_refuses_and_the_pool_stays_clean(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    pids: list[int] = []
    with pytest.raises(AuthorizationPlanNotFinalizedError):
        with authorized_transaction(one, g.o1_user_id, g.campaign_id) as (connection, plan):
            _require_canon_edit(connection, plan, g)
            _write(connection, 1)
            plan.finalize(connection)
            pids.append(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
    assert _rows(scratch) == []
    assert _idle_in_transaction(scratch) == 0
    with authorized_transaction(one, g.o1_user_id, g.campaign_id) as (connection, plan):
        _require_canon_edit(connection, plan, g)
        _write(connection, 2)
        pids.append(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
    assert pids[0] == pids[1], "the pooled backend was not reused"
    assert _rows(scratch) == [2]


def test_authorized_transaction_rolls_back_when_the_body_raises(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    with pytest.raises(KeyError):
        with authorized_transaction(one, g.o1_user_id, g.campaign_id) as (connection, plan):
            _require_canon_edit(connection, plan, g)
            _write(connection, 1)
            raise KeyError("body")
    assert _rows(scratch) == []
    assert _idle_in_transaction(scratch) == 0


def test_the_guard_is_installed_once_per_engine(one: Engine, g: Gate) -> None:
    from sqlalchemy import event

    from dnd_ai.domain import authorization

    for _ in range(3):
        connection, _plan = _begin(one, g)
        deps._discard(connection)
    assert event.contains(one, "commit", authorization._on_commit)
    assert len(one.dispatch.commit) == 1


# --- route plans (rule 1b): a pending route is admitted, a finalized-route plan must finalize -----


def test_a_pending_route_gets_a_pending_plan_the_guard_admits(
    scratch: Engine, one: Engine, g: Gate
) -> None:
    from dnd_ai.api.r01_route_plans import begin_route_plan

    connection = one.connect()
    connection.begin()
    try:
        plan = begin_route_plan(
            connection,
            method="POST",
            route_path="/campaigns/{campaign_id}/memberships",  # a route still pending (access-management)
            actor_user_id=g.o1_user_id,
            campaign_id=g.campaign_id,
        )
        assert plan.pending and not plan.finalised
        _require_canon_edit(connection, plan, g)
        _write(connection, 1)
        connection.commit()  # admitted: the route is not protected, and is not presented as such
    finally:
        deps._discard(connection)
    assert _rows(scratch) == [1]


def test_a_finalized_route_gets_an_ordinary_plan_the_guard_refuses_while_open(
    scratch: Engine, one: Engine, g: Gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dnd_ai.api import r01_route_plans

    route = ("POST", "/campaigns/{campaign_id}/events")
    monkeypatch.setattr(
        r01_route_plans,
        "R01_PENDING_ROUTES",
        {k: v for k, v in r01_route_plans.R01_PENDING_ROUTES.items() if k != route},
    )
    monkeypatch.setattr(r01_route_plans, "R01_FINALIZED_ROUTES", frozenset({route}))
    connection = one.connect()
    connection.begin()
    try:
        plan = r01_route_plans.begin_route_plan(
            connection,
            method="POST",
            route_path=route[1],
            actor_user_id=g.o1_user_id,
            campaign_id=g.campaign_id,
        )
        assert not plan.pending
        _write(connection, 1)
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)
    assert _rows(scratch) == []


def test_an_unclassified_route_cannot_open_a_plan(one: Engine, g: Gate) -> None:
    from dnd_ai.api.r01_route_plans import UnclassifiedRouteError, begin_route_plan

    connection = one.connect()
    connection.begin()
    try:
        with pytest.raises(UnclassifiedRouteError):
            begin_route_plan(
                connection,
                method="POST",
                route_path="/campaigns/{campaign_id}/a-new-write-route",
                actor_user_id=g.o1_user_id,
                campaign_id=g.campaign_id,
            )
    finally:
        deps._discard(connection)
