"""Run the whole backend suite as CI's four shards at once, on this machine (Windows or POSIX).

    uv run python scripts/run_sharded_tests.py            # all four shards, concurrently
    uv run python scripts/run_sharded_tests.py --verify-partition-only
    uv run python scripts/run_sharded_tests.py -- -x      # extra arguments go to every shard's pytest

It reproduces `.github/workflows/ci.yml`'s `postgres-tests` job locally. It reuses CI's partition
(`CI_TEST_SHARD=<index>/<total>`, whole files dealt round-robin by `tests/conftest.py`) and, like CI,
gives every shard **its own PostgreSQL 18 server**. That is the point of this script, not a nicety:
migrations and the downgrade tests create and drop cluster-global roles (`migration_owner`, the
application roles), so two shards on one server collide on them (`tuple concurrently deleted`). Each
shard here gets a throwaway cluster (`initdb` into the run directory, a free loopback port, its own
log) started from the PostgreSQL 18 binaries already installed; your own server and databases are
never connected to, written to or stopped.

Per shard, inside `.tmp/shards/run-<stamp>-<pid>/shard-<n>/`:

    pgdata/       the throwaway cluster (removed at the end)
    postgres.log  the server's log (kept)
    pytest.log    the shard's full pytest output (kept)
    tmp/          TEMP/TMP/TMPDIR for the shard's processes (removed)
    basetemp/     pytest's --basetemp (removed)

plus `isolation/` (the configuration-isolation plugin, docs/DEVELOPMENT.md section 6.2) and `cwd/`
(an empty directory, so the application's own `.env` lookup, which is relative to the current
directory, finds nothing; the repository `.env` that `tests/conftest.py` loads is neutralised by
the generated plugin). `PGAPPNAME=dnd_ai_shard_<n>` names each shard's
sessions. On Windows the four servers and four pytest processes (and what they start after
assignment) are in a Job Object that kills them if this script dies; the short-lived `subprocess.run`
utilities are not (see KillOnCloseJob). On Ctrl+C and on normal exit they are stopped and only the
resources this run created are removed. The run directory itself (logs) is always kept.

This covers unit, database and scenario tests, which are all of `tests/`. Linting, mypy, the
migrations job, the portal and the Foundry module are separate commands (docs/DEVELOPMENT.md).

Exit status: 0 only if the partition check passed, every shard exited 0, and (for an all-green run)
the tests executed equal the tests collected.
"""

import argparse
import contextlib
import ctypes
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SHARDS = 4  # must match the matrix and the "/4" in .github/workflows/ci.yml
REQUIRED_MAJOR = 18
_DB_NAME = "dnd_ai_ci"
_DB_PASSWORD = "postgres"  # a throwaway loopback cluster, as CI's container
_ISOLATION_PLUGIN = textwrap.dedent(
    """
    import os
    import re

    import pytest


    def _refuse(message):
        raise pytest.UsageError("sharded runner isolation: " + message)


    def pytest_sessionstart(session):
        # Section 6.2 of docs/DEVELOPMENT.md: the one default-configuration override.
        os.environ.pop("DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS", None)
        expected = os.environ.get("RUNNER_SHARD_URL")
        if not expected:
            return  # the plugin used on its own, as section 6.2 describes
        # tests/conftest.py has run load_dotenv() by now. A .env file may have put back anything
        # the runner removed from the environment, so close the doors again and then check.
        # Every database URL input is removed except DATABASE_URL, which is validated: that is
        # DND_AI_DATABASE_URL (application settings), DND_AI_TEST_DATABASE_URL (fixtures),
        # MIGRATION_DATABASE_URL and API_DATABASE_URL (migration and deployment tooling), and any
        # other name containing DATABASE_URL, along with the libpq variables.
        for name in list(os.environ):
            if (name != "DATABASE_URL" and "DATABASE_URL" in name.upper()) or re.fullmatch(
                r"PG(?!APPNAME).+", name
            ):
                os.environ.pop(name)
        if os.environ.get("DATABASE_URL") != expected:
            _refuse("DATABASE_URL is not this shard's cluster after loading .env")
        # What the application will resolve, which is what migration helpers, subprocesses and the
        # API tests ultimately use, must be the owned cluster too.
        from dnd_ai.config import settings
        from sqlalchemy import make_url as _make_url

        resolved, owned = _make_url(str(settings.database_url)), _make_url(expected)
        if (resolved.host, resolved.port, resolved.database, resolved.username) != (
            owned.host,
            owned.port,
            owned.database,
            owned.username,
        ):
            _refuse("the application's resolved database URL is not this shard's cluster")
        pgdata = os.environ.get("RUNNER_SHARD_PGDATA")
        if pgdata:
            import psycopg
            from sqlalchemy import make_url

            url = make_url(expected)
            with psycopg.connect(
                host=url.host,
                port=url.port,
                user=url.username,
                password=url.password,
                dbname="postgres",
                connect_timeout=10,
            ) as connection:
                data_directory = connection.execute("SHOW data_directory").fetchone()[0]
            if os.path.normcase(os.path.realpath(data_directory)) != os.path.normcase(
                os.path.realpath(pgdata)
            ):
                _refuse("the server behind DATABASE_URL is not this run's cluster")
    """
)
_SUMMARY = re.compile(r"(\d+) (passed|failed|skipped|xfailed|xpassed|errors?|warnings?|deselected)")
_PROGRESS = re.compile(r"\[\s*(\d+)%\]")


# --- finding PostgreSQL ------------------------------------------------------------------------


def find_pg_bin(explicit: str | None) -> Path:
    """The directory holding initdb/postgres/pg_isready/createdb for PostgreSQL 18."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("DND_AI_PG_BIN"):
        candidates.append(Path(os.environ["DND_AI_PG_BIN"]))
    initdb = shutil.which("initdb")
    if initdb:
        candidates.append(Path(initdb).parent)
    for root in (os.environ.get("PROGRAMFILES"), "/usr/lib/postgresql"):
        if root:
            candidates.append(Path(root) / "PostgreSQL" / str(REQUIRED_MAJOR) / "bin")
            candidates.append(Path(root) / str(REQUIRED_MAJOR) / "bin")
    suffix = ".exe" if sys.platform == "win32" else ""
    for directory in candidates:
        if all((directory / f"{name}{suffix}").exists() for name in ("initdb", "postgres")):
            version = subprocess.run(  # noqa: S603
                [str(directory / f"postgres{suffix}"), "--version"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            if re.search(rf"\b{REQUIRED_MAJOR}\.", version):
                return directory
    raise SystemExit(
        f"PostgreSQL {REQUIRED_MAJOR} binaries (initdb, postgres) were not found. Install them, put "
        "them on PATH, or pass --pg-bin / set DND_AI_PG_BIN to the directory that holds them."
    )


def _exe(directory: Path, name: str) -> str:
    return str(directory / (f"{name}.exe" if sys.platform == "win32" else name))


def free_ports(count: int) -> list[int]:
    sockets = [socket.socket() for _ in range(count)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


# --- children die with this script ------------------------------------------------------------


class JobObjectError(RuntimeError):
    """The Windows Job Object that contains this run's children could not be set up."""


class _BasicLimit(ctypes.Structure):
    _fields_ = [  # noqa: RUF012
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [  # noqa: RUF012
        (name, ctypes.c_uint64)
        for name in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")
    ]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [  # noqa: RUF012
        ("BasicLimitInformation", _BasicLimit),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class KillOnCloseJob:
    """A Windows Job Object. Closing it (when this script's handle closes, including when the script
    is killed) terminates the processes already assigned to it. That does not by itself guarantee
    nothing is left behind: the coverage limits below (the assignment window and the processes
    outside the job) apply.

    Every step is checked, and a failure raises `JobObjectError`: the run refuses to start rather
    than run children it could not contain. `add` also confirms membership with `IsProcessInJob`.
    Coverage is partial, and this is exactly what it covers. **In the job:** the four PostgreSQL
    servers and the four pytest processes, and every process they create *after* they were assigned.
    **Outside the job:** the utilities run with `subprocess.run` (`postgres --version`, `initdb`,
    `pg_isready`, `createdb`, `pg_ctl stop`, `taskkill`, and the partition check's `pytest
    --collect-only` processes), which are short-lived and not killed if this script is hard-killed
    while one is running. **The window:** between `Popen` returning and the assignment a child is
    already executing and may have created children of its own; those are not in the job, because a
    job only captures processes created after the assignment. A child whose assignment fails is
    killed by the caller and the run stops; on a normal exit or Ctrl+C the `finally` block kills the
    pytest trees and stops the servers whether or not a job exists.

    Elsewhere there is no job: POSIX children are in their own session and are stopped by the
    `finally` block. `kernel32` and `last_error` are injectable for tests."""

    def __init__(
        self,
        kernel32: Any = None,
        *,
        platform: str | None = None,
        last_error: Callable[[], int] | None = None,
    ) -> None:
        self.handle: int | None = None
        self._last_error = last_error or (lambda: ctypes.get_last_error())
        if (platform or sys.platform) != "win32":
            return
        k = kernel32 or ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = ctypes.c_void_p
        handle = k.CreateJobObjectW(None, None)
        if not handle:
            raise JobObjectError(f"CreateJobObjectW failed (error {self._last_error()})")
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        if not k.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = self._last_error()
            k.CloseHandle(handle)
            raise JobObjectError(f"SetInformationJobObject failed (error {error})")
        self._kernel32 = k
        self.handle = handle

    def add(self, process: "subprocess.Popen[bytes]") -> None:
        """Put `process` in the job, or raise `JobObjectError` (the caller then kills it)."""
        if self.handle is None:
            return
        k = self._kernel32
        k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        process_handle = ctypes.c_void_p(int(process._handle))  # type: ignore[attr-defined]
        if not k.AssignProcessToJobObject(self.handle, process_handle):
            raise JobObjectError(
                f"AssignProcessToJobObject failed for pid {process.pid} (error {self._last_error()})"
            )
        member = ctypes.c_int(0)
        k.IsProcessInJob.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        if (
            not k.IsProcessInJob(process_handle, self.handle, ctypes.byref(member))
            or not member.value
        ):
            raise JobObjectError(f"pid {process.pid} is not in the job after assignment")

    def contain(self, process: "subprocess.Popen[bytes]") -> None:
        """`add`, and on failure kill the process tree before raising."""
        try:
            self.add(process)
        except JobObjectError:
            kill_tree(process)
            raise


def kill_tree(process: "subprocess.Popen[bytes] | None") -> None:
    if process is None or process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(  # noqa: S603
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],  # noqa: S607
            capture_output=True,
            check=False,
        )
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(Exception):
        process.wait(timeout=30)


# --- one shard ------------------------------------------------------------------------------------


@dataclass
class Shard:
    index: int
    total: int
    root: Path
    port: int = 0
    server: "subprocess.Popen[bytes] | None" = None
    pytest: "subprocess.Popen[bytes] | None" = None
    started: float = 0.0
    finished: float = 0.0
    returncode: int | None = None
    collected: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"shard {self.index}/{self.total}"

    @property
    def pgdata(self) -> Path:
        return self.root / "pgdata"

    @property
    def pytest_log(self) -> Path:
        return self.root / "pytest.log"

    @property
    def postgres_log(self) -> Path:
        return self.root / "postgres.log"

    @property
    def database_url(self) -> str:
        return f"postgresql+psycopg://postgres:{_DB_PASSWORD}@127.0.0.1:{self.port}/{_DB_NAME}"


class ForeignServerError(RuntimeError):
    """Something other than this run's cluster answered on the shard's port."""


def port_in_use(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def verify_server_identity(port: int, pgdata: Path, server_pid: int | None) -> None:
    """Prove the server answering on `port` is the cluster in `pgdata` that this run started.

    `pg_isready` only says that *something* accepts connections there. Here the connection must
    authenticate with the run's own password (a foreign server will not know it), report
    `data_directory` equal to this run's `pgdata`, and its `postmaster.pid` must name the process
    this run started. Anything else raises `ForeignServerError` before a single write."""
    import psycopg

    try:
        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            user="postgres",
            password=_DB_PASSWORD,
            dbname="postgres",
            connect_timeout=5,
        ) as connection:
            row = connection.execute("SHOW data_directory").fetchone()
    except psycopg.Error as exc:
        raise ForeignServerError(
            f"the server on port {port} does not accept this run's credentials ({type(exc).__name__})"
        ) from exc
    reported = os.path.normcase(os.path.realpath(row[0])) if row else ""
    if reported != os.path.normcase(os.path.realpath(pgdata)):
        raise ForeignServerError(
            f"the server on port {port} serves {row[0]!r}, not {str(pgdata)!r}"
        )
    pid_file = pgdata / "postmaster.pid"
    first = pid_file.read_text(encoding="utf-8").splitlines()[0] if pid_file.exists() else ""
    if server_pid is not None and first.strip() != str(server_pid):
        raise ForeignServerError(
            f"postmaster.pid names {first!r}, but this run started process {server_pid}"
        )


def start_cluster(
    shard: Shard,
    pg_bin: Path,
    job: KillOnCloseJob,
    port: int,
    *,
    db_name: str = _DB_NAME,
    attempts: int = 3,
) -> None:
    """A throwaway PostgreSQL 18 cluster for this shard, owned by this run.

    A port that is already taken, or answered by a server that is not this run's, is never used: the
    candidate is rejected before `createdb` or any other write and a different port is tried, up to
    `attempts` times, then `ForeignServerError`."""
    shard.root.mkdir(parents=True, exist_ok=True)
    # Password authentication, as in CI's container (POSTGRES_PASSWORD): a test asserts that a
    # wrong password is refused, which `trust` would not do.
    pwfile = shard.root / "pgpass.txt"
    pwfile.write_text(_DB_PASSWORD, encoding="utf-8")
    subprocess.run(  # noqa: S603
        [
            _exe(pg_bin, "initdb"),
            "-D",
            str(shard.pgdata),
            "-U",
            "postgres",
            "-A",
            "scram-sha-256",
            f"--pwfile={pwfile}",
            "-E",
            "UTF8",
            "--no-sync",
        ],
        capture_output=True,
        check=True,
    )
    pwfile.unlink()
    with (shard.pgdata / "postgresql.conf").open("a", encoding="utf-8") as conf:
        # Disposable data: durability settings off for speed. Nothing else differs from CI's
        # container (default max_connections and memory settings).
        conf.write(
            "\nlisten_addresses = '127.0.0.1'\nfsync = off\n"
            "synchronous_commit = off\nfull_page_writes = off\n"
        )
    last: Exception | None = None
    for attempt in range(attempts):
        candidate = port if attempt == 0 else free_ports(1)[0]
        shard.port = candidate
        if port_in_use(candidate):
            last = ForeignServerError(f"port {candidate} is already in use")
            continue
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        with shard.postgres_log.open("ab") as log:
            shard.server = subprocess.Popen(  # noqa: S603
                [_exe(pg_bin, "postgres"), "-D", str(shard.pgdata), "-p", str(candidate)],
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                start_new_session=sys.platform != "win32",
            )
        job.contain(shard.server)
        try:
            _wait_until_ready(shard, pg_bin, candidate)
            verify_server_identity(candidate, shard.pgdata, shard.server.pid)
        except (ForeignServerError, RuntimeError) as exc:
            last = exc
            stop_cluster(shard, pg_bin)
            continue
        subprocess.run(  # noqa: S603
            [
                _exe(pg_bin, "createdb"),
                "-h",
                "127.0.0.1",
                "-p",
                str(candidate),
                "-U",
                "postgres",
                db_name,
            ],
            env={**os.environ, "PGPASSWORD": _DB_PASSWORD},
            capture_output=True,
            check=True,
        )
        return
    raise ForeignServerError(f"{shard.name}: no usable port after {attempts} attempts ({last})")


def _wait_until_ready(shard: Shard, pg_bin: Path, port: int) -> None:
    assert shard.server is not None
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if shard.server.poll() is not None:
            raise RuntimeError(f"{shard.name}: PostgreSQL exited early; see {shard.postgres_log}")
        ready = subprocess.run(  # noqa: S603
            [_exe(pg_bin, "pg_isready"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres"],
            capture_output=True,
            check=False,
        )
        if ready.returncode == 0:
            return
        time.sleep(0.3)
    raise RuntimeError(f"{shard.name}: PostgreSQL did not become ready on port {port}")


def stop_cluster(shard: Shard, pg_bin: Path) -> None:
    if shard.server is None or shard.server.poll() is not None:
        return
    subprocess.run(  # noqa: S603
        [
            _exe(pg_bin, "pg_ctl"),
            "-D",
            str(shard.pgdata),
            "stop",
            "-m",
            "immediate",
            "-w",
            "-t",
            "30",
        ],
        capture_output=True,
        check=False,
    )
    kill_tree(shard.server)


# Environment inputs that could point a shard at someone else's database, change which options or
# plugins pytest uses, or change which configuration is read. They are removed from every child's
# environment (names are reported, values never are); `.env` files can bring some back after the
# process starts, which the generated plugin closes again and then checks (see _ISOLATION_PLUGIN).
_SCRUBBED_PATTERNS = (
    re.compile(r"PYTEST_.*"),  # PYTEST_ADDOPTS can carry --basetemp, -p, -c, --rootdir ...
    re.compile(r"PG(?!APPNAME$).+"),  # libpq: host, port, user, service, passfile, options ...
    re.compile(
        r".*DATABASE_URL.*"
    ),  # DATABASE_URL, DND_AI_TEST_DATABASE_URL, DND_AI_DATABASE_URL ...
    re.compile(r"CI_TEST_SHARD"),
    re.compile(r"RUNNER_SHARD_.*"),
    re.compile(r"PYTHONPATH|PYTHONSTARTUP|PYTHONHOME|PYTHONSAFEPATH|PYTHONINSPECT"),
)


def scrubbed_environment() -> tuple[dict[str, str], list[str]]:
    """This process's environment without the inputs above, and the names that were removed."""
    kept: dict[str, str] = {}
    removed: list[str] = []
    for name, value in os.environ.items():
        if any(pattern.fullmatch(name.upper()) for pattern in _SCRUBBED_PATTERNS):
            removed.append(name)
        else:
            kept[name] = value
    return kept, sorted(removed)


def shard_environment(shard: Shard, isolation: Path) -> dict[str, str]:
    environment, _ = scrubbed_environment()
    scratch = shard.root / "tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    environment.update(
        DATABASE_URL=shard.database_url,
        # Empty, not absent: python-dotenv will not override a variable that is already set, so a
        # `.env` file cannot restore DND_AI_TEST_DATABASE_URL. The plugin also removes it.
        DND_AI_TEST_DATABASE_URL="",
        RUNNER_SHARD_URL=shard.database_url,
        RUNNER_SHARD_PGDATA=str(shard.pgdata),
        CI_TEST_SHARD=f"{shard.index}/{shard.total}",
        PGAPPNAME=f"dnd_ai_shard_{shard.index}",
        TEMP=str(scratch),
        TMP=str(scratch),
        TMPDIR=str(scratch),
        PYTHONPATH=str(isolation),
        PYTHONUNBUFFERED="1",
    )
    return environment


# Forwarded pytest options the runner accepts: they change how output looks or when a shard stops,
# never which database, configuration, plugins, directories or tests it uses. Everything else is
# refused, because the list of options that can bypass the isolation (--basetemp, -c, --rootdir,
# -p, -o, --confcutdir, --import-mode, --pyargs, ...) is open-ended and an allowlist cannot miss one.
_FLAGS = {"-x", "--exitfirst", "-v", "-vv", "-vvv", "--verbose", "-q", "-qq", "--quiet", "-l",
          "--showlocals", "--full-trace", "--no-header", "--no-summary"}  # fmt: skip
_VALUED = {"--tb": {"auto", "long", "short", "line", "native", "no"}, "--maxfail": None,
           "--durations": None}  # fmt: skip
_REPORT = re.compile(r"-r[a-zA-Z]+")


def validate_forwarded_arguments(arguments: Sequence[str]) -> list[str]:
    """The forwarded pytest arguments, or `SystemExit` naming the first one that is not allowed."""
    allowed = ", ".join(sorted(_FLAGS | set(_VALUED) | {"-r<chars>"}))
    items = list(arguments)
    index = 0
    while index < len(items):
        argument = items[index]
        name, equals, value = argument.partition("=")
        if argument in _FLAGS or _REPORT.fullmatch(argument):
            index += 1
            continue
        if name in _VALUED:
            if not equals:
                index += 1
                if index >= len(items):
                    raise SystemExit(f"{name} needs a value")
                value = items[index]
            choices = _VALUED[name]
            ok = value in choices if choices is not None else value.isdigit()
            if not ok:
                raise SystemExit(f"{name} was given {value!r}, which is not accepted")
            index += 1
            continue
        raise SystemExit(
            f"refusing to forward {argument!r} to the shards: it could change the isolation "
            f"(database, directories, configuration, plugins) or the set of tests. Allowed: "
            f"{allowed}. For anything else run pytest directly (docs/DEVELOPMENT.md section 6)."
        )
    return items


def pytest_command(shard: Shard | None, extra: Sequence[str], *, collect: bool) -> list[str]:
    command = [
        sys.executable, "-m", "pytest", "-p", "default_config_plugin", "-q",
        "-p", "no:cacheprovider", "--tb=short", f"--rootdir={REPO}", "-c", str(REPO / "pyproject.toml"),
    ]  # fmt: skip
    if collect:
        command += ["--collect-only"]
    else:
        assert shard is not None
        command += [f"--basetemp={shard.root / 'basetemp'}"]
    return [*command, *extra, str(REPO / "tests")]


# --- the partition check ----------------------------------------------------------------------


def collect_file_counts(
    environment: dict[str, str], cwd: Path, extra: Sequence[str]
) -> dict[str, int]:
    """How many tests each test file contributes to a collection. The partition is by whole file, so
    files and their counts are what must add up; node ids are not compared because a few
    parametrized tests put a fresh uuid in their id on every collection."""
    result = subprocess.run(  # noqa: S603
        pytest_command(None, extra, collect=True),
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 5):
        raise SystemExit(
            "test collection failed:\n" + result.stdout[-3000:] + "\n" + result.stderr[-2000:]
        )
    counts: dict[str, int] = {}
    for line in result.stdout.splitlines():
        if "::" in line and not line.startswith(" "):
            path = line.split("::", 1)[0].strip()
            counts[path] = counts.get(path, 0) + 1
    return counts


def verify_partition(
    total: int, isolation: Path, cwd: Path, extra: Sequence[str]
) -> tuple[dict[str, int], dict[int, dict[str, int]], list[str]]:
    """Collect everything, then every shard's selection, and prove the shards are disjoint and
    together equal the whole: every test file is in exactly one shard with all of its tests, so a
    newly added test (or file) is covered by exactly one shard."""
    base, _ = scrubbed_environment()
    base["PYTHONPATH"] = str(isolation)
    results: dict[str, dict[str, int]] = {}
    errors: list[str] = []

    def collect(label: str, shard: int | None) -> None:
        environment = dict(base)
        if shard is not None:
            environment["CI_TEST_SHARD"] = f"{shard}/{total}"
        try:
            results[label] = collect_file_counts(environment, cwd, extra)
        except SystemExit as exc:
            errors.append(f"{label}: {exc}")

    threads = [threading.Thread(target=collect, args=("all", None))]
    threads += [threading.Thread(target=collect, args=(str(i), i)) for i in range(1, total + 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        return {}, {}, errors
    everything = results["all"]
    shards = {i: results[str(i)] for i in range(1, total + 1)}
    problems: list[str] = []
    seen: dict[str, int] = {}
    for index, files in shards.items():
        if not files:
            problems.append(f"shard {index} selected no tests")
        for path, count in files.items():
            if path in seen:
                problems.append(f"{path} is in shards {seen[path]} and {index}")
            seen[path] = index
            if everything.get(path) != count:
                problems.append(
                    f"{path}: shard {index} has {count} tests, the suite has {everything.get(path)}"
                )
    for path in sorted(set(everything) - set(seen)):
        problems.append(f"{path} is in no shard")
    return everything, shards, problems


# --- reporting ----------------------------------------------------------------------------------


def parse_summary(log: Path) -> dict[str, int]:
    """The counts from pytest's final line (`7291 passed, 2 failed, 13 warnings in 2787.62s`)."""
    if not log.exists():
        return {}
    for line in reversed(log.read_text(encoding="utf-8", errors="replace").splitlines()):
        if re.search(r" in [\d.]+s", line) and _SUMMARY.search(line):
            counts: dict[str, int] = {}
            for number, word in _SUMMARY.findall(line):
                key = "error" if word.startswith("error") else word.removesuffix("s")
                counts[key] = counts.get(key, 0) + int(number)
            return counts
    return {}


def last_progress(log: Path) -> str:
    if not log.exists():
        return "starting"
    with log.open("rb") as handle:
        handle.seek(max(0, log.stat().st_size - 4000))
        tail = handle.read().decode("utf-8", errors="replace")
    found = _PROGRESS.findall(tail)
    return f"{found[-1]}%" if found else "starting"


def fmt(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{secs:02d}s" if hours else f"{minutes}m{secs:02d}s"


def failure_lines(log: Path, limit: int = 25) -> list[str]:
    if not log.exists():
        return []
    lines = [
        line.strip()
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith(("FAILED ", "ERROR "))
    ]
    return lines[:limit] + ([f"... and {len(lines) - limit} more"] if len(lines) > limit else [])


# --- the run ----------------------------------------------------------------------------------------


def run(arguments: argparse.Namespace) -> int:
    started = time.monotonic()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_root = REPO / ".tmp" / "shards" / f"run-{stamp}-{os.getpid()}"
    run_root.mkdir(parents=True)
    isolation = run_root / "isolation"
    isolation.mkdir()
    (isolation / "default_config_plugin.py").write_text(_ISOLATION_PLUGIN, encoding="utf-8")
    cwd = run_root / "cwd"
    cwd.mkdir()
    extra = arguments.pytest_args
    total = arguments.shards
    print(f"run directory: {run_root}")
    _, removed = scrubbed_environment()
    if removed:
        print("not passed to the shards (isolation): " + ", ".join(removed))

    print(f"checking that {total} shards partition the suite exactly ...")
    everything, partition, problems = verify_partition(total, isolation, cwd, extra)
    if problems:
        print("PARTITION CHECK FAILED:\n  " + "\n  ".join(problems))
        return 2
    sizes = ", ".join(f"{i}: {sum(files.values())}" for i, files in partition.items())
    print(
        f"partition ok: {sum(everything.values())} tests in {len(everything)} files = "
        f"disjoint shards ({sizes})"
    )
    if arguments.verify_partition_only:
        return 0

    pg_bin = find_pg_bin(arguments.pg_bin)
    try:
        job = KillOnCloseJob()
    except JobObjectError as exc:
        print(f"cannot contain the shards' processes, so none are started: {exc}")
        return 3
    if sys.platform == "win32":  # Ctrl+Break in a console behaves like Ctrl+C
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    shards = [Shard(i, total, run_root / f"shard-{i}") for i in range(1, total + 1)]
    for shard in shards:
        shard.collected = sum(partition[shard.index].values())
    interrupted = False
    try:
        ports = free_ports(total)
        print(f"starting {total} throwaway PostgreSQL {REQUIRED_MAJOR} servers (ports {ports}) ...")
        failures: list[BaseException] = []

        def boot(shard: Shard, port: int) -> None:
            try:
                start_cluster(shard, pg_bin, job, port)
            except BaseException as exc:  # noqa: BLE001 - reported below
                failures.append(exc)

        threads = [
            threading.Thread(target=boot, args=(s, p)) for s, p in zip(shards, ports, strict=True)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        if failures:
            print(f"could not start the servers: {failures[0]!r}")
            return 3

        print("running the shards concurrently ...")
        for shard in shards:
            shard.started = time.monotonic()
            log = shard.pytest_log.open("wb")
            shard.pytest = subprocess.Popen(  # noqa: S603
                pytest_command(shard, extra, collect=False),
                cwd=cwd,
                env=shard_environment(shard, isolation),
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
                start_new_session=sys.platform != "win32",
            )
            try:
                job.contain(shard.pytest)  # a child that cannot be contained is killed
            except JobObjectError as exc:
                print(f"{shard.name} could not be contained; stopping the run: {exc}")
                return 3

        next_report = time.monotonic() + 60
        deadline = time.monotonic() + arguments.timeout_minutes * 60
        while any(s.returncode is None for s in shards):
            time.sleep(1)
            for shard in shards:
                assert shard.pytest is not None
                if shard.returncode is None and shard.pytest.poll() is not None:
                    shard.returncode = shard.pytest.returncode
                    shard.finished = time.monotonic()
                    print(
                        f"  {shard.name} finished with exit {shard.returncode} "
                        f"after {fmt(shard.finished - shard.started)}"
                    )
            if time.monotonic() >= next_report:
                next_report += 60
                print(
                    f"  [{fmt(time.monotonic() - started)}] "
                    + "  ".join(
                        f"{s.index}:{'done' if s.returncode is not None else last_progress(s.pytest_log)}"
                        for s in shards
                    )
                )
            if time.monotonic() > deadline:
                print(f"timed out after {arguments.timeout_minutes} minutes; stopping the shards")
                for shard in shards:
                    if shard.returncode is None:
                        shard.notes.append("stopped at the overall timeout")
                        kill_tree(shard.pytest)
                        shard.returncode = 124
                        shard.finished = time.monotonic()
                break
    except KeyboardInterrupt:
        interrupted = True
        print("\ninterrupted: stopping the shards and removing what this run created ...")
        for shard in shards:
            if shard.returncode is None:
                shard.notes.append("interrupted")
                shard.returncode = 130
    finally:
        for shard in shards:
            kill_tree(shard.pytest)
        for shard in shards:
            stop_cluster(shard, pg_bin)
        if not arguments.keep_data:
            for shard in shards:
                for name in ("pgdata", "tmp", "basetemp"):
                    shutil.rmtree(shard.root / name, ignore_errors=True)

    return report(shards, everything, started, run_root, interrupted)


def report(
    shards: list[Shard], everything: set[str], started: float, run_root: Path, interrupted: bool
) -> int:
    print("\n" + "=" * 78)
    totals: dict[str, int] = {}
    failed = interrupted
    executed = 0
    for shard in shards:
        counts = parse_summary(shard.pytest_log)
        for key, value in counts.items():
            if key != "deselected":
                totals[key] = totals.get(key, 0) + value
        ran = sum(counts.get(k, 0) for k in ("passed", "failed", "skipped", "xfailed", "xpassed"))
        executed += ran
        elapsed = (shard.finished or time.monotonic()) - shard.started
        detail = ", ".join(f"{v} {k}" for k, v in counts.items() if k != "warning") or "no summary"
        note = f"  [{'; '.join(shard.notes)}]" if shard.notes else ""
        print(
            f"{shard.name}: exit {shard.returncode}  {detail}  ({shard.collected} collected, "
            f"{fmt(elapsed)}){note}"
        )
        if shard.returncode != 0:
            failed = True
            for line in failure_lines(shard.pytest_log):
                print(f"    {line}")
            print(f"    log: {shard.pytest_log}")
            print(f"    postgres log: {shard.postgres_log}")
    wall = fmt(time.monotonic() - started)
    collected = sum(everything.values())
    print("-" * 78)
    print(
        "total: "
        + ", ".join(f"{v} {k}" for k, v in totals.items() if k != "warning")
        + f"  | {collected} collected, {executed} executed | elapsed {wall}"
    )
    if not failed and executed != collected:
        print(f"MISMATCH: {collected} tests collected but {executed} executed")
        failed = True
    print(f"logs kept in {run_root}")
    print("RESULT: " + ("FAILED" if failed else "PASSED"))
    return 1 if failed else 0


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]  # progress shows when piped
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument(
        "--shards", type=int, default=DEFAULT_SHARDS, help=f"shard count (CI uses {DEFAULT_SHARDS})"
    )
    parser.add_argument("--pg-bin", help="directory holding the PostgreSQL 18 binaries")
    parser.add_argument("--timeout-minutes", type=int, default=120)
    parser.add_argument(
        "--verify-partition-only",
        action="store_true",
        help="only prove the shards are disjoint and cover the suite",
    )
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="keep each shard's cluster, temp and basetemp directories",
    )
    parser.add_argument(
        "pytest_args", nargs="*", help="after `--`: extra arguments for each pytest"
    )
    arguments = parser.parse_args()
    arguments.pytest_args = validate_forwarded_arguments(arguments.pytest_args)
    return run(arguments)


if __name__ == "__main__":
    sys.exit(main())
