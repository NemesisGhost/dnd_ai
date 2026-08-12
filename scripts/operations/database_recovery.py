"""Production database recovery operations for the self-hosted Docker Compose topology.

Consolidates the destructive Compose/psql sequences documented in
docs/operations/DATABASE_RECOVERY.md (backup, role bootstrap, restore,
verification, teardown) into one auditable, cross-platform tool, so the
exact flags, environment file, project name, and database identity used are
identical regardless of which shell invokes it.

Safety model — three levels, not a single "read-only" claim:

  static           Argument/placeholder/path validation and Compose
                    configuration rendering. No container needs to be
                    running; nothing is created.

  docker-ephemeral  May run `docker compose exec`/`cp` against an ALREADY
                    RUNNING `db` container (no new container created), and
                    may create a genuinely new one-off container via
                    `docker compose run --rm` for the migration-target
                    check (which requires the `migrate` image to already
                    exist — see `check_migrate_image_present`; this script
                    never lets that check silently trigger a build). None
                    of this creates, drops, or alters any PostgreSQL
                    database, role, or volume.

  destructive       Force-drops/recreates a database, runs real migrations,
                    restores a dump, or `down -v`s a project. Always gated
                    behind an explicit `--confirm-*` flag, checked before
                    any subprocess — Docker-ephemeral or otherwise — runs.

`verify` performs no PostgreSQL state mutation by default: every one of its
checks, including the Alembic-revision check (`alembic current`, which only
reads `core.alembic_version`), is non-mutating. Its one destructive
exception — an actual `alembic upgrade head` run — only executes when
`--confirm-migrate` is explicitly passed, checked immediately before that
one subprocess; without it, `verify` never runs migrations, and nothing in
its output claims otherwise.

`restore` and `bootstrap-roles` run their static and docker-ephemeral
checks (their "preflight") before doing anything destructive, and refuse to
continue — without touching the target application database, role, or
volume — if any of those checks fails. That is the guarantee this script
makes: not "nothing happens," but "no PostgreSQL state changes, and no
destructive step runs, until every preflight check has passed." The
standalone `preflight` command exposes the same static/docker-ephemeral
checks on their own, for inspection independent of any mutation — see its
own docstring/help for exactly which checks run at which `--level`.

This script never reads or prints POSTGRES_PASSWORD, MIGRATION_DATABASE_URL,
or any other credential — it only ever passes `--env-file <path>` through to
`docker compose`, which resolves secrets itself, and the one place it reads
a database connection's identity (`verify_migration_target`) prints only the
resulting database/user names, never the URL. `docker compose config`'s
JSON output is parsed in memory and never printed in full — callers only
ever extract and display non-secret structural fields (service names, port
bindings). Every subprocess is invoked as an argument list (never
`shell=True`, never a string re-parsed by a shell), and every configurable
SQL identifier this script builds itself (database names) is passed through
psql's `-v`/`:'var'`/`\\gexec` safe-substitution mechanism rather than
string-interpolated into SQL text — see `_grant_create_on_database`'s
docstring for why.
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

# Host addresses that mean "every interface," not "this machine only" — a
# published port bound to one of these is reachable from other machines on
# the network, not just localhost.
ALL_INTERFACES_HOSTS = frozenset({"0.0.0.0", "::", ""})


# compose.yaml's `migrate` service has no explicit top-level `image:` — only
# `build:` — so Compose derives its image tag as `<project>-migrate:latest`
# (confirmed against installed Compose v5.3.1: `docker compose config
# --images` and the "naming to docker.io/library/<project>-migrate:latest"
# line printed by an actual build both match this pattern). Computing it
# directly, rather than parsing it out of rendered JSON (which does not
# include a synthesized `image` key when only `build:` is set), is simpler
# and does not depend on that JSON-shape assumption holding across versions.
def _migrate_image_ref(project: str) -> str:
    return f"{project}-migrate:latest"


# Runs a small psycopg-based check inside a one-off `migrate` service
# container, so the database it actually connects to is proven by a live
# connection through the exact configuration a real migration run would use
# — never by re-parsing the dotenv file (which this script never opens) and
# never by printing the connection URL. Only the resulting database and
# user names are printed, tab-separated on their own line, so the caller
# can find them even alongside `docker compose run`'s own
# container-lifecycle chatter. This creates a genuinely new, one-off
# container (`run --rm`) — see `check_migrate_image_present`, always called
# first, for why that never silently triggers a build.
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


def _validate_compose_selection(
    project: str, env_file: Path, compose_files: tuple[Path, ...]
) -> None:
    _reject_placeholder("--project", project)
    _reject_placeholder("--env-file", str(env_file))
    for f in compose_files:
        _reject_placeholder("--compose-file", str(f))
    if not compose_files:
        raise OperationError("at least one --compose-file is required.")
    if not PROJECT_NAME_RE.match(project):
        raise OperationError(
            f"--project {project!r} is not a valid Compose project name — must start with "
            "a lowercase letter or digit and contain only lowercase letters, digits, '-', "
            "and '_'."
        )


# ---------------------------------------------------------------------------
# Compose selection / target — the closed-over configuration tuples
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComposeSelection:
    """Project/env-file/Compose-files only — no database identity.

    Used by commands that never connect to a specific application database
    (`validate-archive`, `teardown`, and `verify-roles`'s Compose identity —
    which supplies its own `--connect-user` separately rather than through
    a `db_user` field here). Every operation in this module builds its
    `docker compose` invocation from an instance of this (or the subclass
    below) alone — never from a default `.env`, default project discovery,
    or a Compose file list assembled anywhere else — so a drill/major-
    upgrade/production invocation can never silently share state with
    another one. Validation here is pure (no I/O beyond filesystem
    existence checks) and raises immediately, before any subprocess runs.
    """

    project: str
    env_file: Path
    compose_files: tuple[Path, ...]

    def __post_init__(self) -> None:
        _validate_compose_selection(self.project, self.env_file, self.compose_files)

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
        )


@dataclass(frozen=True)
class ComposeTarget(ComposeSelection):
    """A `ComposeSelection` plus a real database user/name this command connects to or mutates."""

    db_user: str
    db_name: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _reject_placeholder("--db-user", self.db_user)
        _reject_placeholder("--db-name", self.db_name)
        if not self.db_user.strip():
            raise OperationError("--db-user must not be empty.")
        if not self.db_name.strip():
            raise OperationError("--db-name must not be empty.")

    def describe(self) -> str:
        return (
            super().describe()
            + f"    db user:       {self.db_user}\n"
            + f"    db name:       {self.db_name}\n"
        )


def announce(operation: str, target: ComposeSelection, **extra: str) -> None:
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
    target: ComposeSelection, *extra_args: str, input_text: str | None = None, capture: bool = False
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
# static checks — no running container required
# ---------------------------------------------------------------------------


def render_compose_config(target: ComposeSelection) -> tuple[bool, dict[str, Any] | None, str]:
    """Render the merged Compose config as JSON, without ever printing it.

    Static: renders configuration text, does not start or require a running
    container. `docker compose config` interpolates and can echo back
    secret-bearing environment values (POSTGRES_PASSWORD,
    MIGRATION_DATABASE_URL). This function parses the JSON into memory and
    returns it to the caller, which must only ever extract non-secret
    structural fields (service names, port lists, volume mounts) from it —
    never print the `environment` map or the raw JSON itself. A nonzero
    exit here (e.g. a missing required variable) surfaces only
    compose.yaml's own diagnostic message text (never a secret value, since
    Compose never echoes back an unset variable) via stderr.
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
    report: Report,
    target: ComposeSelection,
    *,
    require_migrate: bool,
    allow_published_db_port: bool,
) -> dict[str, Any] | None:
    """Static: render config and check structural fields. No container required."""
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
    if not ports:
        report.add("db publishes no host port", True, "none published")
    else:
        bindings = []
        publicly_bound = False
        for p in ports:
            host_ip = p.get("host_ip") or "0.0.0.0"
            bindings.append(f"{host_ip}:{p.get('published', '?')}->{p.get('target', '?')}")
            if host_ip in ALL_INTERFACES_HOSTS:
                publicly_bound = True
        detail = ", ".join(bindings)
        if allow_published_db_port:
            note = (
                " — WARNING: bound to all interfaces, not loopback-only" if publicly_bound else ""
            )
            report.add(
                "db publishes no host port",
                True,
                f"{len(ports)} port(s) published, acknowledged via --allow-published-db-port: {detail}{note}",
                hard=False,
            )
            print(f"    [port exposure acknowledged] {detail}{note}")
        else:
            report.add(
                "db publishes no host port",
                False,
                f"{len(ports)} port(s) published on 'db' ({detail}) — refusing by default; "
                "pass --allow-published-db-port to acknowledge this deliberately",
            )
    return config


def check_migrate_image_present(report: Report, project: str) -> bool:
    """Static-adjacent: `docker image inspect` a locally cached image tag by name.

    Does not start, create, or remove any container — it only asks the
    local Docker daemon whether an image reference already exists in its
    cache. `docker compose run --rm migrate ...` builds the `migrate`
    image implicitly if it is missing (confirmed live against installed
    Compose v5.3.1: no `--no-build`/equivalent flag exists in this version
    to suppress that), so this check exists specifically to let this
    script refuse to trigger that build rather than let it happen as a
    side effect of a migration-target check.
    """
    image = _migrate_image_ref(project)
    result = run(["docker", "image", "inspect", image, "--format", "{{.Id}}"], capture=True)
    present = result.returncode == 0
    report.add(
        "migrate image already built",
        present,
        f"{image} present locally"
        if present
        else f"{image} not found locally — build it deliberately first, e.g. "
        f"`docker compose --env-file <env-file> -p {project} -f <compose files> "
        "--profile tools build migrate` — this script will not trigger that build for you.",
    )
    return present


# ---------------------------------------------------------------------------
# docker-ephemeral checks — require an already-running `db` container
# (`exec`/`cp`), or create a new one-off container (`run --rm`, migration-
# target check only, always gated by check_migrate_image_present above)
# ---------------------------------------------------------------------------


def check_roles(target: ComposeSelection, connect_user: str) -> tuple[Report, dict[str, bool]]:
    """Verify the six cluster-wide roles against the `postgres` maintenance database.

    Docker-ephemeral: runs `exec` against the already-running `db`
    container (creates no new container). Connects to `postgres`, never
    the application database — role definitions and membership are
    cluster-wide, and on an existing cluster with a damaged or missing
    application database, this must succeed without ever touching it. Only
    issues SQL `SELECT`s — no PostgreSQL state is modified.
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

    Docker-ephemeral: `exec` against the already-running `db` container.
    Never touches the application database — this must return a
    meaningful answer even when the application database is missing or
    corrupt.
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


def check_database_exists(target: ComposeTarget, db_name: str) -> tuple[bool | None, str]:
    """Whether db_name exists, checked via the postgres maintenance database.

    Docker-ephemeral: `exec` against the already-running `db` container.
    db_name is passed as a psql variable and substituted with the safe
    `:'dbname'` form (stdin, not `-c` — see `_grant_create_on_database`),
    never interpolated directly into SQL text.

    Returns a tri-state: `(True, "exists")`, `(False, "does not exist")`, or
    `(None, "query failed: ...")`. Callers MUST treat `None` as a distinct,
    unknown outcome — a failed existence query is not evidence the database
    is absent, and collapsing it into `False` previously let a caller in
    this script interpret "the query failed" as "safe to proceed."
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
        return None, f"query failed: {result.stderr.strip()}"
    exists = result.stdout.strip() == "t"
    return exists, ("exists" if exists else "does not exist")


def verify_migration_target(
    target: ComposeTarget, expected_db: str, expected_user: str | None
) -> tuple[bool, str]:
    """Actively verify what database/user the `migrate` service's own configured
    DATABASE_URL actually connects as — not by parsing the dotenv file (this
    script never opens it), but by running a live connection through the
    exact service configuration a real migration invocation would use.

    Docker-ephemeral: creates a genuinely new, one-off container
    (`run --rm`) — unlike every other check in this section, which reuses
    the already-running `db` container via `exec`. Callers MUST call
    `check_migrate_image_present` first and skip this call if that fails,
    so a missing image is reported clearly rather than silently built.
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


# pg_dump's custom format (`-Fc`) begins with the 5-byte magic string
# "PGDMP" (PostgreSQL's pg_backup_archiver.c WriteHead), followed by a
# version byte triple and flags. Plain-text (`-Fp`) dumps are SQL text and
# don't start this way; tar-format (`-Ft`) dumps are POSIX tar archives
# whose outer file starts with a filename field, not this signature —
# `pg_restore --list` can read both of those too, so it alone cannot prove
# custom format. Reading these bytes locally, before any Compose/Docker
# call, is a reliable, host-side way to confirm the format this tool
# claims to require.
_PG_CUSTOM_FORMAT_MAGIC = b"PGDMP"


def _is_pg_custom_format_archive(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(len(_PG_CUSTOM_FORMAT_MAGIC)) == _PG_CUSTOM_FORMAT_MAGIC
    except OSError:
        return False


@dataclass
class ArchiveCheck:
    valid: bool
    cleanup_ok: bool
    has_alembic_version: bool | None
    detail: str


def validate_archive(target: ComposeSelection, dump_path: Path) -> ArchiveCheck:
    """Confirm dump_path is a readable PostgreSQL custom-format (`pg_dump -Fc`) archive.

    Two checks, in order:

    1. **Static, local, host-side**: the file must begin with the 5-byte
       `PGDMP` signature (`_is_pg_custom_format_archive`) that `pg_dump -Fc`
       always writes. `pg_restore --list` succeeding is NOT by itself proof
       of custom format — it can also read tar-format (`-Ft`) archives — so
       this script checks the signature itself rather than inferring format
       from what pg_restore happens to accept. No Docker operation runs for
       this step; a file that fails it is rejected immediately.
    2. **Docker-ephemeral, not database-connecting**: requires the `db`
       container to already be running (this only ever needs the PostgreSQL
       toolchain installed there, not a live database), and temporarily
       modifies that container's filesystem — it copies the archive to a
       uniquely named temporary path inside it, lists it with
       `pg_restore --list`, and always attempts to remove the temporary
       copy afterward. It never connects to PostgreSQL and never creates,
       drops, or restores into any database.

    Together these prove the archive is specifically a well-formed,
    readable custom-format dump with inspectable contents — not merely
    something pg_restore happens to be able to read — and still NOT
    semantic compatibility with any particular application/schema version.
    If removing the temporary copy fails, the check is reported as failed
    (not just a warning) and the file is left in place for inspection, so a
    caller stops before any database mutation rather than proceeding with a
    stray, uninspected file left behind. Truncates listing/error output so
    this never turns into a bulk dump of archive contents.
    """
    if not _is_pg_custom_format_archive(dump_path):
        return ArchiveCheck(
            False,
            True,
            None,
            f"{dump_path} does not begin with the PostgreSQL custom-format signature "
            "('PGDMP') — this tool accepts only pg_dump -Fc (custom-format) archives, the "
            "format 'backup' always produces. Plain-text (-Fp) and tar-format (-Ft) dumps "
            "are rejected even though pg_restore --list can read some of them. No Docker "
            "operation was performed for this check.",
        )

    container_tmp = f"/tmp/archive-check-{os.getpid()}-{uuid.uuid4().hex[:8]}.dump"
    cp = compose_run(target, "cp", str(dump_path), f"db:{container_tmp}")
    if cp.returncode != 0:
        return ArchiveCheck(
            False,
            True,
            None,
            "failed to copy the archive into the container for validation (is the 'db' "
            "container running?)",
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
            f"temporary copy at {container_tmp} inside the 'db' container could not be "
            "removed — preserved for inspection; remove it by hand before proceeding"
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
        "archive begins with the PostgreSQL custom-format signature ('PGDMP') and "
        "pg_restore --list succeeded — this proves the archive is a well-formed, readable "
        "custom-format dump with inspectable contents, not compatibility with any "
        "particular schema/application version",
    )


def add_archive_checks(report: Report, target: ComposeSelection, dump_path: Path) -> bool:
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
    target = ComposeSelection(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
    )
    target.validate_files_exist()
    announce("verify-roles (docker-ephemeral: exec against the running 'db' container)", target)
    report, _ = check_roles(target, args.connect_user)
    return 0 if report.print_summary() else 1


# ---------------------------------------------------------------------------
# validate-archive
# ---------------------------------------------------------------------------


def cmd_validate_archive(args: argparse.Namespace) -> int:
    target = ComposeSelection(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
    )
    target.validate_files_exist()
    dump_path = Path(args.dump_file)
    _validate_file_exists("--dump-file", dump_path)
    announce(
        "validate-archive (static: confirms the PostgreSQL custom-format 'PGDMP' signature "
        "locally first, rejecting anything else; then docker-ephemeral: requires the running "
        "'db' container, does not connect to PostgreSQL, temporarily copies the archive into "
        "that container's filesystem)",
        target,
        dump_file=str(dump_path),
    )
    report = Report()
    ok = add_archive_checks(report, target, dump_path)
    report.print_summary()
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# preflight — standalone static/docker-ephemeral checks
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
    if args.for_ == "bootstrap-roles" and args.temp_db_name:
        _reject_reserved_db_name("--temp-db-name", args.temp_db_name)

    announce(
        f"preflight — level={args.level} (static config/file checks"
        + (
            "; PostgreSQL/Docker state is unaffected either way"
            if args.level == "static"
            else ", plus docker-ephemeral checks against the running 'db' container/a one-off "
            "migrate container — no PostgreSQL database/role/volume is created, dropped, or "
            "modified by any of them"
        )
        + ")",
        target,
        **{"for": args.for_},
    )

    report = Report()
    require_migrate = args.for_ in ("restore-fresh", "bootstrap-roles")
    config = check_compose_config(
        report,
        target,
        require_migrate=require_migrate,
        allow_published_db_port=args.allow_published_db_port,
    )
    if config is None:
        report.print_summary(header=f"{args.level} preflight")
        print("\nStopping: compose configuration could not be rendered.")
        return 1

    if args.level == "static":
        print(
            "\n--level static requested: stopping after configuration checks. No container "
            "was required to be running and none was inspected. Run --level docker (the "
            "default) to also check server reachability, roles, migration target, and "
            "archive readability against a running 'db' container."
        )
        return 0 if report.print_summary(header="static preflight") else 1

    print(
        "\nProceeding to docker-ephemeral checks (require the 'db' container to already be "
        "running; create no PostgreSQL database/role/volume): server reachability, target "
        "database existence, "
        + {
            "restore-existing": "role verification",
            "restore-fresh": "an active migration-target connection check",
            "bootstrap-roles": "temporary-database-name availability",
        }[args.for_]
        + (", and archive validation" if dump_path is not None else "")
        + ".\n"
    )

    reachable, detail = check_server_reachable(target)
    report.add("server reachable (postgres maintenance db)", reachable, detail)

    if reachable:
        exists, detail = check_database_exists(target, target.db_name)
        report.add(f"database {target.db_name!r} exists", bool(exists), detail, hard=False)

        if args.for_ == "restore-existing":
            role_report, _ = check_roles(target, target.db_user)
            report.results.extend(role_report.results)
        elif args.for_ == "restore-fresh":
            if check_migrate_image_present(report, target.project):
                ok, detail = verify_migration_target(target, target.db_name, target.db_user)
                report.add("migration URL targets expected database", ok, detail)
        elif args.for_ == "bootstrap-roles":
            if not args.temp_db_name:
                report.add("--temp-db-name provided", False, "required when --for bootstrap-roles")
            else:
                temp_exists, temp_detail = check_database_exists(target, args.temp_db_name)
                if temp_exists is None:
                    # Query failure is not evidence of absence — a hard
                    # failure here, distinct from "already exists", so a
                    # caller never mistakes "we couldn't tell" for "safe to
                    # proceed."
                    report.add(
                        f"temporary database {args.temp_db_name!r} does not already exist",
                        False,
                        f"could not determine — {temp_detail}",
                    )
                else:
                    report.add(
                        f"temporary database {args.temp_db_name!r} does not already exist",
                        not temp_exists,
                        "confirmed absent (expected before bootstrap-roles creates it)"
                        if not temp_exists
                        else "already exists — bootstrap-roles will refuse to reuse it",
                    )
                print(
                    "    Note: bootstrap-roles' ACTIVE migration-target verification "
                    "(confirming MIGRATION_DATABASE_URL really points at the temporary "
                    "database) can only run after bootstrap-roles itself creates that "
                    "database — it does not exist yet, so this command cannot perform that "
                    "check. This is a deliberately incomplete subset of what bootstrap-roles "
                    "itself checks, not the same battery run early."
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
            f"create {args.temp_db_name!r}, ACTIVELY verify its migration target only once it "
            "exists (not performed by this command), run migrations against it, verify roles, "
            "then drop it again"
        ),
    }.get(args.for_, "(unspecified)")
    print(f"\nPlanned destructive sequence (not performed by this command): {planned}")
    print(
        "This command performed no PostgreSQL database/role/volume mutation. It did run "
        "Docker-side checks above (exec against the running 'db' container, and, for "
        "restore-fresh, a one-off migrate container) — see the safety model in this script's "
        "module docstring / --help for exactly what that does and does not mean."
    )

    return 0 if report.print_summary(header="docker preflight") else 1


# ---------------------------------------------------------------------------
# bootstrap-roles
# ---------------------------------------------------------------------------


def _grant_create_on_database(
    target: ComposeTarget, connect_user: str, db_name: str
) -> subprocess.CompletedProcess[str]:
    """Reissue GRANT CREATE ON DATABASE ... TO migration_owner.

    dropdb/createdb discards the database-level ACL 001_bootstrap set up
    (docs/operations/DATABASE_RECOVERY.md, "What dropping and recreating
    the database loses"). db_name is passed as a psql variable and
    substituted with the safe-quoting `:'dbname'` form, then run through
    `format('%I', ...)` server-side to produce a properly quoted identifier
    and re-executed via `\\gexec` — this is safe regardless of what
    characters db_name contains, unlike interpolating it directly into a
    GRANT statement string. The SQL is piped on stdin rather than passed
    via `-c`, because `:'var'` substitution is a feature of psql's
    query-scanning input stream, not of `-c` arguments (confirmed: `-c`
    sends the text close to verbatim and `:'dbname'` reaches the server as
    a literal syntax error).
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

    # ---- preflight: static + docker-ephemeral checks, no PostgreSQL mutation ----
    if not args.confirm_env_targets_temp_db:
        raise OperationError(
            "refusing to continue: pass --confirm-env-targets-temp-db to acknowledge that "
            f"--env-file {args.env_file}'s MIGRATION_DATABASE_URL is intended to point at "
            f"the temporary database {args.temp_db_name!r}. This is checked ACTIVELY below, "
            "once that database exists — this flag alone does not skip that check."
        )

    announce("bootstrap-roles", target, protect_db_name=args.protect_db_name)

    report = Report()
    config = check_compose_config(
        report, target, require_migrate=True, allow_published_db_port=args.allow_published_db_port
    )
    if config is None:
        report.print_summary(header="preflight")
        return 1
    reachable, detail = check_server_reachable(target)
    report.add("server reachable (postgres maintenance db)", reachable, detail)
    temp_exists, temp_detail = check_database_exists(target, args.temp_db_name)
    if temp_exists is None:
        # Query failure is not evidence of absence — report it as its own
        # hard failure rather than letting "not temp_exists" evaluate True
        # on a failed query and wrongly let bootstrap proceed.
        report.add(
            f"temporary database {args.temp_db_name!r} does not already exist",
            False,
            f"could not determine — {temp_detail}",
        )
    else:
        report.add(
            f"temporary database {args.temp_db_name!r} does not already exist",
            not temp_exists,
            "confirmed absent" if not temp_exists else "already exists — refusing to reuse it",
        )
    image_present = check_migrate_image_present(report, target.project)
    if not report.print_summary(header="preflight"):
        print(
            "\nPreflight failed — no database, role, or file was created or migrated (the "
            "docker-ephemeral checks above did run against the already-running 'db' container, "
            "but none of them mutate PostgreSQL state).",
            file=sys.stderr,
        )
        return 1

    print("\nPREFLIGHT PASSED — beginning bootstrap of the temporary database.\n")

    # ---- destructive: creates and later drops a temporary database ----
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
    if not image_present:
        print(
            f"\nThe migrate image was not present at preflight time — refusing to let the "
            f"migration-target check trigger an implicit build. Removing the temporary "
            f"database {args.temp_db_name!r} we just created:",
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

    # ---- confirmation flags, before ANY docker invocation ----
    # Checked first and unconditionally — if either is absent, this function
    # returns before a single subprocess has run, so no database, role,
    # container, volume, or file can have changed, and no ephemeral Docker
    # resource (not even a config render) has been created either.
    if not args.confirm_drop:
        raise OperationError(
            "refusing to continue: --confirm-drop is required. No subprocess has run — "
            "nothing has been touched."
        )
    if not args.confirm_restore:
        raise OperationError(
            "refusing to continue: --confirm-restore is required. No subprocess has run — "
            "nothing has been touched."
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

    # ---- preflight: static + docker-ephemeral checks, no PostgreSQL mutation ----
    report = Report()
    require_migrate = args.mode == "fresh"
    config = check_compose_config(
        report,
        target,
        require_migrate=require_migrate,
        allow_published_db_port=args.allow_published_db_port,
    )
    if config is None:
        report.print_summary(header="preflight")
        return 1

    reachable, detail = check_server_reachable(target)
    report.add("server reachable (postgres maintenance db)", reachable, detail)
    if not reachable:
        report.print_summary(header="preflight")
        print(
            "\nPreflight failed — server unreachable. The target application database was "
            "not touched.",
            file=sys.stderr,
        )
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
        # migration URL targets it is safe and required before the
        # destructive phase's migration bootstrap runs against it.
        if check_migrate_image_present(report, target.project):
            target_ok, detail = verify_migration_target(target, target.db_name, target.db_user)
            report.add("migration URL targets expected database", target_ok, detail)

    if not report.print_summary(header="preflight"):
        print(
            "\nPreflight failed — the target application database was NOT touched (the "
            "docker-ephemeral checks above did run against the running 'db' container, but "
            "none of them create, drop, or modify a PostgreSQL database).",
            file=sys.stderr,
        )
        return 1
    if not archive_ok:
        # Belt and suspenders: hard_ok() above already covers this, but the
        # explicit branch keeps the "archive failure blocks the destructive
        # phase" contract obvious to a future reader.
        return 1

    print("\nPREFLIGHT PASSED — beginning destructive recovery.\n")

    # ---- destructive: drop/recreate/restore, and (fresh mode) an actual migration run ----
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

    print(
        "-- Alembic revision (non-mutating: `alembic current` only reads core.alembic_version) --"
    )
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

    # Real migration execution is DESTRUCTIVE — it can change schema/data —
    # so, unlike the rest of this non-mutating acceptance battery, it never
    # runs unless explicitly confirmed. Checked immediately before the one
    # subprocess it gates, consistent with every other --confirm-* flag in
    # this script.
    if args.confirm_migrate:
        print(
            "-- migration machinery (DESTRUCTIVE: --confirm-migrate passed — running a real "
            "`alembic upgrade head` against this database) --"
        )
        migrate = compose_run(target, "--profile", "tools", "run", "--rm", "migrate")
        report.add(
            "alembic upgrade head (--confirm-migrate)",
            migrate.returncode == 0,
            "ran cleanly (this proves migration machinery works end-to-end; it does not by "
            "itself prove CREATE ON DATABASE — the privilege check above already did that "
            "directly)"
            if migrate.returncode == 0
            else "failed — this was a real migration attempt against this database, not a "
            "dry run; inspect its output above before retrying",
        )
    else:
        print(
            "-- migration machinery: skipped (verify never runs migrations by default; pass "
            "--confirm-migrate to also run a real, DESTRUCTIVE `alembic upgrade head` as an "
            "end-to-end smoke test) --"
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
        print(
            f"Server unreachable — no dump was taken, nothing was mutated. ({detail})",
            file=sys.stderr,
        )
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
        "roles. See docs/operations/DATABASE_RECOVERY.md, "
        '"What a pg_dump backup does not cover."'
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
    target = ComposeSelection(
        project=args.project,
        env_file=Path(args.env_file),
        compose_files=tuple(Path(f) for f in args.compose_file),
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


def _add_port_flag(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--allow-published-db-port",
        action="store_true",
        help="Acknowledge that the rendered Compose configuration publishes a host port for "
        "'db' (e.g. via compose.override.yaml). Without this flag, any published port fails "
        "preflight by default — the base self-hosted topology (compose.yaml alone) publishes "
        "none. A binding to all interfaces (0.0.0.0/::), not just loopback, is still reported "
        "loudly even when acknowledged.",
    )


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
        help="Check the six cluster-wide roles via the postgres maintenance database "
        "(docker-ephemeral: exec against the running 'db' container).",
    )
    _add_target_args(p_roles, with_db=False)
    p_roles.add_argument(
        "--connect-user", default="postgres", help="User to connect as (default: postgres)."
    )
    p_roles.set_defaults(func=cmd_verify_roles)

    p_validate = sub.add_parser(
        "validate-archive",
        help="Confirm a file is a readable pg_dump -Fc (custom-format) archive, without "
        "restoring it — rejects plain-text/tar-format archives even though pg_restore --list "
        "can read some of those too (static: local 'PGDMP' signature check first; "
        "docker-ephemeral: requires the running 'db' container; never connects to PostgreSQL).",
    )
    _add_target_args(p_validate, with_db=False)
    p_validate.add_argument(
        "--dump-file", required=True, help="Host path to the archive to validate."
    )
    p_validate.set_defaults(func=cmd_validate_archive)

    p_preflight = sub.add_parser(
        "preflight",
        help="Run the static and docker-ephemeral checks restore/bootstrap-roles run before "
        "their destructive phase, standalone. For --for bootstrap-roles this is necessarily "
        "an incomplete subset (its active migration-target check needs a database that "
        "doesn't exist until bootstrap-roles itself creates it) — not the same checks run early.",
    )
    _add_target_args(p_preflight)
    _add_port_flag(p_preflight)
    p_preflight.add_argument(
        "--for",
        dest="for_",
        required=True,
        choices=["restore-fresh", "restore-existing", "bootstrap-roles"],
        help="Which workflow's preflight checks to run.",
    )
    p_preflight.add_argument(
        "--level",
        choices=["static", "docker"],
        default="docker",
        help="static: argument/file/Compose-config checks only, no container needs to be "
        "running. docker (default): also runs docker-ephemeral checks against the running "
        "'db' container (and, for restore-fresh, a one-off migrate container) — reachability, "
        "roles/migration-target, archive readability. Neither level creates, drops, or "
        "modifies a PostgreSQL database, role, or volume.",
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
    _add_port_flag(p_bootstrap)
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
        "to point at --temp-db-name. This is checked ACTIVELY once that database exists — "
        "this flag records operator intent, it does not replace that check.",
    )
    p_bootstrap.set_defaults(func=cmd_bootstrap_roles)

    p_restore = sub.add_parser(
        "restore", help="Force-drop/recreate the target database and restore a dump."
    )
    _add_target_args(p_restore)
    _add_port_flag(p_restore)
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

    p_verify = sub.add_parser(
        "verify",
        help="Run the post-recovery acceptance battery. Non-mutating by default — no "
        "PostgreSQL state changes; pass --confirm-migrate to also run a real, DESTRUCTIVE "
        "`alembic upgrade head` smoke test.",
    )
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
        help="An additional SELECT check and its expected scalar result, executed under "
        "database-enforced read-only mode (default_transaction_read_only=on for that one "
        "psql process) — PostgreSQL itself rejects any side-effecting statement, not just "
        "this script's lexical SELECT-prefix check. Repeatable. "
        'Example: --check "SELECT count(*) FROM core.worlds" "0"',
    )
    p_verify.add_argument(
        "--confirm-migrate",
        action="store_true",
        help="DESTRUCTIVE, opt-in only: also run a real `alembic upgrade head` against this "
        "database, in addition to the non-mutating `alembic current` check that always runs. "
        "Without this flag (the default), verify never runs migrations and performs no "
        "PostgreSQL state mutation. Passing this can make real schema/data changes if the "
        "database is not already at head. Checked immediately before that one subprocess.",
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
