"""Production database recovery operations for the self-hosted Docker Compose topology.

Consolidates the destructive Compose/psql sequences documented in
docs/DEVELOPMENT.md §3.6 (backup, role bootstrap, restore, verification,
teardown) into one auditable, cross-platform tool, so the exact flags,
environment file, project name, and database identity used are identical
regardless of which shell invokes it.

Every mutating command (`restore`, `bootstrap-roles`) is split into two
strict phases:

  Phase A — preflight. Read-only. Validates arguments, files, Compose
  configuration, server reachability, required confirmation flags, dump
  archives, and (via an active connection, not just a flag) the actual
  database a migration run would target. Nothing is created, dropped, or
  modified in this phase, and it ends with a printed
  "PREFLIGHT PASSED — beginning destructive recovery" boundary.

  Phase B — mutation. Only entered once every Phase A check has passed.

`preflight` and `validate-archive` expose Phase A's checks as their own
read-only commands, callable independently of any mutation.

This script never reads or prints POSTGRES_PASSWORD, MIGRATION_DATABASE_URL,
or any other credential — it only ever passes `--env-file <path>` through to
`docker compose`, which resolves secrets itself, and the one place it reads
a database connection's identity (`verify_migration_target`) prints only the
resulting database/user names, never the URL. Every subprocess is invoked as
an argument list (never `shell=True`, never a string re-parsed by a shell),
and every configurable SQL identifier this script builds itself (database
names) is passed through psql's `-v`/`:'var'`/`\\gexec` safe-substitution
mechanism rather than string-interpolated into SQL text — see
`_grant_create_on_database`'s docstring for why.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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

# Databases that must never be the subject of dropdb/createdb/migration
# bootstrap — dropping or recreating any of these would be catastrophic to
# the cluster itself, not just this project's data.
RESERVED_DB_NAMES = frozenset({"postgres", "template0", "template1"})

PLACEHOLDER_RE = re.compile(r"<[^>]*>")
# Docker Compose project-name syntax: lowercase letters, digits, '-', '_',
# starting with a lowercase letter or digit.
PROJECT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# Project names that are too generic to safely target with a destructive
# teardown — most often the result of a forgotten or empty --project.
DEFAULT_LIKE_PROJECT_NAMES = frozenset({"default", "compose", "docker-compose"})

MAINTENANCE_DATABASE = "postgres"

# Runs a small psycopg-based check inside the `migrate` service's own
# container/environment, so the database it actually connects to is proven
# by a live connection through the exact configuration a real migration run
# would use — never by re-parsing the dotenv file (which this script never
# opens) and never by printing the connection URL. Only the resulting
# database and user names are printed, tab-separated on their own line, so
# the caller can find them even alongside `docker compose run`'s own
# container-lifecycle chatter.
_TARGET_CHECK_SCRIPT = """\
import os
import psycopg

url = os.environ["DATABASE_URL"]
for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://"):
    if url.startswith(prefix):
        url = "postgresql://" + url[len(prefix):]
        break

with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user")
        db, user = cur.fetchone()
        print(f"MIGRATION_TARGET\\t{db}\\t{user}")
"""


class OperationError(RuntimeError):
    """A destructive or verification operation failed or refused to proceed."""


def _reject_placeholder(label: str, value: str) -> None:
    if PLACEHOLDER_RE.search(value):
        raise OperationError(
            f"{label} looks like an unfilled documentation placeholder ({value!r}) "
            "— replace it with a real value before running this command."
        )


def _reject_reserved_db_name(label: str, name: str) -> None:
    if name in RESERVED_DB_NAMES:
        raise OperationError(
            f"{label} {name!r} is a reserved database ({sorted(RESERVED_DB_NAMES)}) — "
            "refusing to target it."
        )


def _validate_file_exists(label: str, path: Path) -> None:
    if not path.is_file():
        raise OperationError(f"{label} {path} does not exist or is not a regular file.")


# ---------------------------------------------------------------------------
# ComposeTarget — the complete, closed-over configuration tuple
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComposeTarget:
    """The complete, closed-over configuration tuple every command uses.

    Every operation in this module builds its `docker compose` invocation
    from this object alone — never from a default `.env`, default project
    discovery, or a Compose file list assembled anywhere else — so a
    drill/major-upgrade/production invocation can never silently share
    state with another one. Validation here is pure (no I/O beyond
    filesystem existence checks) and raises immediately, before any
    subprocess runs.
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
        if not PROJECT_NAME_RE.match(self.project):
            raise OperationError(
                f"--project {self.project!r} is not a valid Compose project name — must "
                "start with a lowercase letter or digit and contain only lowercase "
                "letters, digits, '-', and '_'."
            )
        if not self.db_user.strip():
            raise OperationError("--db-user must not be empty.")
        if not self.db_name.strip():
            raise OperationError("--db-name must not be empty.")

    def validate_files_exist(self) -> None:
        """Filesystem-only checks, run before any subprocess call."""
        _validate_file_exists("--env-file", self.env_file)
        for f in self.compose_files:
            _validate_file_exists("--compose-file", f)

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


def _format_argv(cmd: list[str]) -> str:
    """An unambiguous, cross-platform diagnostic rendering of an argument list.

    Deliberately not a copy-paste shell command: `" ".join(cmd)` is
    ambiguous for any argument containing a space or shell metacharacter,
    and a quoting scheme correct for one platform's shell (POSIX `shlex`,
    Windows `list2cmdline`) is wrong for the other. This is informational
    logging only, so a plain Python list repr — unambiguous on every
    platform — is preferable to a falsely-authoritative shell command.
    """
    return "argv: " + repr(cmd)


def run(
    cmd: list[str], *, input_text: str | None = None, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess from an explicit argument list — never a shell string."""
    print("+ " + _format_argv(cmd))
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

    def hard_ok(self) -> bool:
        return all(r.passed for r in self.results if r.hard)

    def print_summary(self, *, header: str = "results") -> bool:
        print()
        print(f"-- {header} --")
        for r in self.results:
            status = "PASS" if r.passed else ("WARN" if not r.hard else "FAIL")
            print(f"[{status}] {r.name}: {r.detail}")
        ok = self.hard_ok()
        print()
        print("OVERALL: " + ("PASS" if ok else "FAIL"))
        return ok


# ---------------------------------------------------------------------------
# Read-only checks reusable across commands
# ---------------------------------------------------------------------------


def check_roles(target: ComposeTarget, connect_user: str) -> tuple[Report, dict[str, bool]]:
    """Verify the six cluster-wide roles against the `postgres` maintenance database.

    Connects to `postgres`, never the application database — role
    definitions and membership are cluster-wide, and on an existing cluster
    with a damaged or missing application database, this must succeed
    without ever touching it. Purely read-only.
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
    ok, detail = _check(not missing, "all six roles exist", f"missing roles: {', '.join(missing)}")
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


def check_server_reachable(target: ComposeTarget) -> tuple[bool, str]:
    """pg_isready against the always-present `postgres` maintenance database.

    Never touches the application database — this must return a meaningful
    answer even when the application database is missing or corrupt.
    """
    result = compose_run(
        target,
        "exec",
        "-T",
        "db",
        "pg_isready",
        "-U",
        target.db_user,
        "-d",
        MAINTENANCE_DATABASE,
        capture=True,
    )
    detail = (result.stdout.strip() or result.stderr.strip()) or "no output"
    return result.returncode == 0, detail


def check_database_exists(target: ComposeTarget, db_name: str) -> tuple[bool, str]:
    """Whether db_name exists, checked via the postgres maintenance database.

    db_name is passed as a psql variable and substituted with the safe
    `:'dbname'` form (stdin, not `-c` — see `_grant_create_on_database`),
    never interpolated directly into SQL text.
    """
    sql = "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_database WHERE datname = :'dbname');"
    result = compose_run(
        target,
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        target.db_user,
        "-d",
        MAINTENANCE_DATABASE,
        "-t",
        "-A",
        "-v",
        f"dbname={db_name}",
        input_text=sql,
        capture=True,
    )
    if result.returncode != 0:
        return False, f"query failed: {result.stderr.strip()}"
    exists = result.stdout.strip() == "t"
    return exists, ("exists" if exists else "does not exist")


def render_compose_config(target: ComposeTarget) -> tuple[bool, dict[str, Any] | None, str]:
    """Render the merged Compose config as JSON, without ever printing it.

    `docker compose config` interpolates and can echo back secret-bearing
    environment values (POSTGRES_PASSWORD, MIGRATION_DATABASE_URL). This
    function parses the JSON into memory and returns it to the caller, which
    must only ever extract non-secret structural fields (service names,
    port lists, volume mounts) from it — never print the `environment` map
    or the raw JSON itself. A nonzero exit here (e.g. a missing required
    variable) surfaces only compose.yaml's own diagnostic message text
    (never a secret value, since Compose never echoes back an unset
    variable) via stderr.
    """
    # `docker compose config` omits services gated behind a non-active
    # profile by default — `migrate` carries `profiles: ["tools"]`
    # (compose.yaml), so without `--profile tools` here it never appears in
    # the rendered output at all, making a real "migrate exists" check
    # report a false "MISSING". Always requesting the profile is harmless
    # for callers that don't need `migrate`: it only adds to what's
    # rendered, never removes `db`.
    result = compose_run(target, "--profile", "tools", "config", "--format", "json", capture=True)
    if result.returncode != 0:
        return False, None, result.stderr.strip()
    try:
        config: dict[str, Any] = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return False, None, f"could not parse compose config output: {exc}"
    return True, config, ""


def check_compose_config(
    report: Report, target: ComposeTarget, *, require_migrate: bool
) -> dict[str, Any] | None:
    ok, config, error = render_compose_config(target)
    if not ok or config is None:
        report.add("compose configuration renders", False, error or "unknown error")
        return None
    services = set(config.get("services", {}).keys())
    report.add(
        "compose configuration renders",
        True,
        f"services: {', '.join(sorted(services)) or '(none)'}",
    )
    report.add(
        "'db' service defined", "db" in services, "present" if "db" in services else "MISSING"
    )
    if require_migrate:
        report.add(
            "'migrate' service defined",
            "migrate" in services,
            "present" if "migrate" in services else "MISSING",
        )
    db_service = config.get("services", {}).get("db", {})
    ports = db_service.get("ports") or []
    report.add(
        "db publishes no host port",
        not ports,
        "none published"
        if not ports
        else f"{len(ports)} port(s) published — confirm this is deliberate",
        hard=False,
    )
    return config


def verify_migration_target(
    target: ComposeTarget, expected_db: str, expected_user: str | None
) -> tuple[bool, str]:
    """Actively verify what database/user the `migrate` service's own configured
    DATABASE_URL actually connects as — not by parsing the dotenv file (this
    script never opens it), but by running a live connection through the
    exact service configuration a real migration invocation would use.
    Prints neither the URL nor any password; only the resulting database
    and user names, which are not secrets.
    """
    result = compose_run(
        target,
        "--profile",
        "tools",
        "run",
        "--rm",
        "migrate",
        "python",
        "-c",
        _TARGET_CHECK_SCRIPT,
        capture=True,
    )
    if result.returncode != 0:
        tail = result.stderr.strip()[-800:] if result.stderr else ""
        return False, f"could not connect via the migrate service's configured DATABASE_URL: {tail}"

    line = next(
        (ln for ln in reversed(result.stdout.splitlines()) if ln.startswith("MIGRATION_TARGET\t")),
        None,
    )
    if line is None:
        return False, "unexpected output from the migration-target check (no MIGRATION_TARGET line)"
    _, _, rest = line.partition("\t")
    actual_db, _, actual_user = rest.partition("\t")
    if actual_db != expected_db:
        return (
            False,
            f"MIGRATION_DATABASE_URL targets database {actual_db!r}, expected {expected_db!r}",
        )
    if expected_user is not None and actual_user != expected_user:
        return (
            False,
            f"MIGRATION_DATABASE_URL connects as {actual_user!r}, expected {expected_user!r}",
        )
    return True, f"confirmed: connects to {actual_db!r} as {actual_user!r}"


@dataclass
class ArchiveCheck:
    valid: bool
    cleanup_ok: bool
    has_alembic_version: bool | None
    detail: str


def validate_archive(target: ComposeTarget, dump_path: Path) -> ArchiveCheck:
    """Validate a pg_dump -Fc archive is readable, via `pg_restore --list`.

    This proves the archive is a well-formed, readable custom-format dump
    with inspectable contents — it does NOT prove semantic compatibility
    with any particular application/schema version. Copies the archive to a
    uniquely named temporary path inside the `db` container (pg_restore
    needs to run somewhere with the PostgreSQL toolchain installed), lists
    it, and always attempts to remove the temporary copy — if that removal
    fails, the check is reported as failed (not just a warning) and the
    file is left in place for inspection, per the "stop before database
    mutation if archive-preflight cleanup fails" contract. Never touches
    any actual database. Truncates listing/error output so this never turns
    into a bulk dump of archive contents.
    """
    container_tmp = f"/tmp/archive-check-{os.getpid()}-{uuid.uuid4().hex[:8]}.dump"
    cp = compose_run(target, "cp", str(dump_path), f"db:{container_tmp}")
    if cp.returncode != 0:
        return ArchiveCheck(
            False, True, None, "failed to copy the archive into the container for validation"
        )

    listing = compose_run(
        target, "exec", "-T", "db", "pg_restore", "--list", container_tmp, capture=True
    )
    valid = listing.returncode == 0
    has_alembic = ("alembic_version" in listing.stdout) if valid else None

    cleanup = compose_run(target, "exec", "-T", "db", "rm", "-f", container_tmp)
    cleanup_ok = cleanup.returncode == 0

    if not cleanup_ok:
        return ArchiveCheck(
            valid,
            False,
            has_alembic,
            f"temporary copy at {container_tmp} could not be removed — preserved for "
            "inspection; remove it by hand before proceeding"
            + ("" if valid else " (archive was also invalid)"),
        )
    if not valid:
        return ArchiveCheck(
            False, True, None, "pg_restore --list failed: " + listing.stderr.strip()[-800:]
        )
    return ArchiveCheck(
        True,
        True,
        has_alembic,
        "archive is a readable custom-format dump (pg_restore --list succeeded) — this "
        "proves readability, not compatibility with any particular schema/application version",
    )


def add_archive_checks(report: Report, target: ComposeTarget, dump_path: Path) -> bool:
    result = validate_archive(target, dump_path)
    report.add("dump archive validation", result.valid and result.cleanup_ok, result.detail)
    if result.valid:
        report.add(
            "dump archive references core.alembic_version",
            bool(result.has_alembic_version),
            "present" if result.has_alembic_version else "not found — unexpected for this schema",
            hard=False,
        )
    return result.valid and result.cleanup_ok


def _validate_check_query(query: str) -> tuple[bool, str]:
    """Lexical guard only — see `_psql_scalar_readonly` for the real enforcement."""
    stripped = query.strip()
    if not stripped:
        return False, "empty query"
    stripped = stripped.rstrip(";").strip()
    if not stripped:
        return False, "empty query"
    if ";" in stripped:
        return False, "only a single statement is allowed"
    if not stripped.lower().startswith("select"):
        return False, "must be a single SELECT statement"
    return True, stripped


def _psql_scalar_readonly(target: ComposeTarget, sql: str) -> tuple[bool, str]:
    """Run a single scalar query with PostgreSQL itself enforcing read-only execution.

    `default_transaction_read_only=on` is set for this one psql process via
    `PGOPTIONS`, scoped with `exec -e` rather than any persistent server
    setting — PostgreSQL, not this script's lexical `SELECT`-prefix check,
    is what actually rejects a side-effecting statement (e.g. one that
    calls a volatile function): the server raises "cannot execute ... in a
    read-only transaction" and psql exits nonzero, which this function
    reports as a failed check.
    """
    result = compose_run(
        target,
        "exec",
        "-T",
        "-e",
        "PGOPTIONS=-c default_transaction_read_only=on",
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
        return False, (
            result.stderr.strip() or "query failed (possibly rejected by read-only enforcement)"
        )
    return True, result.stdout.strip()


# ---------------------------------------------------------------------------
# verify-roles
# ---------------------------------------------------------------------------


def cmd_verify_roles(args: argparse.Namespace) -> int:
    target = ComposeTarget(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
        db_user=args.connect_user,
        db_name="(cluster-wide check — no application database used)",
    )
    target.validate_files_exist()
    announce("verify-roles", target)
    report, _ = check_roles(target, args.connect_user)
    return 0 if report.print_summary() else 1


# ---------------------------------------------------------------------------
# validate-archive
# ---------------------------------------------------------------------------


def cmd_validate_archive(args: argparse.Namespace) -> int:
    target = ComposeTarget(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
        db_user="postgres",
        db_name="(not applicable — archive validation does not connect to a database)",
    )
    target.validate_files_exist()
    dump_path = Path(args.dump_file)
    _validate_file_exists("--dump-file", dump_path)
    announce("validate-archive (read-only)", target, dump_file=str(dump_path))
    report = Report()
    ok = add_archive_checks(report, target, dump_path)
    report.print_summary()
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# preflight — standalone, read-only
# ---------------------------------------------------------------------------


def cmd_preflight(args: argparse.Namespace) -> int:
    target = ComposeTarget(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
        db_user=args.db_user,
        db_name=args.db_name,
    )
    target.validate_files_exist()
    dump_path = Path(args.dump_file) if args.dump_file else None
    if dump_path is not None:
        _validate_file_exists("--dump-file", dump_path)

    announce("preflight — no changes will be made", target, **{"for": args.for_})
    report = Report()

    require_migrate = args.for_ in ("restore-fresh", "bootstrap-roles")
    config = check_compose_config(report, target, require_migrate=require_migrate)
    if config is None:
        report.print_summary()
        print("\nStopping: compose configuration could not be rendered.")
        return 1

    reachable, detail = check_server_reachable(target)
    report.add("server reachable (postgres maintenance db)", reachable, detail)

    if reachable:
        exists, detail = check_database_exists(target, target.db_name)
        report.add(f"database {target.db_name!r} exists", exists, detail, hard=False)

        if args.for_ == "restore-existing":
            role_report, _ = check_roles(target, target.db_user)
            report.results.extend(role_report.results)
        elif args.for_ == "restore-fresh":
            ok, detail = verify_migration_target(target, target.db_name, target.db_user)
            report.add("migration URL targets expected database", ok, detail)
        elif args.for_ == "bootstrap-roles":
            if not args.temp_db_name:
                report.add("--temp-db-name provided", False, "required when --for bootstrap-roles")
            else:
                _reject_reserved_db_name("--temp-db-name", args.temp_db_name)
                temp_exists, detail = check_database_exists(target, args.temp_db_name)
                report.add(
                    f"temporary database {args.temp_db_name!r} exists yet",
                    not temp_exists,
                    "does not exist yet (expected before bootstrap-roles creates it)"
                    if not temp_exists
                    else "already exists — bootstrap-roles will refuse to reuse it",
                    hard=False,
                )

    if dump_path is not None:
        add_archive_checks(report, target, dump_path)

    planned = {
        "restore-fresh": (
            f"run migrations against {target.db_name!r} to bootstrap roles, verify roles, then "
            f"force-drop, recreate, re-grant, and restore into {target.db_name!r}"
        ),
        "restore-existing": (
            f"(roles already verified above) force-drop, recreate, re-grant, and restore into "
            f"{target.db_name!r}, without ever connecting to it first"
        ),
        "bootstrap-roles": (
            f"create {args.temp_db_name!r}, verify its migration target, run migrations "
            "against it, verify roles, then drop it again"
        ),
    }.get(args.for_, "(unspecified)")
    print(f"\nPlanned mutation sequence (not performed by this command): {planned}")
    print("No changes were made — `preflight` is strictly read-only.")

    return 0 if report.print_summary() else 1


# ---------------------------------------------------------------------------
# bootstrap-roles
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


def cmd_bootstrap_roles(args: argparse.Namespace) -> int:
    target = ComposeTarget(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
        db_user=args.connect_user,
        db_name=args.temp_db_name,
    )
    target.validate_files_exist()
    _reject_reserved_db_name("--temp-db-name", args.temp_db_name)
    if args.temp_db_name == args.protect_db_name:
        raise OperationError(
            "--temp-db-name must not equal --protect-db-name — bootstrap-roles is only "
            "for a database that is not the real recovery target."
        )

    # ---- Phase A: preflight (no mutation) ----
    if not args.confirm_env_targets_temp_db:
        raise OperationError(
            "refusing to continue: pass --confirm-env-targets-temp-db to acknowledge that "
            f"--env-file {args.env_file}'s MIGRATION_DATABASE_URL is intended to point at "
            f"the temporary database {args.temp_db_name!r}. This is checked ACTIVELY below, "
            "not just acknowledged — this flag alone does not skip that check."
        )

    announce("bootstrap-roles", target, protect_db_name=args.protect_db_name)

    report = Report()
    config = check_compose_config(report, target, require_migrate=True)
    if config is None:
        report.print_summary()
        return 1
    reachable, detail = check_server_reachable(target)
    report.add("server reachable (postgres maintenance db)", reachable, detail)
    temp_exists, detail = check_database_exists(target, args.temp_db_name)
    report.add(
        f"temporary database {args.temp_db_name!r} does not already exist",
        not temp_exists,
        "confirmed absent" if not temp_exists else "already exists — refusing to reuse it",
    )
    if not report.print_summary(header="preflight"):
        print("\nPreflight failed — nothing was created or migrated.", file=sys.stderr)
        return 1

    print("\nPREFLIGHT PASSED — beginning bootstrap of the temporary database.\n")

    # ---- Phase B: mutation ----
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
            f"createdb failed for {args.temp_db_name!r} — nothing else was touched.",
            file=sys.stderr,
        )
        return 1

    print("-- actively verifying the migration URL targets the temporary database --")
    target_ok, detail = verify_migration_target(target, args.temp_db_name, args.connect_user)
    print(f"    {detail}")
    if not target_ok:
        print(
            "\nMIGRATION_DATABASE_URL does NOT point at the temporary database — this is "
            "exactly the misconfiguration --confirm-env-targets-temp-db cannot catch by "
            "itself. Migrations were NOT run. Removing the temporary database we just created:",
            file=sys.stderr,
        )
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
                f"    cleanup of {args.temp_db_name!r} also failed — remove it by hand.",
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
    role_report, _ = check_roles(target, args.connect_user)
    roles_ok = role_report.print_summary(header="role verification")

    if not roles_ok:
        print(
            f"\nBOOTSTRAP FAILED: role verification did not pass after migrating. The "
            f"temporary database {args.temp_db_name!r} was left in place for inspection.",
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
            f"\nBOOTSTRAP SUCCEEDED — roles verified — but CLEANUP FAILED: the temporary "
            f"database {args.temp_db_name!r} could not be removed and remains. Operator "
            "intervention is required to drop it by hand. Exiting nonzero for that reason.",
            file=sys.stderr,
        )
        return 1

    print("\nbootstrap-roles: complete. All six roles verified; temporary database removed.")
    return 0


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


def cmd_restore(args: argparse.Namespace) -> int:
    target = ComposeTarget(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
        db_user=args.db_user,
        db_name=args.db_name,
    )
    target.validate_files_exist()
    _reject_reserved_db_name("--db-name", target.db_name)
    dump_path = Path(args.dump_file)
    _validate_file_exists("--dump-file", dump_path)

    # ---- Phase A, step 0: confirmation flags, before ANY docker invocation ----
    # Checked first and unconditionally — if either is absent, this function
    # returns before a single subprocess has run, so no database, role,
    # container, volume, or file can have changed.
    if not args.confirm_drop:
        raise OperationError(
            "refusing to continue: --confirm-drop is required. Nothing has been touched."
        )
    if not args.confirm_restore:
        raise OperationError(
            "refusing to continue: --confirm-restore is required. Nothing has been touched."
        )

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

    # ---- Phase A: preflight (no mutation) ----
    report = Report()
    require_migrate = args.mode == "fresh"
    config = check_compose_config(report, target, require_migrate=require_migrate)
    if config is None:
        report.print_summary(header="preflight")
        return 1

    reachable, detail = check_server_reachable(target)
    report.add("server reachable (postgres maintenance db)", reachable, detail)
    if not reachable:
        report.print_summary(header="preflight")
        print("\nPreflight failed — server unreachable. Nothing was touched.", file=sys.stderr)
        return 1

    archive_ok = add_archive_checks(report, target, dump_path)

    if args.mode == "existing":
        # Existing-cluster mode must never connect to the (possibly missing
        # or corrupt) target database before it has been recreated — only
        # to the always-present `postgres` maintenance database.
        role_report, _ = check_roles(target, target.db_user)
        report.results.extend(role_report.results)
    else:
        # Fresh-cluster mode: the target database is the one PostgreSQL's
        # own container init already created from POSTGRES_DB — not the
        # possibly-corrupt "existing" case — so actively confirming the
        # migration URL targets it is safe and required before Phase B's
        # migration bootstrap runs against it.
        target_ok, detail = verify_migration_target(target, target.db_name, target.db_user)
        report.add("migration URL targets expected database", target_ok, detail)

    if not report.print_summary(header="preflight"):
        print("\nPreflight failed — the target database was NOT touched.", file=sys.stderr)
        return 1
    if not archive_ok:
        # Belt and suspenders: hard_ok() above already covers this, but the
        # explicit branch keeps the "archive failure blocks mutation"
        # contract obvious to a future reader.
        return 1

    print("\nPREFLIGHT PASSED — beginning destructive recovery.\n")

    # ---- Phase B: mutation ----
    if args.mode == "fresh":
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
        role_report, _ = check_roles(target, target.db_user)
        if not role_report.print_summary(header="post-bootstrap role verification"):
            print(
                "\nRole verification failed immediately after bootstrap — stopping before "
                f"the drop/restore steps. Note: {target.db_name!r} was already migrated by "
                "the bootstrap step above; it has not been dropped or recreated.",
                file=sys.stderr,
            )
            return 1
        print()
    else:
        print(
            "Roles verified in preflight — proceeding without requiring Alembic to connect to the target database.\n"
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

    container_tmp = f"/tmp/restore-{os.getpid()}-{uuid.uuid4().hex[:8]}.dump"
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
            f"\nrestore succeeded WITH CLEANUP WARNING: the in-container copy at "
            f"{container_tmp} could not be removed and remains — remove it by hand.",
            file=sys.stderr,
        )
    else:
        print("\nrestore: complete.")

    print(
        "Before treating this deployment as authoritative:\n"
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
    target.validate_files_exist()
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

    print("-- operator-supplied checks (executed under database-enforced read-only mode) --")
    for query, expected in args.check or []:
        valid, stripped_or_reason = _validate_check_query(query)
        if not valid:
            report.add(f"check: {query}", False, f"refused — {stripped_or_reason}")
            continue
        ok, value = _psql_scalar_readonly(target, stripped_or_reason + ";")
        report.add(
            f"check: {query}",
            ok and value == expected,
            f"got {value!r}, expected {expected!r}"
            if ok
            else f"query failed or was rejected: {value}",
        )

    return 0 if report.print_summary() else 1


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


def _validate_backup_output(target: ComposeTarget, output: Path, *, overwrite: bool) -> None:
    if output.is_dir():
        raise OperationError(f"--output {output} is a directory, not a file path.")
    if output.exists() and not overwrite:
        raise OperationError(f"--output {output} already exists — pass --overwrite to replace it.")
    parent = output.parent if str(output.parent) else Path(".")
    if not parent.exists():
        raise OperationError(
            f"--output {output}'s parent directory {parent} does not exist — create it "
            "first; this script does not create directories implicitly."
        )
    protected = {target.env_file.resolve(), *(f.resolve() for f in target.compose_files)}
    resolved_output = output.resolve() if output.exists() else (parent.resolve() / output.name)
    if resolved_output in protected:
        raise OperationError(
            f"--output {output} resolves to a configuration file already in use — refusing."
        )


def cmd_backup(args: argparse.Namespace) -> int:
    target = ComposeTarget(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
        db_user=args.db_user,
        db_name=args.db_name,
    )
    target.validate_files_exist()
    output = Path(args.output)
    _validate_backup_output(target, output, overwrite=args.overwrite)

    announce("backup", target, output=str(output))

    reachable, detail = check_server_reachable(target)
    if not reachable:
        print(f"Server unreachable — nothing was touched. ({detail})", file=sys.stderr)
        return 1

    container_tmp = f"/tmp/{target.db_name}-{os.getpid()}-{uuid.uuid4().hex[:8]}.dump"
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
            f"\nbackup succeeded WITH CLEANUP WARNING: {output} was written, but the "
            f"in-container copy at {container_tmp} could not be removed and remains — "
            "remove it by hand.",
            file=sys.stderr,
        )
    else:
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
    if args.project.strip().lower() in DEFAULT_LIKE_PROJECT_NAMES:
        raise OperationError(
            f"--project {args.project!r} looks like a default/generic placeholder, not a "
            "specific disposable project — refusing to tear it down."
        )
    target = ComposeTarget(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
        db_user="(not applicable)",
        db_name="(not applicable)",
    )
    target.validate_files_exist()
    if not args.confirm_teardown:
        raise OperationError(
            "refusing to continue: pass --confirm-teardown to run `down -v`. Nothing was touched."
        )

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

    p_validate = sub.add_parser(
        "validate-archive",
        help="Validate a pg_dump -Fc archive is readable, without restoring it (read-only).",
    )
    _add_target_args(p_validate, with_db=False)
    p_validate.add_argument(
        "--dump-file", required=True, help="Host path to the archive to validate."
    )
    p_validate.set_defaults(func=cmd_validate_archive)

    p_preflight = sub.add_parser(
        "preflight",
        help="Run the same read-only checks `restore`/`bootstrap-roles` run before mutating, standalone.",
    )
    _add_target_args(p_preflight)
    p_preflight.add_argument(
        "--for",
        dest="for_",
        required=True,
        choices=["restore-fresh", "restore-existing", "bootstrap-roles"],
        help="Which workflow's preflight checks to run.",
    )
    p_preflight.add_argument(
        "--dump-file", default=None, help="If supplied, also validates this archive."
    )
    p_preflight.add_argument(
        "--temp-db-name", default=None, help="Required when --for bootstrap-roles."
    )
    p_preflight.set_defaults(func=cmd_preflight)

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
        help="Required acknowledgment that --env-file's MIGRATION_DATABASE_URL is intended "
        "to point at --temp-db-name. This is checked ACTIVELY before migrations run — this "
        "flag records operator intent, it does not replace that check.",
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
        help="An additional read-only SELECT check and its expected scalar result, executed "
        "under database-enforced read-only mode (default_transaction_read_only=on) — "
        "PostgreSQL itself rejects any side-effecting statement, not just this script's "
        "lexical SELECT-prefix check. Repeatable. "
        'Example: --check "SELECT count(*) FROM core.worlds" "0"',
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
