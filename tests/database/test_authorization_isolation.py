# ruff: noqa: F811, SIM117 - nested `with` keeps the expected failure separate; the imported `g` is a pytest fixture used by parameter name
"""R01 S1: requests run at READ COMMITTED however the database or role defaults are set (plan 3.1).

- `get_engine` builds the engine with `isolation_level="READ COMMITTED"`; psycopg then begins every
  transaction with `BEGIN ISOLATION LEVEL READ COMMITTED` (its `_get_tx_start_command`, the text it
  sends; libpq tracing is unavailable on Windows), so the database, role and server defaults no longer
  apply. Proven by the begin text and by the effect: a request still reads `read committed` under a
  database-level and a role-level `repeatable read` default.
- The decision statement itself returns `transaction_isolation`; unless it is `read committed` the
  reader raises `IsolationLevelError`, a 5xx with nothing persisted. This also covers an engine a
  direct caller passes to `authorized_transaction` (and one built without the level).
- A structural test requires every `create_engine` in `src` to pass the level.
"""

import ast
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, text

import dnd_ai.api.deps as deps
from dnd_ai.api.errors import install_error_handlers
from dnd_ai.commands._content import canon_edit_requirement
from dnd_ai.commands.authorized_transaction import authorized_transaction
from dnd_ai.domain.access import IsolationLevelError, read_authority_snapshot
from dnd_ai.domain.authorization import AuthorizationPlan
from tests.database.test_campaign_owner_gate import Gate, drop_gate, g  # noqa: F401

pytestmark = pytest.mark.database

SRC = Path(__file__).resolve().parents[2] / "src"
SCHEMA = "r01_s1_isolation"


@contextmanager
def _database_default(engine: Engine, scope: str, level: str) -> Iterator[None]:
    """Sets (then resets) `default_transaction_isolation` for the test database, or for the
    connecting role inside it."""
    database = engine.url.database
    role = engine.url.username
    if scope == "database":
        set_sql = f"ALTER DATABASE \"{database}\" SET default_transaction_isolation = '{level}'"
        reset_sql = f'ALTER DATABASE "{database}" RESET default_transaction_isolation'
    else:
        set_sql = (
            f'ALTER ROLE "{role}" IN DATABASE "{database}" '
            f"SET default_transaction_isolation = '{level}'"
        )
        reset_sql = (
            f'ALTER ROLE "{role}" IN DATABASE "{database}" RESET default_transaction_isolation'
        )
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(set_sql))
    try:
        yield
    finally:
        with admin.connect() as connection:
            connection.execute(text(reset_sql))


@pytest.fixture
def scratch(postgres_engine: Engine) -> Iterator[Engine]:
    admin = postgres_engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        connection.execute(text(f"CREATE TABLE {SCHEMA}.marker (n int)"))
    try:
        yield postgres_engine
    finally:
        with admin.connect() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))


def _marker_rows(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.marker")).scalar_one())  # noqa: S608


def _production_engine(url: str, monkeypatch: pytest.MonkeyPatch) -> Engine:
    """The engine `dnd_ai.api.deps.get_engine` builds, from `settings.database_url`."""
    monkeypatch.setattr(deps, "settings", SimpleNamespace(database_url=url))
    monkeypatch.setattr(deps, "_engine", None)
    return deps.get_engine()


def _isolation_in_a_request(engine: Engine) -> str:
    app = FastAPI(dependencies=[Depends(deps.commit_request_transaction, scope="function")])

    @app.get("/iso")
    def iso(connection: Annotated[Connection, Depends(deps.get_connection)]) -> dict[str, str]:
        return {"level": str(connection.execute(text("SHOW transaction_isolation")).scalar_one())}

    app.dependency_overrides[deps.get_engine] = lambda: engine
    with TestClient(app) as client:
        return str(client.get("/iso").json()["level"])


def test_get_engine_enforces_read_committed_and_installs_the_guard(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from psycopg.pq import TransactionStatus  # noqa: F401  (psycopg is the production driver)
    from sqlalchemy import event

    from dnd_ai.domain import authorization

    engine = _production_engine(
        postgres_engine.url.render_as_string(hide_password=False), monkeypatch
    )
    try:
        assert event.contains(engine, "commit", authorization._on_commit)
        with engine.connect() as connection:
            driver = connection.connection.driver_connection
            assert driver is not None
            # The text psycopg sends to begin every transaction on this connection.
            begin = driver._get_tx_start_command().decode()  # type: ignore[attr-defined]
            assert begin == "BEGIN ISOLATION LEVEL READ COMMITTED"
    finally:
        engine.dispose()


@pytest.mark.parametrize("scope", ["database", "role"])
@pytest.mark.parametrize("level", ["repeatable read", "serializable"])
def test_a_request_runs_at_read_committed_despite_the_database_or_role_default(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch, scope: str, level: str
) -> None:
    url = postgres_engine.url.render_as_string(hide_password=False)
    with _database_default(postgres_engine, scope, level):
        # The default really changed what an engine without the level runs at ...
        plain = create_engine(url)
        try:
            with plain.connect() as connection:
                assert connection.execute(text("SHOW transaction_isolation")).scalar_one() == level
        finally:
            plain.dispose()
        # ... and the production engine no longer inherits it.
        engine = _production_engine(url, monkeypatch)
        try:
            assert _isolation_in_a_request(engine) == "read committed"
        finally:
            engine.dispose()
    engine = _production_engine(url, monkeypatch)
    try:
        assert _isolation_in_a_request(engine) == "read committed"
    finally:
        engine.dispose()


@pytest.mark.parametrize("level", ["repeatable read", "serializable"])
def test_an_engine_without_the_level_makes_the_reader_refuse(
    postgres_engine: Engine, g: Gate, level: str
) -> None:
    url = postgres_engine.url.render_as_string(hide_password=False)
    with _database_default(postgres_engine, "database", level):
        engine = create_engine(url)  # built without isolation_level
        try:
            with engine.connect() as connection:
                with pytest.raises(IsolationLevelError):
                    read_authority_snapshot(
                        connection, user_id=g.o1_user_id, campaign_id=g.campaign_id
                    )
        finally:
            engine.dispose()


def test_an_unexpected_isolation_fails_a_protected_request_safely_with_nothing_persisted(
    scratch: Engine, postgres_engine: Engine, g: Gate
) -> None:
    """The route writes, then runs the final check. Under an inherited `repeatable read` the check
    refuses with the fixed 5xx and the write is not committed."""
    url = postgres_engine.url.render_as_string(hide_password=False)

    def make_app(engine: Engine) -> FastAPI:
        app = FastAPI(dependencies=[Depends(deps.commit_request_transaction, scope="function")])
        install_error_handlers(app)

        @app.post("/write")
        def write(
            connection: Annotated[Connection, Depends(deps.get_connection)],
        ) -> dict[str, bool]:
            plan = AuthorizationPlan.begin(
                connection, actor_user_id=g.o1_user_id, campaign_id=g.campaign_id
            )
            plan.require(connection, canon_edit_requirement(g.o1_user_id, g.campaign_id))
            connection.execute(text(f"INSERT INTO {SCHEMA}.marker VALUES (1)"))
            plan.finalize(connection)
            return {"ok": True}

        app.dependency_overrides[deps.get_engine] = lambda: engine
        return app

    with _database_default(postgres_engine, "database", "repeatable read"):
        inherited = create_engine(url)
        try:
            with TestClient(make_app(inherited), raise_server_exceptions=False) as client:
                refused = client.post("/write")
            assert refused.status_code == 500
            assert refused.json()["error"]["code"] == "internal_error"
            assert "read committed" not in refused.text.lower()
            assert _marker_rows(scratch) == 0
        finally:
            inherited.dispose()
        # The same request through the production-shaped engine is allowed, at read committed.
        enforced = create_engine(url, isolation_level="READ COMMITTED")
        try:
            with TestClient(make_app(enforced), raise_server_exceptions=False) as client:
                assert client.post("/write").status_code == 200
            assert _marker_rows(scratch) == 1
        finally:
            enforced.dispose()


def test_a_direct_callers_engine_without_the_level_is_refused_by_the_decision_itself(
    scratch: Engine, postgres_engine: Engine, g: Gate
) -> None:
    url = postgres_engine.url.render_as_string(hide_password=False)
    with _database_default(postgres_engine, "database", "repeatable read"):
        inherited = create_engine(url)
        try:
            with pytest.raises(IsolationLevelError):
                with authorized_transaction(inherited, g.o1_user_id, g.campaign_id) as (
                    connection,
                    plan,
                ):
                    plan.require(connection, canon_edit_requirement(g.o1_user_id, g.campaign_id))
                    connection.execute(text(f"INSERT INTO {SCHEMA}.marker VALUES (1)"))
        finally:
            inherited.dispose()
    assert _marker_rows(scratch) == 0


def test_every_create_engine_in_src_passes_read_committed() -> None:
    """Plan 3.1 enforcement 2: no engine in `src` can inherit a database default. Today there is one,
    in `get_engine`."""
    offenders: list[str] = []
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if name != "create_engine":
                continue
            found.append(f"{path.relative_to(SRC)}:{node.lineno}")
            level = next((kw.value for kw in node.keywords if kw.arg == "isolation_level"), None)
            if not (isinstance(level, ast.Constant) and level.value == "READ COMMITTED"):
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert found, "no create_engine call found: the test lost its subject"
    assert offenders == []


def test_src_never_sets_the_isolation_level_per_transaction() -> None:
    """The level is the engine's; no code path changes it per transaction (the enforcement is the
    engine option plus the in-statement check)."""
    hits = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if "default_transaction_isolation" in path.read_text(encoding="utf-8")
        or "SET TRANSACTION" in path.read_text(encoding="utf-8").upper()
    ]
    assert hits == []
