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
(an empty directory, so no `.env` is read). `PGAPPNAME=dnd_ai_shard_<n>` names each shard's
sessions. The pytest processes and servers are assigned to a Windows Job Object that kills them if
this script dies, and on Ctrl+C they are stopped and only the resources this run created are
removed. The run directory itself (logs) is always kept.

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
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SHARDS = 4  # must match the matrix and the "/4" in .github/workflows/ci.yml
REQUIRED_MAJOR = 18
_DB_NAME = "dnd_ai_ci"
_DB_PASSWORD = "postgres"  # a throwaway loopback cluster, as CI's container
_ISOLATION_PLUGIN = textwrap.dedent(
    """\
    import os


    def pytest_sessionstart(session):
        os.environ.pop("DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS", None)
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


class KillOnCloseJob:
    """A Windows Job Object that kills every process in it when this script's handle closes, so a
    crash or a closed terminal cannot leave servers or test processes behind. A no-op elsewhere
    (POSIX children are stopped by the `finally` block and the process group)."""

    def __init__(self) -> None:
        self.handle: int | None = None
        if sys.platform != "win32":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class BasicLimit(ctypes.Structure):
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

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (  # noqa: RUF012
                    "ReadOps",
                    "WriteOps",
                    "OtherOps",
                    "ReadBytes",
                    "WriteBytes",
                    "OtherBytes",
                )
            ]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [  # noqa: RUF012
                ("BasicLimitInformation", BasicLimit),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return
        info = ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        if not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            return
        self._kernel32 = kernel32
        self.handle = handle

    def add(self, process: "subprocess.Popen[bytes]") -> None:
        if self.handle is None:
            return
        self._kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._kernel32.AssignProcessToJobObject(
            self.handle,
            ctypes.c_void_p(int(process._handle)),
        )


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


def start_cluster(shard: Shard, pg_bin: Path, job: KillOnCloseJob, port: int) -> None:
    """A throwaway PostgreSQL 18 cluster for this shard, owned by this run."""
    shard.port = port
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
            f"\nport = {port}\nlisten_addresses = '127.0.0.1'\nfsync = off\n"
            "synchronous_commit = off\nfull_page_writes = off\n"
        )
    log = shard.postgres_log.open("wb")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    shard.server = subprocess.Popen(  # noqa: S603
        [_exe(pg_bin, "postgres"), "-D", str(shard.pgdata)],
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        start_new_session=sys.platform != "win32",
    )
    job.add(shard.server)
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
            break
        time.sleep(0.3)
    else:
        raise RuntimeError(f"{shard.name}: PostgreSQL did not become ready on port {port}")
    subprocess.run(  # noqa: S603
        [_exe(pg_bin, "createdb"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", _DB_NAME],
        env={**os.environ, "PGPASSWORD": _DB_PASSWORD},
        capture_output=True,
        check=True,
    )


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


def shard_environment(shard: Shard, isolation: Path) -> dict[str, str]:
    environment = {**os.environ}
    for variable in ("DND_AI_TEST_DATABASE_URL", "CI_TEST_SHARD"):
        environment.pop(variable, None)
    scratch = shard.root / "tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    environment.update(
        DATABASE_URL=shard.database_url,
        CI_TEST_SHARD=f"{shard.index}/{shard.total}",
        PGAPPNAME=f"dnd_ai_shard_{shard.index}",
        TEMP=str(scratch),
        TMP=str(scratch),
        TMPDIR=str(scratch),
        PYTHONPATH=os.pathsep.join(filter(None, [str(isolation), os.environ.get("PYTHONPATH")])),
        PYTHONUNBUFFERED="1",
    )
    return environment


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
    base = {**os.environ}
    base.pop("CI_TEST_SHARD", None)
    base["PYTHONPATH"] = os.pathsep.join(filter(None, [str(isolation), base.get("PYTHONPATH")]))
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
    job = KillOnCloseJob()
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
            job.add(shard.pytest)

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
    return run(arguments)


if __name__ == "__main__":
    sys.exit(main())
