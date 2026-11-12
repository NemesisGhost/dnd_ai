"""R01 S0 probes: what the fresh-authorization plan assumes about PostgreSQL 18 and the request path.

docs/R01_FRESH_AUTHORIZATION_PLAN_2026-11-12.md section 12.1 lists assumptions ([A]) that must be
verified before S1. Each test here states, in its docstring, **what it establishes and what it does not**.
Nothing here changes production behavior: the tests read the catalog, the source and the live app, and
create and drop only their own scratch objects in the ephemeral test database.

Evidence summary and the design consequence of each result: docs/R01_S0_VERIFICATION_2026-11-12.md.
"""

import ast
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy import Engine, create_engine, text

pytestmark = pytest.mark.database

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "dnd_ai"
SCHEMA = "r01_s0_probe"
WAIT = 15.0


# --- scratch objects -------------------------------------------------------------------------------


@pytest.fixture
def scratch(postgres_engine: Engine) -> Iterator[Engine]:
    """A scratch schema with the tables the probes lock and read, dropped afterwards."""
    admin = postgres_engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        for table in ("input_t", "marker", "x", "y"):
            connection.execute(text(f"CREATE TABLE {SCHEMA}.{table} (n int)"))
        connection.execute(text(f"INSERT INTO {SCHEMA}.input_t VALUES (1)"))
    try:
        yield postgres_engine
    finally:
        with admin.connect() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))


def _wait_blocked(engine: Engine, pid: int) -> list[int]:
    """Waits until `pid` is blocked, and returns the pids blocking it. Deterministic: the block lasts
    as long as the blocker holds its lock, so there is no timing assumption beyond the poll limit."""
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            blockers = connection.execute(
                text("SELECT pg_blocking_pids(:p)"), {"p": pid}
            ).scalar_one()
        if blockers:
            return list(blockers)
        time.sleep(0.02)
    raise AssertionError(f"pid {pid} was never blocked")


_FINAL = f"""
WITH t AS MATERIALIZED (SELECT clock_timestamp() AS t_auth)
SELECT t.t_auth,
       (SELECT count(*) FROM {SCHEMA}.marker) AS markers,
       (SELECT count(*) FROM {SCHEMA}.input_t) AS inputs
FROM t
"""


def _run_ordering_probe(engine: Engine, *, variant: str) -> dict[str, Any]:
    """Session B holds ACCESS EXCLUSIVE on the input table. Session A runs the final-statement shape and
    blocks on the relation lock. While A waits, session C commits a marker row (a table A can read
    without waiting). B then releases. If A's snapshot was taken *after* the lock wait, A sees the
    marker; if before, it does not. `t_auth` is compared with the instant B released."""
    results: dict[str, Any] = {}
    url = engine.url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg", "postgresql"
    )
    a_raw: psycopg.Connection[Any] | None = None
    a = None
    if variant == "simple_protocol":
        a_raw = psycopg.connect(url, cursor_factory=psycopg.ClientCursor)
        a_pid = a_raw.info.backend_pid
    else:
        a = engine.connect()
        a_pid = a.execute(text("SELECT pg_backend_pid()")).scalar_one()
        if variant == "prepared":
            # psycopg prepares a statement on its prepare_threshold-th use (default 5); warm up past
            # it *before* the lock is taken, so the blocked execution is a server-side prepared one.
            for _ in range(8):
                a.execute(text(_FINAL.replace("FROM t", "FROM t WHERE :p = 1")), {"p": 1})
            prepared = a.execute(text("SELECT count(*) FROM pg_prepared_statements")).scalar_one()
            results["prepared_statements_on_session"] = int(prepared)
        a.commit()  # the warm-up's AccessShareLock must not outlive it: B's lock would wait on it
    b = engine.connect()
    b.execute(text(f"LOCK TABLE {SCHEMA}.input_t IN ACCESS EXCLUSIVE MODE"))
    c = engine.connect()

    def run() -> None:
        try:
            if variant == "bind_parameters" or variant == "prepared":
                row = a.execute(  # type: ignore[union-attr]
                    text(_FINAL.replace("FROM t", "FROM t WHERE :p = 1")), {"p": 1}
                ).one()
            elif variant == "no_bind_parameters":
                row = a.execute(text(_FINAL)).one()  # type: ignore[union-attr]
            else:
                assert a_raw is not None
                row = a_raw.execute(_FINAL).fetchone()  # type: ignore[assignment]
            results["row"] = row
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            results["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        results["blocked_by_b"] = b.execute(text("SELECT pg_backend_pid()")).scalar_one() in (
            _wait_blocked(engine, a_pid)
        )
        c.execute(text(f"INSERT INTO {SCHEMA}.marker VALUES (1)"))
        c.commit()
        results["marker_committed_at"] = c.execute(text("SELECT clock_timestamp()")).scalar_one()
        c.commit()
        # Read just before the release: the release instant is later than this, and A's `t_auth` can
        # only be later than it if A evaluated the clock after the lock wait ended. (A clock read
        # *after* the release returns is not usable: A can finish first.)
        results["release_started_at"] = c.execute(text("SELECT clock_timestamp()")).scalar_one()
        c.commit()
        b.rollback()
        c.commit()
        thread.join(WAIT)
        assert not thread.is_alive(), "the statement never finished after the lock was released"
    finally:
        b.close()
        c.close()
        if a is not None:
            a.rollback()
            a.close()
        if a_raw is not None:
            a_raw.close()
    assert "error" not in results, results["error"]
    t_auth, markers, inputs = results["row"]
    results.update(t_auth=t_auth, markers_seen=int(markers), inputs=int(inputs))
    results["t_auth_after_release_started"] = t_auth > results["release_started_at"]
    return results


@pytest.mark.parametrize(
    "variant", ["bind_parameters", "prepared", "no_bind_parameters", "simple_protocol"]
)
def test_the_snapshot_and_t_auth_both_follow_a_relation_lock_wait(
    scratch: Engine, variant: str
) -> None:
    """ESTABLISHES (plan section 3 and section 5, [A]): for a statement shaped like the final check, a
    wait for an `AccessShareLock` behind an `ACCESS EXCLUSIVE` holder ends **before** the statement's
    snapshot is taken and before `clock_timestamp()` is evaluated. Proof: the statement was observed
    blocked (`pg_blocking_pids`), another session then committed a marker row, and the statement,
    once released, saw that row (so its snapshot is later than the wait) and returned a `t_auth` later
    than the instant the release began.

    Covered shapes: bind parameters over the extended protocol (the production shape), the same as a
    server-side *prepared* statement (psycopg prepares on the 6th use), no bind parameters (psycopg
    sends the simple protocol for these), and an explicit `psycopg.ClientCursor` simple query.

    DOES NOT ESTABLISH: other lock waits (a row, advisory or tuple lock inside the executor is a
    different position, see the next test); the ordering on other PostgreSQL versions or with a
    different `default_transaction_isolation`; waits behind anything other than a held
    `ACCESS EXCLUSIVE` lock on one table; that the wait is *short*."""
    results = _run_ordering_probe(scratch, variant=variant)
    assert results["blocked_by_b"] is True
    assert results["markers_seen"] == 1, "the snapshot was taken before the relation-lock wait"
    assert results["t_auth_after_release_started"] is True, "t_auth was read before the wait ended"
    if variant == "prepared":
        assert results["prepared_statements_on_session"] >= 1, "the warm-up did not prepare it"


def test_a_snapshot_precedes_an_executor_time_clock_read_and_one_statement_is_coherent(
    scratch: Engine,
) -> None:
    """ESTABLISHES (plan section 3): (1) within one READ COMMITTED statement every subquery sees the
    **same** snapshot: a transaction committed *while the statement ran* is invisible to a subquery
    evaluated after the commit, so a decision read in one statement is coherent. (2) `S <= T_auth`:
    `clock_timestamp()` evaluated in the executor can be later than the snapshot by as long as the
    executor takes (here a deliberate in-statement wait), never earlier.

    Proof: the statement reads `x`, then blocks inside the executor on an advisory lock, then reads
    `y` and the clock. While it waits, one transaction commits a row into **both** `x` and `y`. The
    statement returns `(0, 0)` and a clock later than the commit. The same two reads issued as two
    statements return `(0, 1)`: the incoherent view the plan's multi-statement reader allowed.

    DOES NOT ESTABLISH: the same for the real `resolve_access_context` (S1 builds the single-statement
    reader); behavior under REPEATABLE READ (not used); that a wait inside the *final* statement can
    occur at all (it is a plain SELECT with no locks, so only I/O waits are possible there)."""
    engine = scratch
    single_sql = f"""
        WITH t AS MATERIALIZED (
            SELECT pg_advisory_xact_lock(990001) IS NOT NULL AS locked, clock_timestamp() AS t_auth
        )
        SELECT (SELECT count(*) FROM {SCHEMA}.x),
               (SELECT count(*) FROM {SCHEMA}.y),
               (SELECT t_auth FROM t)
    """
    holder = engine.connect()
    holder.execute(text("SELECT pg_advisory_xact_lock(990001)"))
    reader = engine.connect()
    reader_pid = reader.execute(text("SELECT pg_backend_pid()")).scalar_one()
    out: dict[str, Any] = {}

    def run() -> None:
        try:
            out["row"] = reader.execute(text(single_sql)).one()
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            out["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    writer = engine.connect()
    try:
        _wait_blocked(engine, reader_pid)
        writer.execute(text(f"INSERT INTO {SCHEMA}.x VALUES (1)"))
        writer.execute(text(f"INSERT INTO {SCHEMA}.y VALUES (1)"))
        writer.commit()
        out["committed_at"] = writer.execute(text("SELECT clock_timestamp()")).scalar_one()
        writer.commit()
        holder.rollback()
        thread.join(WAIT)
        assert not thread.is_alive()
    finally:
        holder.close()
        writer.close()
        reader.rollback()
        reader.close()
    assert "error" not in out, out.get("error")
    x_count, y_count, t_auth = out["row"]
    assert (x_count, y_count) == (0, 0), "one statement saw a transaction commit mid-statement"
    assert t_auth > out["committed_at"], "the executor-time clock was earlier than the commit"

    with engine.connect() as separate:
        first = separate.execute(text(f"SELECT count(*) FROM {SCHEMA}.x")).scalar_one()
        # (the table already holds the committed row; to show the multi-statement tear, delete and redo)
        separate.execute(text(f"DELETE FROM {SCHEMA}.x"))
        separate.execute(text(f"DELETE FROM {SCHEMA}.y"))
        separate.commit()
    assert first == 1
    # The tear: statement 1 reads x (empty), another transaction commits both rows, statement 2 reads y.
    with engine.connect() as reader2, engine.connect() as writer2:
        x_before = reader2.execute(text(f"SELECT count(*) FROM {SCHEMA}.x")).scalar_one()
        writer2.execute(text(f"INSERT INTO {SCHEMA}.x VALUES (2)"))
        writer2.execute(text(f"INSERT INTO {SCHEMA}.y VALUES (2)"))
        writer2.commit()
        y_after = reader2.execute(text(f"SELECT count(*) FROM {SCHEMA}.y")).scalar_one()
        reader2.rollback()
    assert (x_before, y_after) == (0, 1), "two statements should be able to tear (control case)"


# --- catalog: expiry columns, triggers, deferral -------------------------------------------------

_APP_SCHEMAS = (
    "ai",
    "audit",
    "campaign",
    "character",
    "core",
    "integration",
    "interaction",
    "knowledge",
    "narrative",
    "security",
    "world",
)


_LOCK_PATTERNS = {
    "advisory": re.compile(r"pg_(try_)?advisory", re.IGNORECASE),
    "for_update": re.compile(r"\bFOR\s+(NO\s+KEY\s+)?UPDATE\b", re.IGNORECASE),
    "for_share": re.compile(r"\bFOR\s+(KEY\s+)?SHARE\b", re.IGNORECASE),
    "lock_table": re.compile(r"\bLOCK\s+TABLE\b", re.IGNORECASE),
}


def _function_bodies(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT n.nspname || '.' || p.proname AS name, p.prosrc
                FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = ANY(:schemas)
            """),
            {"schemas": list(_APP_SCHEMAS)},
        ).all()
    bodies: dict[str, str] = {}
    for name, body in rows:
        bodies[name] = bodies.get(name, "") + "\n" + body
    return bodies


def _locks_reached(name: str, bodies: dict[str, str], seen: set[str] | None = None) -> set[str]:
    """Lock constructs in `name`'s body and in every schema-qualified function it calls (transitively).
    A textual scan: it cannot see a lock taken through dynamic SQL or an unqualified call."""
    seen = seen if seen is not None else set()
    if name in seen or name not in bodies:
        return set()
    seen.add(name)
    body = bodies[name]
    found = {label for label, pattern in _LOCK_PATTERNS.items() if pattern.search(body)}
    for called in re.findall(r"\b([a-z_]+\.[a-z_0-9]+)\s*\(", body):
        found |= _locks_reached(called, bodies, seen)
    return found


def _trigger_catalog(engine: Engine) -> list[dict[str, Any]]:
    bodies = _function_bodies(engine)
    sql = """
        SELECT n.nspname AS schema_name, c.relname AS table_name, t.tgname AS trigger_name,
               pn.nspname || '.' || p.proname AS function_name,
               t.tgconstraint <> 0 AS is_constraint_trigger,
               t.tgdeferrable AS deferrable, t.tginitdeferred AS initially_deferred
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_proc p ON p.oid = t.tgfoid
        JOIN pg_namespace pn ON pn.oid = p.pronamespace
        WHERE NOT t.tgisinternal AND n.nspname = ANY(:schemas)
        ORDER BY 1, 2, 3
    """
    with engine.connect() as connection:
        rows = connection.execute(text(sql), {"schemas": list(_APP_SCHEMAS)}).mappings().all()
    return [{**row, "locks": sorted(_locks_reached(row["function_name"], bodies))} for row in rows]


#: Every trigger whose function (or a schema-qualified function it calls) contains a lock construct.
EXPECTED_LOCK_TAKING_TRIGGERS: frozenset[tuple[str, str, tuple[str, ...]]] = frozenset(
    {
        ("campaign.campaigns", "tr_campaigns_enforce_ruleset_allowed", ("for_share",)),
        ("campaign.campaigns", "tr_campaigns_retain_access_manager", ("for_update",)),
        ("character.characters", "tr_characters_enforce_subtype", ("advisory",)),
        ("character.npcs", "tr_npcs_enforce_subtype", ("advisory",)),
        ("character.player_characters", "tr_player_characters_enforce_subtype", ("advisory",)),
        ("core.entities", "tr_entities_enforce_dungeon_type_change", ("advisory",)),
        ("core.entities", "tr_entities_enforce_type_change", ("advisory",)),
        ("core.worlds", "tr_worlds_enforce_default_ruleset_allowed", ("for_share",)),
        (
            "interaction.check_results",
            "tr_check_results_advance_interaction_status",
            ("for_update",),
        ),
        ("knowledge.knowledge_items", "tr_knowledge_items_enforce_subtype", ("advisory",)),
        ("narrative.events", "tr_events_enforce_subtype", ("advisory",)),
        ("narrative.quests", "tr_quests_enforce_subtype", ("advisory",)),
        (
            "security.campaign_memberships",
            "tr_campaign_memberships_retain_access_manager",
            ("for_update",),
        ),
        ("security.capabilities", "tr_capabilities_retain_access_manager", ("for_update",)),
        ("security.membership_roles", "tr_membership_roles_retain_access_manager", ("for_update",)),
        (
            "security.membership_statuses",
            "tr_membership_statuses_retain_access_manager",
            ("for_update",),
        ),
        (
            "security.role_capabilities",
            "tr_role_capabilities_retain_access_manager",
            ("for_update",),
        ),
        ("security.roles", "tr_roles_retain_access_manager", ("for_update",)),
        ("security.world_memberships", "tr_world_memberships_retain_owner", ("for_update",)),
        ("world.buildings", "tr_buildings_enforce_subtype", ("advisory",)),
        ("world.businesses", "tr_businesses_enforce_subtype", ("advisory",)),
        ("world.dungeon_areas", "tr_dungeon_areas_enforce_parent_dungeon", ("advisory",)),
        ("world.dungeon_areas", "tr_dungeon_areas_enforce_subtype", ("advisory",)),
        ("world.dungeons", "tr_dungeons_enforce_subtype", ("advisory",)),
        ("world.governments", "tr_governments_enforce_subtype", ("advisory",)),
        ("world.item_instances", "tr_item_instances_enforce_subtype", ("advisory",)),
        ("world.locations", "tr_locations_enforce_dungeon_area_parent_on_update", ("advisory",)),
        ("world.locations", "tr_locations_enforce_no_cycle", ("advisory",)),
        ("world.locations", "tr_locations_enforce_subtype", ("advisory",)),
        ("world.military_units", "tr_military_units_enforce_subtype", ("advisory",)),
        ("world.organizations", "tr_organizations_enforce_no_cycle", ("advisory",)),
        ("world.organizations", "tr_organizations_enforce_subtype", ("advisory",)),
        ("world.political_factions", "tr_political_factions_enforce_subtype", ("advisory",)),
        ("world.religions", "tr_religions_enforce_subtype", ("advisory",)),
        (
            "world.religious_organizations",
            "tr_religious_organizations_enforce_subtype",
            ("advisory",),
        ),
        ("world.settlements", "tr_settlements_enforce_subtype", ("advisory",)),
    }
)

#: Every constraint trigger that is deferrable and initially deferred: it runs at COMMIT.
EXPECTED_DEFERRED_CONSTRAINT_TRIGGERS = frozenset(
    {
        ("campaign.campaigns", "tr_campaigns_retain_access_manager"),
        ("campaign.character_player_profiles", "tr_character_player_profiles_has_version"),
        ("narrative.events", "ctr_events_status_has_correction"),
        ("security.campaign_memberships", "tr_campaign_memberships_retain_access_manager"),
        ("security.capabilities", "tr_capabilities_retain_access_manager"),
        ("security.membership_roles", "tr_membership_roles_retain_access_manager"),
        ("security.membership_statuses", "tr_membership_statuses_retain_access_manager"),
        ("security.role_capabilities", "tr_role_capabilities_retain_access_manager"),
        ("security.roles", "tr_roles_retain_access_manager"),
        ("security.world_memberships", "tr_world_memberships_retain_owner"),
    }
)

#: The authorization-input tables that carry `expires_at` (plan section 2).
EXPECTED_AUTHORIZATION_EXPIRY_TABLES = frozenset(
    {
        "security.membership_character_relationships",
        "security.membership_roles",
        "security.resource_grants",
    }
)


def test_the_tables_the_plan_says_have_no_expiry_have_none(postgres_engine: Engine) -> None:
    """ESTABLISHES (plan section 2 and section 12.1): `world_memberships`, `user_system_roles`,
    `world_use_grants` and `campaign_memberships` have no `expires_at` column, and the three
    authorization-input tables the plan names do. Also that the other `expires_at` tables are
    credential or invitation tables (not authorization inputs read by `resolve_access_context`).

    DOES NOT ESTABLISH: that an expiry is never enforced some other way (for example a `CHECK` against
    a time, or an `ended_at` set by a job): no such mechanism exists in `src`, which the plan's
    inventory treats separately."""
    with postgres_engine.connect() as connection:
        tables = {
            f"{schema}.{table}"
            for schema, table in connection.execute(
                text("""
                    SELECT table_schema, table_name FROM information_schema.columns
                    WHERE table_schema = ANY(:s) AND column_name = 'expires_at'
                """),
                {"s": list(_APP_SCHEMAS)},
            ).all()
        }
    for name in (
        "security.world_memberships",
        "security.user_system_roles",
        "security.world_use_grants",
        "security.campaign_memberships",
    ):
        assert name not in tables, f"{name} gained an expires_at column"
    assert tables >= EXPECTED_AUTHORIZATION_EXPIRY_TABLES
    credential_tables = {
        "security.campaign_invitations",
        "security.foundry_access_tokens",
        "security.foundry_devices",
        "security.foundry_pairing_codes",
        "security.invitation_onboarding_sessions",
        "security.password_reset_tokens",
        "security.timeline_bootstrap_grants",
        "security.user_activation_tokens",
    }
    assert tables == EXPECTED_AUTHORIZATION_EXPIRY_TABLES | credential_tables


def test_there_is_no_deferrable_foreign_key_today_and_the_deferred_triggers_are_pinned(
    postgres_engine: Engine,
) -> None:
    """ESTABLISHES (plan section 5, item 2; section 9.3, item 5): no foreign key, unique or exclusion
    constraint is deferrable now (so the reservation's campaign FK is checked immediately, and S5's
    deferral is a real change), and the commit-time constraint triggers are exactly the ten pinned
    above. Each of these ten runs at COMMIT.

    DOES NOT ESTABLISH which of them the R01 families can fire: see the manifest-based test below."""
    with postgres_engine.connect() as connection:
        deferrable = connection.execute(
            text(
                "SELECT conrelid::regclass::text, conname FROM pg_constraint "
                "WHERE condeferrable AND contype IN ('f', 'u', 'p', 'x')"
            )
        ).all()
    assert deferrable == []
    deferred = {
        (f"{t['schema_name']}.{t['table_name']}", t["trigger_name"])
        for t in _trigger_catalog(postgres_engine)
        if t["is_constraint_trigger"] and t["deferrable"] and t["initially_deferred"]
    }
    assert deferred == EXPECTED_DEFERRED_CONSTRAINT_TRIGGERS
    assert not {
        (f"{t['schema_name']}.{t['table_name']}", t["trigger_name"])
        for t in _trigger_catalog(postgres_engine)
        if t["deferrable"] and not t["initially_deferred"]
    }, "a deferrable but initially-immediate trigger exists: SET CONSTRAINTS could defer it"


def test_lock_taking_triggers_are_exactly_the_pinned_set(postgres_engine: Engine) -> None:
    """ESTABLISHES (plan section 7.2, class 5): the triggers whose function, or a schema-qualified
    function it calls, contains an advisory-lock call, `FOR UPDATE` / `FOR SHARE` or `LOCK TABLE`. They
    are the subtype advisory guards, the cycle and dungeon-area guards, the type-change guards, the
    ruleset triggers (`FOR SHARE` on the world and campaign), `interaction.check_results`, and the eight
    retention triggers (seven access-manager triggers and the world-owner trigger on
    `world_memberships`; `FOR UPDATE`, deferred to COMMIT).

    DOES NOT ESTABLISH: locks taken through dynamic SQL or an unqualified function call (the scan is
    textual); the lock *target* or mode ordering (only that a construct is present); that the plan's
    class-5 list is exhaustive for foreign-key checks, which take `FOR KEY SHARE` without a trigger
    body we can read."""
    found = {
        (f"{t['schema_name']}.{t['table_name']}", t["trigger_name"], tuple(t["locks"]))
        for t in _trigger_catalog(postgres_engine)
        if t["locks"]
    }
    assert found == EXPECTED_LOCK_TAKING_TRIGGERS


def test_the_post_write_families_write_no_deferred_trigger_table_but_events(
    postgres_engine: Engine,
) -> None:
    """ESTABLISHES (plan section 5, item 2): by a static trace of the SQL literals each command
    reaches, the authoring, operation, reveal and route-capability-only families write exactly one
    table that has a deferred constraint trigger: `narrative.events`. The access-management family
    writes the retention-trigger tables, which is why section 9 treats it separately.

    DOES NOT ESTABLISH: writes made through SQL assembled at run time or through a function the trace
    could not resolve (see `unresolved` in the manifest); writes by triggers; that the events trigger
    takes no row lock (it runs plain SELECTs, per migration 124, which this test does not execute)."""
    import json

    manifest = json.loads((REPO / "tests" / "r01_route_manifest.json").read_text(encoding="utf-8"))
    deferred_tables = {table for table, _ in EXPECTED_DEFERRED_CONSTRAINT_TRIGGERS}
    written: dict[str, set[str]] = {}
    for record in manifest:
        for tables in record["command_writes"].values():
            for table in set(tables) & deferred_tables:
                written.setdefault(record["family"], set()).add(table)
    post_write = {"authoring_scope", "operation_scope", "reveal_authority", "route_capability_only"}
    assert {family: tables for family, tables in written.items() if family in post_write} == {
        "operation_scope": {"narrative.events"},
        "route_capability_only": {"narrative.events"},
    }
    assert {"campaign.campaigns", "security.membership_roles"} <= written["access_management"]


# --- transaction isolation --------------------------------------------------------------------------


def _read_isolation_through_the_request_path(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Builds the engine with `dnd_ai.api.deps.get_engine` itself (production's constructor, from
    `settings.database_url`) and reads `transaction_isolation` on the connection the real
    `get_connection` dependency hands a request."""
    from types import SimpleNamespace
    from typing import Annotated

    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import Connection

    import dnd_ai.api.deps as deps

    monkeypatch.setattr(deps, "settings", SimpleNamespace(database_url=database_url))
    monkeypatch.setattr(deps, "_engine", None)
    engine = deps.get_engine()
    app = FastAPI(dependencies=[Depends(deps.commit_request_transaction, scope="function")])

    @app.get("/iso")
    def iso(connection: Annotated[Connection, Depends(deps.get_connection)]) -> dict[str, str]:
        return {
            "show": str(connection.execute(text("SHOW transaction_isolation")).scalar_one()),
            "setting": str(
                connection.execute(
                    text("SELECT current_setting('transaction_isolation')")
                ).scalar_one()
            ),
        }

    app.dependency_overrides[deps.get_engine] = lambda: engine
    try:
        with TestClient(app) as client:
            body = client.get("/iso").json()
    finally:
        engine.dispose()
    assert body["show"] == body["setting"]
    return body["show"]


def test_a_request_runs_at_read_committed_because_the_server_default_is_inherited(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CHARACTERISATION of S0 finding F-4, **updated by slice S1 (plan section 3.1)**.

    ORIGINAL S0 FINDING (historical evidence, observed 2026-11-12 at 395d595, before S1): through the
    real request path a request's transaction was `read committed` on PostgreSQL 18 only because the
    level was **inherited from the server, database or role default**. `src` never set an isolation
    level (no `create_engine` passed `isolation_level`, no `SET TRANSACTION` text), and when this test
    changed the database default to `repeatable read` the same code ran at `repeatable read`.

    AFTER S1: `get_engine` passes `isolation_level="READ COMMITTED"`, so the level no longer follows
    the database default. This test now shows that a request still runs at `read committed` under a
    database-level `repeatable read` default, that exactly one `create_engine` in `src` sets the level,
    and that no `SET TRANSACTION` / `default_transaction_isolation` text exists. The role-level default,
    `serializable`, the in-statement refusal and the structural rule are in
    `tests/database/test_authorization_isolation.py`. The test name keeps its S0 spelling because the
    plan refers to it.

    DOES NOT ESTABLISH: the level behind a transaction-mode pooler or proxy that rewrites
    transaction-control statements (the in-statement check refuses there; it is not exercised)."""
    url = postgres_engine.url.render_as_string(hide_password=False)
    assert _read_isolation_through_the_request_path(url, monkeypatch) == "read committed"

    leveled: list[str] = []
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if re.search(
            r"default_transaction_isolation|SET\s+TRANSACTION|set_session\(", source, re.I
        ):
            offenders.append(f"{path.relative_to(REPO)}: isolation text")
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", "")) == "create_engine"
                and any(kw.arg == "isolation_level" for kw in node.keywords)
            ):
                leveled.append(f"{path.relative_to(REPO)}:{node.lineno}")
    assert offenders == []
    assert len(leveled) == 1 and "deps.py" in leveled[0], leveled

    database = postgres_engine.url.database
    admin = postgres_engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(
            text(
                f"ALTER DATABASE \"{database}\" SET default_transaction_isolation = 'repeatable read'"
            )
        )
    try:
        assert _read_isolation_through_the_request_path(url, monkeypatch) == "read committed"
    finally:
        with admin.connect() as connection:
            connection.execute(
                text(f'ALTER DATABASE "{database}" RESET default_transaction_isolation')
            )
    assert _read_isolation_through_the_request_path(url, monkeypatch) == "read committed"


# --- row-lock facts the plan's section 4 relies on --------------------------------------------------


def test_row_lock_conflict_facts_of_plan_section_4(scratch: Engine) -> None:
    """ESTABLISHES (plan section 4, "Lock facts"), on PostgreSQL 18 with a primary-keyed table: a row
    held `FOR SHARE` blocks a plain non-key `UPDATE`; a row held `FOR KEY SHARE` does **not** block a
    plain non-key `UPDATE`, but does block `FOR UPDATE`, a key update and a `DELETE`.

    CONSEQUENCE: holding the campaign row `FOR KEY SHARE` protects its lifecycle only against writers
    that take `FOR UPDATE` first (plan section 4.1, row "Campaign lifecycle"). A writer that updated
    `lifecycle_status_id` with a bare `UPDATE` would not be blocked: the lifecycle-writer test below
    shows that none does.

    DOES NOT ESTABLISH: the matrix for multixact or subtransaction cases; the exact lock a trigger
    takes on a parent row for a foreign key (those are `FOR KEY SHARE` and are covered by the same
    matrix)."""
    admin = scratch.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"CREATE TABLE {SCHEMA}.locked (k int PRIMARY KEY, v int)"))
        connection.execute(text(f"INSERT INTO {SCHEMA}.locked VALUES (1, 0)"))

    def blocked(statement: str) -> bool:
        with scratch.connect() as probe:
            probe.execute(text("SET LOCAL lock_timeout = '300ms'"))
            try:
                probe.execute(text(statement))
            except Exception as exc:  # noqa: BLE001 - classified by SQLSTATE below
                assert getattr(exc.orig, "sqlstate", None) == "55P03", exc  # type: ignore[attr-defined]
                return True
            finally:
                probe.rollback()
            return False

    for mode, expectations in {
        "FOR SHARE": {
            "non_key_update": True,
            "for_update": True,
            "key_update": True,
            "delete": True,
        },
        "FOR KEY SHARE": {
            "non_key_update": False,
            "for_update": True,
            "key_update": True,
            "delete": True,
        },
    }.items():
        holder = scratch.connect()
        holder.execute(text(f"SELECT 1 FROM {SCHEMA}.locked WHERE k = 1 {mode}"))
        try:
            observed = {
                "non_key_update": blocked(f"UPDATE {SCHEMA}.locked SET v = v + 1 WHERE k = 1"),
                "for_update": blocked(f"SELECT 1 FROM {SCHEMA}.locked WHERE k = 1 FOR UPDATE"),
                "key_update": blocked(f"UPDATE {SCHEMA}.locked SET k = 2 WHERE k = 1"),
                "delete": blocked(f"DELETE FROM {SCHEMA}.locked WHERE k = 1"),
            }
        finally:
            holder.rollback()
            holder.close()
        assert observed == expectations, mode


# --- campaign lifecycle writers --------------------------------------------------------------------

_CAMPAIGN_UPDATE = re.compile(
    r"UPDATE\s+campaign\.campaigns\b|DELETE\s+FROM\s+campaign\.campaigns\b"
    r"|INSERT\s+INTO\s+campaign\.campaigns\b[^;]*?\bON\s+CONFLICT\b[^;]*?\bDO\s+UPDATE\b",
    re.IGNORECASE | re.DOTALL,
)


def _string_literals(tree: ast.AST) -> Iterator[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value, node.lineno
        elif isinstance(node, ast.JoinedStr):
            yield (
                "".join(
                    part.value if isinstance(part, ast.Constant) else "{}" for part in node.values
                ),
                node.lineno,
            )


def _enclosing_function(tree: ast.AST, lineno: int) -> str:
    best: tuple[int, str] | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            end = node.end_lineno or node.lineno
            if node.lineno <= lineno <= end and (best is None or end - node.lineno < best[0]):
                best = (end - node.lineno, node.name)
    return best[1] if best else "<module>"


def _call_lines(function: ast.AST, name: str) -> list[int]:
    return sorted(
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", "")) == name
    )


def test_every_campaign_lifecycle_writer_locks_the_campaign_for_update_first(
    postgres_engine: Engine,
) -> None:
    """ESTABLISHES (plan section 4.1, [A]; section 12.1): the only statements in `src` and `scripts`
    that `UPDATE` or `DELETE` a `campaign.campaigns` row are in `update_campaign` and
    `_set_campaign_lifecycle` (`dnd_ai.commands.campaigns`); each is reached only after a call to
    `_lock_campaign_for_manage`, which runs `SELECT ... FOR UPDATE OF c` on the campaign row first. In
    the database, no function body (trigger or otherwise) updates `campaign.campaigns`, and the
    campaign is not an entity subtype (no foreign key to `core.entities`), so `core.entities` lifecycle
    commands cannot change a campaign's status.

    DOES NOT ESTABLISH: runtime order (this is source order: the line of the lock call precedes the
    line of the write in each function); out-of-band writers (migrations such as revision 024,
    administrator SQL, test fixtures); SQL assembled from names at run time (the scan sees literals
    and f-string literal parts only). A runtime recorder over the three lifecycle routes is an S1
    obligation (plan section 12.5)."""
    hits: set[tuple[str, str]] = set()
    trees: dict[str, ast.AST] = {}
    for root in (SRC, REPO / "scripts"):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            relative = path.relative_to(REPO).as_posix()
            trees[relative] = tree
            for literal, lineno in _string_literals(tree):
                if _CAMPAIGN_UPDATE.search(literal):
                    hits.add((relative, _enclosing_function(tree, lineno)))
    assert hits == {
        ("src/dnd_ai/commands/campaigns.py", "update_campaign"),
        ("src/dnd_ai/commands/campaigns.py", "_set_campaign_lifecycle"),
    }

    campaigns = trees["src/dnd_ai/commands/campaigns.py"]
    functions = {
        node.name: node for node in ast.walk(campaigns) if isinstance(node, ast.FunctionDef)
    }
    update = functions["update_campaign"]
    write_line = next(
        lineno for literal, lineno in _string_literals(update) if _CAMPAIGN_UPDATE.search(literal)
    )
    assert _call_lines(update, "_lock_campaign_for_manage")[0] < write_line
    callers = [
        name
        for name, node in functions.items()
        if name != "_set_campaign_lifecycle" and _call_lines(node, "_set_campaign_lifecycle")
    ]
    assert sorted(callers) == ["archive_campaign", "reactivate_campaign"]
    for name in callers:
        node = functions[name]
        assert (
            _call_lines(node, "_lock_campaign_for_manage")[0]
            < _call_lines(node, "_set_campaign_lifecycle")[0]
        ), name
    lock_function = functions["_lock_campaign_for_manage"]
    assert any(
        re.search(r"FOR\s+UPDATE\s+OF\s+c\b", literal, re.IGNORECASE)
        for literal, _ in _string_literals(lock_function)
    )

    bodies = _function_bodies(postgres_engine)
    assert [
        name
        for name, body in bodies.items()
        if re.search(r"UPDATE\s+campaign\.campaigns", body, re.I)
    ] == []
    with postgres_engine.connect() as connection:
        references = {
            row[0]
            for row in connection.execute(
                text("""
                    SELECT confrelid::regclass::text FROM pg_constraint
                    WHERE contype = 'f' AND conrelid = 'campaign.campaigns'::regclass
                """)
            ).all()
        }
    assert "core.entities" not in references


# --- the request transaction's exit: how an error raised there maps --------------------------------


class _GuardRuntimeError(RuntimeError):
    """Stands in for a commit guard's error that is a plain Exception."""


class _GuardValueError(ValueError):
    """The same, if it were (wrongly) a ValueError."""


def _exit_probe_app(engine: Engine) -> Any:
    from typing import Annotated

    from fastapi import Depends, FastAPI
    from sqlalchemy import Connection

    import dnd_ai.api.deps as deps
    from dnd_ai.api.errors import ForbiddenError, install_error_handlers
    from dnd_ai.domain.errors import DomainAuthorizationError

    app = FastAPI(dependencies=[Depends(deps.commit_request_transaction, scope="function")])
    install_error_handlers(app)
    classes: dict[str, type[BaseException]] = {
        "runtime": _GuardRuntimeError,
        "value_error": _GuardValueError,
        "domain_authorization": DomainAuthorizationError,
        "forbidden": ForbiddenError,
    }

    @app.post("/write")
    def write(connection: Annotated[Connection, Depends(deps.get_connection)]) -> dict[str, bool]:
        connection.execute(text(f"INSERT INTO {SCHEMA}.marker VALUES (7)"))
        return {"ok": True}

    @app.post("/handler-raises/{kind}")
    def handler_raises(
        kind: str, connection: Annotated[Connection, Depends(deps.get_connection)]
    ) -> dict[str, bool]:
        connection.execute(text(f"INSERT INTO {SCHEMA}.marker VALUES (7)"))
        raise classes[kind]()

    app.dependency_overrides[deps.get_engine] = lambda: engine
    return app


def _marker_rows(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.marker")).scalar_one())


@pytest.mark.parametrize(
    ("kind", "expected_status"),
    [("runtime", 500), ("value_error", 400), ("domain_authorization", 404), ("forbidden", 403)],
)
def test_an_error_raised_in_the_commit_dependency_exit_maps_by_class_and_persists_nothing(
    scratch: Engine, monkeypatch: pytest.MonkeyPatch, kind: str, expected_status: int
) -> None:
    """ESTABLISHES (plan section 6.3, [A]; section 6.5): an exception raised **at the request
    transaction's exit** (the `_commit` seam that `commit_request_transaction` calls) is mapped by the
    app's ordinary exception handlers *by its class*, exactly as one raised in the handler is:
    a plain `RuntimeError` subclass -> 500, a `ValueError` subclass -> 400, a `DomainAuthorizationError`
    -> 404, a `ForbiddenError` -> 403. In every case the transaction is rolled back (the row the
    request inserted is absent) and the response is sent after that.

    CONSEQUENCE: the plan's "[A] an error raised in the exit maps to 5xx" holds **only if the commit
    guard's error is not a `ValueError`, `SafeMessageError`, `ApiError` or `IntegrityError`**.
    `AuthorizationPlanNotFinalizedError` must derive from `RuntimeError` (or bare `Exception`) and a
    test must pin that; a guard error written in the codebase's usual `SafeMessageError` style would
    surface as a 4xx on an unfinalised write. Placing the final check in the handler (plan section 6.3)
    is still right, but for its own reason: the refusal must map to the route's real error class.

    DOES NOT ESTABLISH: behavior under cancellation (covered by the existing P3 tests); a guard
    refusal raised by an SQLAlchemy `commit` event (next test)."""
    from fastapi.testclient import TestClient

    import dnd_ai.api.deps as deps

    errors: dict[str, type[BaseException]] = {
        "runtime": _GuardRuntimeError,
        "value_error": _GuardValueError,
        "domain_authorization": __import__(
            "dnd_ai.domain.errors", fromlist=["DomainAuthorizationError"]
        ).DomainAuthorizationError,
        "forbidden": __import__("dnd_ai.api.errors", fromlist=["ForbiddenError"]).ForbiddenError,
    }

    def refusing_commit(connection: Any) -> None:
        raise errors[kind]()

    monkeypatch.setattr(deps, "_commit", refusing_commit)
    with TestClient(_exit_probe_app(scratch), raise_server_exceptions=False) as client:
        from_exit = client.post("/write")
    assert from_exit.status_code == expected_status
    assert _marker_rows(scratch) == 0, "a refused commit persisted the request's write"

    monkeypatch.undo()
    with TestClient(_exit_probe_app(scratch), raise_server_exceptions=False) as client:
        from_handler = client.post(f"/handler-raises/{kind}")
    assert from_handler.status_code == expected_status, "exit and handler mapping differ"
    assert _marker_rows(scratch) == 0


def _idle_in_transaction(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("""
                    SELECT count(*) FROM pg_stat_activity
                    WHERE datname = current_database() AND state = 'idle in transaction'
                """)
            ).scalar_one()
        )


@pytest.mark.parametrize("mitigation", ["none", "rollback_in_listener"])
def test_a_raising_commit_event_prevents_the_commit_but_the_unmodified_exit_leaves_the_session_dirty(
    scratch: Engine, mitigation: str
) -> None:
    """CHARACTERISATION of a hazard in the plan's section 6.5, rule 3 mechanism (plan [A]: "raising in
    the `commit` event prevents the DBAPI COMMIT"). **Updated by slice T0 (plan section 6.8).**

    ESTABLISHES (unchanged): a listener on the application engine's `commit` event that raises **does
    prevent the DBAPI COMMIT**: the request's write is absent and the response is a 500.

    ORIGINAL S0 FINDING (historical evidence, observed 2026-11-12 at 395d595, before T0): with the
    request-transaction exit as it was (`_finish` -> `_discard`), the refused transaction was **not
    rolled back**. SQLAlchemy marks its transaction finished when the event raises, so
    `connection.in_transaction()` was False, `_discard` skipped its rollback, and the pool's
    reset-on-return was skipped too. The session stayed `idle in transaction`, holding the request's
    row locks, and the **next request that reused that pooled connection committed the refused write**:
    the run ended with two rows and one idle-in-transaction session after the refusal. With
    `mitigation="rollback_in_listener"` (the listener rolls the DBAPI connection back before raising)
    the session was clean and only the second write persisted.

    AFTER T0: `_discard` follows the driver's transaction status, so the `none` case now ends with one
    row (only the second request's) and no idle-in-transaction session, the same as the mitigated
    case. The test name keeps its S0 spelling because the plan refers to it.

    DOES NOT ESTABLISH: behavior with `pool_pre_ping` or a different pool class (a one-connection
    `QueuePool` is used so that reuse is certain); the behavior of a real database commit failure
    (see `test_request_transaction_failure_cleanup.py`, T0.3)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import event

    one = create_engine(scratch.url, pool_size=1, max_overflow=0)
    calls: list[int] = []

    def guard(connection: Any) -> None:
        calls.append(1)
        if len(calls) == 1:
            if mitigation == "rollback_in_listener":
                connection.connection.driver_connection.rollback()
            raise _GuardRuntimeError("plan not finalised")

    event.listen(one, "commit", guard)
    try:
        with TestClient(_exit_probe_app(one), raise_server_exceptions=False) as client:
            refused = client.post("/write")
            assert refused.status_code == 500
            assert _marker_rows(scratch) == 0, "the DBAPI COMMIT ran although the listener raised"
            idle_after_refusal = _idle_in_transaction(scratch)
            allowed = client.post("/write")
            assert allowed.status_code == 200
        rows = _marker_rows(scratch)
    finally:
        one.dispose()
    assert len(calls) == 2
    # T0: both cases end clean. Before T0 the `none` case had one idle-in-transaction session after
    # the refusal and two rows at the end (the refused write was committed by the next request).
    assert idle_after_refusal == 0, "the refused session was left idle in transaction"
    assert rows == 1, "the refused write was committed, or the second write was lost"
