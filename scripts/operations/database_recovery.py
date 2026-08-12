"""Production database recovery operations for the self-hosted Docker Compose topology.

Consolidates the destructive Compose/psql sequences documented in
docs/DEVELOPMENT.md §3.6 (backup, role bootstrap, restore, verification,
teardown) into one auditable, cross-platform tool, so the exact flags,
environment file, project name, and database identity used are identical
regardless of which shell invokes it — replacing hand-duplicated Bash and
PowerShell command blocks that had repeatedly drifted apart.

Usage:
    uv run python scripts/operations/database_recovery.py <command> [options]

Commands:
    backup          Dump a database to a host file.
    verify-roles    Check the six cluster-wide roles exist with the right
                    LOGIN/NOLOGIN attributes and membership.
    bootstrap-roles Create the six roles on a cluster that's missing them,
                    via a deliberately named temporary database.
    restore         Force-drop/recreate (or in fresh-cluster mode, bootstrap
                    then drop/recreate) the target database and restore a dump.
    verify          Run the full post-recovery acceptance battery.
    teardown        `down -v` a Compose project.

This script never reads or prints POSTGRES_PASSWORD, MIGRATION_DATABASE_URL,
or any other credential — it only ever passes `--env-file <path>` through to
`docker compose`, which resolves secrets itself. Every subprocess is invoked
as an argument list (never `shell=True`, never a string re-parsed by a
shell), and every configurable SQL identifier this script builds itself
(database names) is passed through psql's `-v`/`:'var'`/`\\gexec`
safe-substitution mechanism rather than string-interpolated into SQL text —
see the `_grant_create_on_database` docstring below for why.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Six roles from database/migrations/versions/001_bootstrap.py and
# docs/DATABASE_CONVENTIONS.md §27.1 — migration_owner is the sole NOLOGIN
# ownership anchor, the other five are LOGIN roles.
REQUIRED_ROLES: dict[str, bool] = {
    "migration_owner": False,
    "migration_runner": True,
    "app_read_write": True,
    "app_read_only": True,
    "integration_worker": True,
    "admin_maintenance": True,
}

# Extensions 001_bootstrap always installs; btree_gist is installed later
# (revision 009) and is only expected once a database is at or past that
# revision, so its absence is reported, not treated as a hard failure.
REQUIRED_EXTENSIONS = ("pgcrypto", "pg_trgm")
OPTIONAL_EXTENSIONS = ("btree_gist",)

PLACEHOLDER_RE = re.compile(r"<[^>]*>")

MAINTENANCE_DATABASE = "postgres"


class OperationError(RuntimeError):
    """A destructive or verification operation failed or refused to proceed."""


def _reject_placeholder(label: str, value: str) -> None:
    if PLACEHOLDER_RE.search(value):
        raise OperationError(
            f"{label} looks like an unfilled documentation placeholder ({value!r}) "
            "— replace it with a real value before running this command."
        )


@dataclass(frozen=True)
class ComposeTarget:
    """The complete, closed-over configuration tuple every command uses.

    Every operation in this module builds its `docker compose` invocation
    from this object alone — never from a default `.env`, default project
    discovery, or a Compose file list assembled anywhere else — so a
    drill/major-upgrade/production invocation can never silently share
    state with another one.
    """

    project: str
    env_file: Path
    compose_files: tuple[Path, ...]
    db_user: str
    db_name: str

    def __post_init__(self) -> None:
        _reject_placeholder("--project", self.project)
        _reject_placeholder("--env-file", str(self.env_file))
        for f in self.compose_files:
            _reject_placeholder("--compose-file", str(f))
        _reject_placeholder("--db-user", self.db_user)
        _reject_placeholder("--db-name", self.db_name)
        if not self.compose_files:
            raise OperationError("at least one --compose-file is required.")

    def base_args(self) -> list[str]:
        args = ["docker", "compose", "--env-file", str(self.env_file), "-p", self.project]
        for f in self.compose_files:
            args += ["-f", str(f)]
        return args

    def describe(self) -> str:
        files = " ".join(str(f) for f in self.compose_files)
        return (
            f"    project:       {self.project}\n"
            f"    env file:      {self.env_file}\n"
            f"    compose files: {files}\n"
            f"    db user:       {self.db_user}\n"
            f"    db name:       {self.db_name}\n"
        )


def announce(operation: str, target: ComposeTarget, **extra: str) -> None:
    """Print exactly what is about to run, before any destructive work."""
    print(f"== {operation} ==")
    print(target.describe(), end="")
    for key, value in extra.items():
        print(f"    {key}: {value}")
    print()


def run(
    cmd: list[str], *, input_text: str | None = None, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess from an explicit argument list — never a shell string."""
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd, input=input_text, text=True, capture_output=capture)


def compose_run(
    target: ComposeTarget, *extra_args: str, input_text: str | None = None, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    return run(target.base_args() + list(extra_args), input_text=input_text, capture=capture)


def _check(condition: bool, ok_message: str, fail_message: str) -> tuple[bool, str]:
    return (condition, ok_message if condition else fail_message)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    hard: bool = True  # hard failures make the overall command exit nonzero


@dataclass
class Report:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str, *, hard: bool = True) -> None:
        self.results.append(CheckResult(name, passed, detail, hard))

    def print_summary(self) -> bool:
        print()
        print("-- results --")
        ok = True
        for r in self.results:
            status = "PASS" if r.passed else ("WARN" if not r.hard else "FAIL")
            print(f"[{status}] {r.name}: {r.detail}")
            if r.hard and not r.passed:
                ok = False
        print()
        print("OVERALL: " + ("PASS" if ok else "FAIL"))
        return ok


# ---------------------------------------------------------------------------
# Role verification — shared by `verify-roles`, `bootstrap-roles`, `restore`,
# and `verify`.
# ---------------------------------------------------------------------------


def check_roles(target: ComposeTarget, connect_user: str) -> tuple[Report, dict[str, bool]]:
    """Verify the six cluster-wide roles against the `postgres` maintenance database.

    Connects to `postgres`, never the application database — role
    definitions and membership are cluster-wide, and on an existing cluster
    with a damaged or missing application database, this must succeed
    without ever touching it.
    """
    report = Report()

    role_list = ", ".join(f"'{name}'" for name in REQUIRED_ROLES)
    result = compose_run(
        target,
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        connect_user,
        "-d",
        MAINTENANCE_DATABASE,
        "-t",
        "-A",
        "-F",
        ",",
        "-c",
        f"SELECT rolname, rolcanlogin FROM pg_catalog.pg_roles WHERE rolname IN ({role_list}) ORDER BY rolname;",
        capture=True,
    )
    if result.returncode != 0:
        report.add("role query", False, f"psql failed: {result.stderr.strip()}")
        return report, {}

    found: dict[str, bool] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        name, _, canlogin = line.partition(",")
        found[name] = canlogin.strip() == "t"

    missing = [name for name in REQUIRED_ROLES if name not in found]
    ok, detail = _check(
        not missing,
        "all six roles exist",
        f"missing roles: {', '.join(missing)}",
    )
    report.add("roles exist", ok, detail)

    for name, expect_login in REQUIRED_ROLES.items():
        if name not in found:
            continue
        actual_login = found[name]
        ok, detail = _check(
            actual_login == expect_login,
            f"{'LOGIN' if expect_login else 'NOLOGIN'} as required",
            f"expected {'LOGIN' if expect_login else 'NOLOGIN'}, got {'LOGIN' if actual_login else 'NOLOGIN'}",
        )
        report.add(f"role {name} attribute", ok, detail)

    membership_result = compose_run(
        target,
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        connect_user,
        "-d",
        MAINTENANCE_DATABASE,
        "-t",
        "-A",
        "-c",
        "SELECT EXISTS (SELECT 1 FROM pg_auth_members m "
        "JOIN pg_roles r ON r.oid = m.roleid "
        "JOIN pg_roles mem ON mem.oid = m.member "
        "WHERE r.rolname = 'migration_owner' AND mem.rolname = 'migration_runner');",
        capture=True,
    )
    member_ok = membership_result.returncode == 0 and membership_result.stdout.strip() == "t"
    report.add(
        "migration_runner member of migration_owner",
        member_ok,
        "confirmed" if member_ok else "not a member (or roles missing/query failed)",
    )

    return report, found


def cmd_verify_roles(args: argparse.Namespace) -> int:
    target = ComposeTarget(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
        db_user=args.connect_user,
        db_name="(cluster-wide check — no application database used)",
    )
    announce("verify-roles", target)
    report, _ = check_roles(target, args.connect_user)
    return 0 if report.print_summary() else 1


# ---------------------------------------------------------------------------
# bootstrap-roles
# ---------------------------------------------------------------------------


def cmd_bootstrap_roles(args: argparse.Namespace) -> int:
    target = ComposeTarget(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
        db_user=args.connect_user,
        db_name=args.temp_db_name,
    )
    if args.temp_db_name == args.protect_db_name:
        raise OperationError(
            "--temp-db-name must not equal --protect-db-name — bootstrap-roles is only "
            "for a database that is not the real recovery target."
        )
    if not args.confirm_env_targets_temp_db:
        raise OperationError(
            "refusing to continue: pass --confirm-env-targets-temp-db to confirm that "
            f"--env-file {args.env_file}'s MIGRATION_DATABASE_URL points at the temporary "
            f"database {args.temp_db_name!r}, not the real recovery target. This script "
            "never reads that file to check for you."
        )

    announce(
        "bootstrap-roles",
        target,
        protect_db_name=args.protect_db_name,
    )

    print(f"-- creating temporary bootstrap database {args.temp_db_name!r} --")
    create = compose_run(
        target,
        "exec",
        "-T",
        "db",
        "createdb",
        "-U",
        args.connect_user,
        "--owner",
        args.connect_user,
        args.temp_db_name,
    )
    if create.returncode != 0:
        print(
            f"createdb failed — if {args.temp_db_name!r} already exists from an earlier "
            "attempt, inspect it before re-running (it may hold evidence of a prior failure).",
            file=sys.stderr,
        )
        return 1

    print("-- running migrations against the temporary database --")
    migrate = compose_run(target, "--profile", "tools", "run", "--rm", "migrate")
    if migrate.returncode != 0:
        print(
            f"migration run failed. The temporary database {args.temp_db_name!r} was left "
            "in place for inspection — remove it by hand once you're done.",
            file=sys.stderr,
        )
        return 1

    print("-- verifying roles were created --")
    report, _ = check_roles(target, args.connect_user)
    ok = report.print_summary()

    if not ok:
        print(
            f"Role verification failed after bootstrap. The temporary database "
            f"{args.temp_db_name!r} was left in place for inspection.",
            file=sys.stderr,
        )
        return 1

    print(f"-- dropping temporary bootstrap database {args.temp_db_name!r} --")
    drop = compose_run(
        target,
        "exec",
        "-T",
        "db",
        "dropdb",
        "-U",
        args.connect_user,
        "--if-exists",
        "--force",
        args.temp_db_name,
    )
    if drop.returncode != 0:
        print(
            f"Roles verified, but cleanup of the temporary database {args.temp_db_name!r} "
            "failed — remove it by hand.",
            file=sys.stderr,
        )
        return 1

    print("bootstrap-roles: complete. All six roles verified; temporary database removed.")
    return 0


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


def _grant_create_on_database(
    target: ComposeTarget, connect_user: str, db_name: str
) -> subprocess.CompletedProcess[str]:
    """Reissue GRANT CREATE ON DATABASE ... TO migration_owner.

    dropdb/createdb discards the database-level ACL 001_bootstrap set up
    (docs/DEVELOPMENT.md §3.6, "What dropping and recreating the database
    loses"). db_name is passed as a psql variable and substituted with the
    safe-quoting `:'dbname'` form, then run through `format('%I', ...)`
    server-side to produce a properly quoted identifier and re-executed via
    `\\gexec` — this is safe regardless of what characters db_name contains,
    unlike interpolating it directly into a GRANT statement string. The SQL
    is piped on stdin rather than passed via `-c`, because `:'var'`
    substitution is a feature of psql's query-scanning input stream, not of
    `-c` arguments (confirmed: `-c` sends the text close to verbatim and
    `:'dbname'` reaches the server as a literal syntax error).
    """
    sql = "SELECT format('GRANT CREATE ON DATABASE %I TO migration_owner', :'dbname') \\gexec"
    return compose_run(
        target,
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        connect_user,
        "-d",
        MAINTENANCE_DATABASE,
        "-v",
        f"dbname={db_name}",
        input_text=sql,
    )


def cmd_restore(args: argparse.Namespace) -> int:
    target = ComposeTarget(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
        db_user=args.db_user,
        db_name=args.db_name,
    )
    dump_path = Path(args.dump_file)
    if not dump_path.is_file():
        raise OperationError(f"--dump-file {dump_path} does not exist or is not a file.")

    announce("restore", target, mode=args.mode, dump_file=str(dump_path))

    print(
        "-- quiesce reminder --\n"
        "Before continuing: stop or disconnect every other consumer of "
        f"{target.db_name!r} in project {target.project!r} (application services, "
        "interactive psql/GUI sessions, scheduled jobs). This script cannot see "
        "connections it didn't make itself. dropdb --force will terminate anything "
        "still connected, but that is a safety net, not a substitute for quiescing "
        "deliberately.\n"
    )

    if args.mode == "existing":
        print(
            "-- existing-cluster mode: verifying roles without connecting to the target database --"
        )
        report, _ = check_roles(target, args.db_user)
        if not report.print_summary():
            print(
                "\nRoles are missing or incorrect on this cluster. Do not overload the "
                "recovery target merely to manufacture them — run `bootstrap-roles` "
                "first, against a deliberately named temporary database, then re-run "
                "this restore.",
                file=sys.stderr,
            )
            return 1
        print(
            "Roles verified — proceeding without requiring Alembic to connect to the target database.\n"
        )
    else:
        print(
            "-- fresh-cluster mode: running migrations against the freshly created application database --"
        )
        migrate = compose_run(target, "--profile", "tools", "run", "--rm", "migrate")
        if migrate.returncode != 0:
            print(
                "Initial role/schema bootstrap failed — nothing else was touched.", file=sys.stderr
            )
            return 1
        print("-- verifying roles were created --")
        report, _ = check_roles(target, args.db_user)
        if not report.print_summary():
            print(
                "\nRole verification failed immediately after bootstrap — stopping.",
                file=sys.stderr,
            )
            return 1
        print()

    if not args.confirm_drop:
        raise OperationError(
            "refusing to continue: pass --confirm-drop to force-drop the target database."
        )

    print(f"-- force-dropping and recreating {target.db_name!r} --")
    drop = compose_run(
        target,
        "exec",
        "-T",
        "db",
        "dropdb",
        "-U",
        target.db_user,
        "--if-exists",
        "--force",
        target.db_name,
    )
    if drop.returncode != 0:
        print("dropdb failed — nothing further was touched.", file=sys.stderr)
        return 1

    create = compose_run(
        target,
        "exec",
        "-T",
        "db",
        "createdb",
        "-U",
        target.db_user,
        "--owner",
        target.db_user,
        target.db_name,
    )
    if create.returncode != 0:
        print(
            f"createdb failed after the previous database was already dropped — "
            f"{target.db_name!r} does not currently exist. Investigate before retrying.",
            file=sys.stderr,
        )
        return 1

    print("-- reapplying GRANT CREATE ON DATABASE ... TO migration_owner --")
    grant = _grant_create_on_database(target, target.db_user, target.db_name)
    if grant.returncode != 0:
        print(
            f"Reapplying the CREATE ON DATABASE grant failed. {target.db_name!r} exists but "
            "is missing this privilege — do not restore into it until this is fixed.",
            file=sys.stderr,
        )
        return 1

    if not args.confirm_restore:
        raise OperationError(
            f"refusing to continue: {target.db_name!r} was recreated and is ready, but "
            "restoring requires --confirm-restore."
        )

    container_tmp = f"/tmp/restore-{os.getpid()}.dump"
    print(f"-- copying {dump_path} into the container and restoring --")
    cp = compose_run(target, "cp", str(dump_path), f"db:{container_tmp}")
    if cp.returncode != 0:
        print(
            "Copying the dump into the container failed — target database is empty but intact.",
            file=sys.stderr,
        )
        return 1

    restore = compose_run(
        target,
        "exec",
        "-T",
        "db",
        "pg_restore",
        "-U",
        target.db_user,
        "-d",
        target.db_name,
        container_tmp,
    )
    if restore.returncode != 0:
        print(
            f"pg_restore failed. The in-container copy at {container_tmp} was left in place "
            "for inspection — remove it by hand once you're done. The target database was "
            "NOT deleted or recreated again automatically.",
            file=sys.stderr,
        )
        return 1

    cleanup = compose_run(target, "exec", "-T", "db", "rm", container_tmp)
    if cleanup.returncode != 0:
        print(
            f"Restore succeeded, but removing the in-container copy at {container_tmp} failed.",
            file=sys.stderr,
        )

    print(
        "\nrestore: complete. Before treating this deployment as authoritative:\n"
        "  1. Run `verify` against it.\n"
        "  2. Reapply or rotate runtime credentials for migration_runner/app_read_write/"
        "app_read_only/integration_worker/admin_maintenance from your own secret-management "
        "process — restoring a dump never recovers passwords or other post-deployment role changes."
    )
    return 0


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def _psql_scalar(target: ComposeTarget, sql: str) -> tuple[bool, str]:
    result = compose_run(
        target,
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        target.db_user,
        "-d",
        target.db_name,
        "-t",
        "-A",
        "-c",
        sql,
        capture=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, result.stdout.strip()


def _psql_rows(target: ComposeTarget, sql: str) -> tuple[bool, list[tuple[str, ...]]]:
    result = compose_run(
        target,
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        target.db_user,
        "-d",
        target.db_name,
        "-t",
        "-A",
        "-F",
        ",",
        "-c",
        sql,
        capture=True,
    )
    if result.returncode != 0:
        return False, []
    rows = [tuple(line.split(",")) for line in result.stdout.splitlines() if line.strip()]
    return True, rows


_OWNERSHIP_QUERIES = {
    "schemas": (
        "SELECT pg_get_userbyid(nspowner) AS owner, count(*) FROM pg_namespace "
        "WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'public') "
        "AND nspname NOT LIKE 'pg\\_%' GROUP BY owner ORDER BY 2 DESC;"
    ),
    "relations": (
        "SELECT pg_get_userbyid(c.relowner) AS owner, count(*) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'public') "
        "AND c.relkind IN ('r', 'p', 'S', 'v', 'm') "
        "AND NOT (n.nspname = 'core' AND c.relname = 'alembic_version') "
        "GROUP BY owner ORDER BY 2 DESC;"
    ),
    "functions": (
        "SELECT pg_get_userbyid(p.proowner) AS owner, count(*) FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'public') "
        "GROUP BY owner ORDER BY 2 DESC;"
    ),
    "domains/enums": (
        "SELECT pg_get_userbyid(t.typowner) AS owner, count(*) FROM pg_type t "
        "JOIN pg_namespace n ON n.oid = t.typnamespace "
        "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'public') "
        "AND t.typtype IN ('d', 'e') GROUP BY owner ORDER BY 2 DESC;"
    ),
}


def _check_single_owner(
    report: Report, target: ComposeTarget, label: str, sql: str, expected_owner: str
) -> None:
    ok, rows = _psql_rows(target, sql)
    if not ok:
        report.add(f"{label} ownership", False, "query failed")
        return
    owners = {row[0] for row in rows}
    total = sum(int(row[1]) for row in rows)
    passed = owners == {expected_owner} or (not owners and total == 0)
    detail = f"{total} objects, owner(s): {', '.join(sorted(owners)) or '(none)'}"
    report.add(f"{label} ownership", passed, detail)


def cmd_verify(args: argparse.Namespace) -> int:
    target = ComposeTarget(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
        db_user=args.db_user,
        db_name=args.db_name,
    )
    connect_role = args.connect_role or args.db_user
    announce("verify", target, connect_role=connect_role)
    report = Report()

    print("-- role verification --")
    role_report, _ = check_roles(target, args.db_user)
    report.results.extend(role_report.results)

    print("-- database CREATE privilege --")
    ok, value = _psql_scalar(
        target, "SELECT has_database_privilege('migration_owner', current_database(), 'CREATE');"
    )
    report.add(
        "migration_owner CREATE ON DATABASE", ok and value == "t", value if ok else "query failed"
    )

    print("-- ownership --")
    for label, sql in _OWNERSHIP_QUERIES.items():
        _check_single_owner(report, target, label, sql, "migration_owner")

    print("-- core.alembic_version exceptional ownership --")
    ok, value = _psql_scalar(
        target,
        "SELECT pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'core' AND c.relname = 'alembic_version';",
    )
    report.add(
        "core.alembic_version owner",
        ok and value == connect_role,
        f"owned by {value!r}, expected connecting role {connect_role!r}" if ok else "query failed",
    )

    print("-- extensions --")
    ok, rows = _psql_rows(
        target,
        "SELECT extname FROM pg_extension WHERE extname IN "
        f"({', '.join(repr(e) for e in REQUIRED_EXTENSIONS + OPTIONAL_EXTENSIONS)}) ORDER BY 1;",
    )
    present = {row[0] for row in rows} if ok else set()
    for ext in REQUIRED_EXTENSIONS:
        report.add(f"extension {ext}", ext in present, "installed" if ext in present else "MISSING")
    for ext in OPTIONAL_EXTENSIONS:
        report.add(
            f"extension {ext} (optional)",
            ext in present,
            "installed"
            if ext in present
            else "not installed — fine if this database predates its introduction",
            hard=False,
        )

    print("-- Alembic revision --")
    current = compose_run(
        target,
        "--profile",
        "tools",
        "run",
        "--rm",
        "migrate",
        "alembic",
        "-c",
        "database/alembic.ini",
        "current",
        capture=True,
    )
    report.add(
        "alembic current",
        current.returncode == 0,
        current.stdout.strip() or current.stderr.strip(),
    )

    print("-- migration machinery (clean upgrade to head) --")
    migrate = compose_run(target, "--profile", "tools", "run", "--rm", "migrate")
    report.add(
        "alembic upgrade head",
        migrate.returncode == 0,
        "ran cleanly (this proves migration machinery works end-to-end; it does not by "
        "itself prove CREATE ON DATABASE — the privilege check above already did that directly)",
    )

    print("-- structural table counts --")
    ok, rows = _psql_rows(
        target,
        "SELECT schemaname, count(*) FROM pg_tables WHERE schemaname NOT IN "
        "('pg_catalog', 'information_schema', 'public') GROUP BY schemaname ORDER BY 1;",
    )
    total_tables = sum(int(row[1]) for row in rows) if ok else 0
    report.add(
        "domain tables exist",
        ok and total_tables > 0,
        f"{total_tables} tables across {len(rows)} schemas" if ok else "query failed",
    )
    print(
        "    (structural only — proves the schema exists, not that any particular "
        "business data does. A structurally valid deployment may legitimately have "
        "zero rows in any given table.)"
    )

    for query, expected in args.check or []:
        stripped = query.strip().rstrip(";")
        if not stripped.lower().startswith("select"):
            report.add(
                f"check: {query}",
                False,
                "refused — operator-supplied checks must be SELECT statements",
            )
            continue
        if ";" in stripped:
            report.add(f"check: {query}", False, "refused — only a single statement is allowed")
            continue
        ok, value = _psql_scalar(target, stripped + ";")
        report.add(
            f"check: {query}",
            ok and value == expected,
            f"got {value!r}, expected {expected!r}" if ok else "query failed",
        )

    return 0 if report.print_summary() else 1


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


def cmd_backup(args: argparse.Namespace) -> int:
    target = ComposeTarget(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
        db_user=args.db_user,
        db_name=args.db_name,
    )
    output = Path(args.output)
    if output.exists() and not args.overwrite:
        raise OperationError(f"--output {output} already exists — pass --overwrite to replace it.")

    announce("backup", target, output=str(output))

    container_tmp = f"/tmp/{target.db_name}-{os.getpid()}.dump"
    dump = compose_run(
        target,
        "exec",
        "-T",
        "db",
        "pg_dump",
        "-U",
        target.db_user,
        "-d",
        target.db_name,
        "-Fc",
        "-f",
        container_tmp,
    )
    if dump.returncode != 0:
        print("pg_dump failed.", file=sys.stderr)
        return 1

    cp = compose_run(target, "cp", f"db:{container_tmp}", str(output))
    if cp.returncode != 0:
        print(
            f"Copying the dump out of the container failed. The in-container copy at "
            f"{container_tmp} was left in place for inspection.",
            file=sys.stderr,
        )
        return 1

    cleanup = compose_run(target, "exec", "-T", "db", "rm", container_tmp)
    if cleanup.returncode != 0:
        print(
            f"Backup succeeded, but removing the in-container copy at {container_tmp} failed.",
            file=sys.stderr,
        )

    print(f"\nbackup: complete. {output} written.")
    print(
        "Reminder: this file is a database-only artifact — it does not include cluster-wide "
        'roles. See docs/DEVELOPMENT.md §3.6, "What a pg_dump backup does not cover."'
    )
    return 0


# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------


def cmd_teardown(args: argparse.Namespace) -> int:
    target = ComposeTarget(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
        db_user="(not applicable)",
        db_name="(not applicable)",
    )
    if not args.confirm_teardown:
        raise OperationError("refusing to continue: pass --confirm-teardown to run `down -v`.")

    announce("teardown", target)
    result = compose_run(target, "down", "-v")
    return 0 if result.returncode == 0 else 1


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------


def _add_target_args(sub: argparse.ArgumentParser, *, with_db: bool = True) -> None:
    sub.add_argument(
        "--project", required=True, help="Compose project name (never guessed/defaulted)."
    )
    sub.add_argument(
        "--env-file", required=True, help="Compose --env-file to use for every command."
    )
    sub.add_argument(
        "--compose-file",
        action="append",
        required=True,
        default=[],
        help="Compose -f file; repeat to add more (e.g. a temporary image override). "
        "At least one required, typically compose.yaml.",
    )
    if with_db:
        sub.add_argument("--db-user", default="postgres", help="Database user (default: postgres).")
        sub.add_argument("--db-name", default="dnd_ai", help="Database name (default: dnd_ai).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="database_recovery.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_backup = sub.add_parser("backup", help="Dump a database to a host file.")
    _add_target_args(p_backup)
    p_backup.add_argument("--output", required=True, help="Host path to write the dump file to.")
    p_backup.add_argument(
        "--overwrite", action="store_true", help="Allow overwriting an existing --output file."
    )
    p_backup.set_defaults(func=cmd_backup)

    p_roles = sub.add_parser(
        "verify-roles",
        help="Check the six cluster-wide roles via the postgres maintenance database.",
    )
    _add_target_args(p_roles, with_db=False)
    p_roles.add_argument(
        "--connect-user", default="postgres", help="User to connect as (default: postgres)."
    )
    p_roles.set_defaults(func=cmd_verify_roles)

    p_bootstrap = sub.add_parser(
        "bootstrap-roles",
        help="Create the six roles via a deliberately named temporary database, then remove it.",
    )
    _add_target_args(p_bootstrap, with_db=False)
    p_bootstrap.add_argument(
        "--connect-user", default="postgres", help="Superuser to connect as (default: postgres)."
    )
    p_bootstrap.add_argument(
        "--temp-db-name",
        required=True,
        help="A deliberately named, disposable database to bootstrap roles into "
        "(e.g. dnd_ai_bootstrap_tmp). Must differ from --protect-db-name.",
    )
    p_bootstrap.add_argument(
        "--protect-db-name",
        default="dnd_ai",
        help="The real recovery target's database name, checked against --temp-db-name "
        "as a safety guard (default: dnd_ai).",
    )
    p_bootstrap.add_argument(
        "--confirm-env-targets-temp-db",
        action="store_true",
        help="Required: confirms --env-file's MIGRATION_DATABASE_URL points at "
        "--temp-db-name, not the real target. This script never reads that file to check.",
    )
    p_bootstrap.set_defaults(func=cmd_bootstrap_roles)

    p_restore = sub.add_parser(
        "restore", help="Force-drop/recreate the target database and restore a dump."
    )
    _add_target_args(p_restore)
    p_restore.add_argument(
        "--dump-file", required=True, help="Host path to the pg_dump -Fc file to restore."
    )
    p_restore.add_argument(
        "--mode",
        required=True,
        choices=["fresh", "existing"],
        help="fresh: brand-new cluster, bootstrap by migrating the freshly created target "
        "database directly. existing: surviving cluster — verify roles without ever "
        "connecting to the (possibly missing/corrupt) target database first.",
    )
    p_restore.add_argument(
        "--confirm-drop", action="store_true", help="Required to force-drop the target database."
    )
    p_restore.add_argument(
        "--confirm-restore",
        action="store_true",
        help="Required to restore over the recreated database.",
    )
    p_restore.set_defaults(func=cmd_restore)

    p_verify = sub.add_parser("verify", help="Run the full post-recovery acceptance battery.")
    _add_target_args(p_verify)
    p_verify.add_argument(
        "--connect-role",
        default=None,
        help="Expected owner of core.alembic_version (default: --db-user).",
    )
    p_verify.add_argument(
        "--check",
        nargs=2,
        metavar=("QUERY", "EXPECTED"),
        action="append",
        help="An additional read-only SELECT check and its expected scalar result. "
        'Repeatable. Example: --check "SELECT count(*) FROM core.worlds" "0"',
    )
    p_verify.set_defaults(func=cmd_verify)

    p_teardown = sub.add_parser("teardown", help="`down -v` a Compose project.")
    _add_target_args(p_teardown, with_db=False)
    p_teardown.add_argument(
        "--confirm-teardown", action="store_true", help="Required to run `down -v`."
    )
    p_teardown.set_defaults(func=cmd_teardown)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: int = args.func(args)
        return result
    except OperationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
