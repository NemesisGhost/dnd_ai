"""The pure parts of scripts/run_sharded_tests.py (the local four-shard runner).

The runner itself is exercised end to end by running it; these pin the pieces that decide what each
shard is given, so a change cannot quietly drop CI's partition variable, the configuration
isolation, or a shard's private temporary directories.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_sharded_tests.py"
_spec = importlib.util.spec_from_file_location("run_sharded_tests", _PATH)
assert _spec is not None and _spec.loader is not None
runner = importlib.util.module_from_spec(_spec)
sys.modules["run_sharded_tests"] = runner
_spec.loader.exec_module(runner)


def _shard(tmp_path: Path, index: int = 2) -> "runner.Shard":
    shard = runner.Shard(index=index, total=4, root=tmp_path / f"shard-{index}")
    shard.port = 54000 + index
    return shard


def test_a_shard_is_given_ci_s_partition_its_own_database_and_private_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DND_AI_TEST_DATABASE_URL", "postgresql://elsewhere/db")
    monkeypatch.setenv("CI_TEST_SHARD", "9/9")
    environment = runner.shard_environment(_shard(tmp_path), tmp_path / "isolation")
    assert environment["CI_TEST_SHARD"] == "2/4"
    # Set but empty, so python-dotenv (which never overrides a variable that is set) cannot restore a
    # value from .env; the generated plugin also removes it once .env has loaded.
    assert environment["DND_AI_TEST_DATABASE_URL"] == ""
    assert environment["DATABASE_URL"].endswith(f"@127.0.0.1:54002/{runner._DB_NAME}")
    assert environment["PGAPPNAME"] == "dnd_ai_shard_2"
    scratch = str(tmp_path / "shard-2" / "tmp")
    assert environment["TEMP"] == environment["TMP"] == environment["TMPDIR"] == scratch
    assert environment["PYTHONPATH"] == str(tmp_path / "isolation")  # nothing else is importable
    assert environment["DND_AI_SHARD_PGDATA"] == str(tmp_path / "shard-2" / "pgdata")
    assert environment["DND_AI_SHARD_DATABASE_URL"] == environment["DATABASE_URL"]


def test_two_shards_share_no_directory_port_or_application_name(tmp_path: Path) -> None:
    first = runner.shard_environment(_shard(tmp_path, 1), tmp_path / "isolation")
    second = runner.shard_environment(_shard(tmp_path, 2), tmp_path / "isolation")
    for variable in ("DATABASE_URL", "PGAPPNAME", "TEMP", "CI_TEST_SHARD"):
        assert first[variable] != second[variable], variable


def test_the_shard_command_pins_a_private_basetemp_and_the_repository_config(
    tmp_path: Path,
) -> None:
    shard = _shard(tmp_path, 3)
    command = runner.pytest_command(shard, ["-x"], collect=False)
    assert f"--basetemp={tmp_path / 'shard-3' / 'basetemp'}" in command
    assert "-x" in command and "default_config_plugin" in command
    assert command[-1].endswith("tests")
    assert "--collect-only" not in command
    assert "--collect-only" in runner.pytest_command(None, [], collect=True)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            "7291 passed, 2 failed, 13 warnings in 2787.62s (0:46:27)",
            {"passed": 7291, "failed": 2, "warning": 13},
        ),
        ("1243 passed, 6072 deselected in 841.20s (0:14:01)", {"passed": 1243, "deselected": 6072}),
        ("3 passed, 1 error in 2.00s", {"passed": 3, "error": 1}),
    ],
)
def test_the_summary_line_is_parsed(tmp_path: Path, line: str, expected: dict[str, int]) -> None:
    log = tmp_path / "pytest.log"
    log.write_text("....\n" + line + "\n", encoding="utf-8")
    assert runner.parse_summary(log) == expected


def test_a_log_with_no_summary_reports_nothing(tmp_path: Path) -> None:
    log = tmp_path / "pytest.log"
    log.write_text("....F\n", encoding="utf-8")
    assert runner.parse_summary(log) == {}
    assert runner.parse_summary(tmp_path / "missing.log") == {}


def test_the_shard_count_matches_ci() -> None:
    ci = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert f"CI_TEST_SHARD: ${{{{ matrix.shard }}}}/{runner.DEFAULT_SHARDS}" in ci
    assert "shard: [1, 2, 3, 4]" in ci and runner.DEFAULT_SHARDS == 4


def test_the_free_ports_are_distinct() -> None:
    ports = runner.free_ports(4)
    assert len(set(ports)) == 4


# --- the environment a shard is given ------------------------------------------------------------


def test_inputs_that_could_bypass_the_isolation_are_removed_from_every_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hostile = {
        "PYTEST_ADDOPTS": "--basetemp=C:/elsewhere -p no:default_config_plugin",
        "PYTEST_PLUGINS": "evil",
        "PGHOST": "prod.example",
        "PGPORT": "5432",
        "PGSERVICE": "prod",
        "PGPASSFILE": "C:/passwords",
        "DND_AI_DATABASE_URL": "postgresql://prod/db",
        "MIGRATION_DATABASE_URL": "postgresql://prod/db",
        "PYTHONPATH": "C:/shadow",
        "PYTHONSTARTUP": "C:/startup.py",
    }
    for name, value in hostile.items():
        monkeypatch.setenv(name, value)
    environment = runner.shard_environment(_shard(tmp_path), tmp_path / "isolation")
    for name in hostile:
        if name != "PYTHONPATH":
            assert name not in environment, name
    assert environment["PYTHONPATH"] == str(tmp_path / "isolation")  # replaced, not extended
    assert environment["PGAPPNAME"] == "dnd_ai_shard_2"
    _, removed = runner.scrubbed_environment()
    assert set(hostile) <= set(removed)


_HOSTILE_ENV = """
DND_AI_TEST_DATABASE_URL=postgresql://hostile.example/elsewhere
DATABASE_URL=postgresql://hostile.example/elsewhere
PGHOST=hostile.example
PGPORT=1
PGPASSFILE=C:/hostile
"""


def _sandbox_pytest(tmp_path: Path, environment: dict[str, str], test: Path) -> "object":
    return subprocess.run(  # noqa: S603
        [
            sys.executable, "-m", "pytest", "-p", "default_config_plugin", "-p", "no:cacheprovider",
            "-q", str(test), f"--rootdir={tmp_path}",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )  # fmt: skip


def _sandbox(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    isolation = tmp_path / "isolation"
    isolation.mkdir()
    (isolation / "default_config_plugin.py").write_text(runner._ISOLATION_PLUGIN)
    (tmp_path / ".env").write_text(_HOSTILE_ENV, encoding="utf-8")
    (tmp_path / "conftest.py").write_text("from dotenv import load_dotenv\n\nload_dotenv()\n")
    environment = runner.shard_environment(_shard(tmp_path), isolation)
    environment.pop("DND_AI_SHARD_PGDATA")  # no server here: the identity check has its own test
    return tmp_path, environment


def test_a_hostile_dotenv_cannot_bring_back_a_database_or_a_libpq_setting(tmp_path: Path) -> None:
    """The real mechanism in a sandbox project: a conftest that calls `load_dotenv()` (as
    tests/conftest.py does) next to a `.env` that tries to override the shard's database, plus the
    runner's generated plugin. After the plugin's session start the test sees only the shard's own
    database URL, no DND_AI_TEST_DATABASE_URL and no libpq variable."""
    root, environment = _sandbox(tmp_path)
    test = root / "test_environment.py"
    test.write_text(
        "import os\n\n\n"
        "def test_only_the_shard_database_is_visible():\n"
        "    assert not os.environ.get('DND_AI_TEST_DATABASE_URL')\n"
        "    assert os.environ['DATABASE_URL'] == os.environ['DND_AI_SHARD_DATABASE_URL']\n"
        "    assert 'hostile' not in os.environ['DATABASE_URL']\n"
        "    assert [n for n in os.environ if n.startswith('PG') and n != 'PGAPPNAME'] == []\n"
    )
    result = _sandbox_pytest(root, environment, test)
    assert result.returncode == 0, result.stdout + result.stderr  # type: ignore[attr-defined]


def test_a_session_whose_database_is_not_the_shards_is_aborted(tmp_path: Path) -> None:
    """If DATABASE_URL were not the shard's after .env loading, the plugin refuses to start the
    session rather than let fixtures run against another server."""
    root, environment = _sandbox(tmp_path)
    test = root / "test_noop.py"
    test.write_text("def test_noop():\n    pass\n")
    environment["DATABASE_URL"] = "postgresql+psycopg://postgres:postgres@127.0.0.1:1/elsewhere"
    result = _sandbox_pytest(root, environment, test)
    assert result.returncode != 0  # type: ignore[attr-defined]
    assert "not this shard's cluster" in result.stdout + result.stderr  # type: ignore[attr-defined]


# --- forwarded pytest arguments -------------------------------------------------------------------


@pytest.mark.parametrize(
    "arguments",
    [
        ["-x"],
        ["--exitfirst", "-v", "--tb=short"],
        ["--tb", "line", "--maxfail=3", "-rfE"],
        ["--durations", "10"],
        [],
    ],
)
def test_harmless_forwarded_arguments_pass_through_unchanged(arguments: list[str]) -> None:
    assert runner.validate_forwarded_arguments(arguments) == arguments


@pytest.mark.parametrize(
    "arguments",
    [
        ["--basetemp=C:/elsewhere"],
        ["--basetemp", "C:/elsewhere"],  # the second form
        ["-c", "other.ini"],
        ["--config-file=other.ini"],
        ["--rootdir=C:/elsewhere"],
        ["-p", "no:default_config_plugin"],
        ["-pno:default_config_plugin"],
        ["-o", "addopts="],
        ["--override-ini=addopts="],
        ["--confcutdir=C:/"],
        ["--import-mode=importlib"],
        ["--pyargs", "other"],
        ["-k", "not database"],
        ["-m", "unit"],
        ["--deselect", "tests/x.py::t"],
        ["--ignore=tests/database"],
        ["tests/unit/test_config.py"],  # a path would change the set of tests
        ["--tb=weird"],
        ["--maxfail=many"],
        ["--maxfail"],
    ],
)
def test_forwarded_arguments_that_could_bypass_the_isolation_are_refused(
    arguments: list[str],
) -> None:
    with pytest.raises(SystemExit):
        runner.validate_forwarded_arguments(arguments)


# --- the Windows Job Object ------------------------------------------------------------------------


class _FakeKernel32:
    """Stands in for kernel32 and records calls; each step can be made to fail."""

    def __init__(self, *, fail: str | None = None, member: bool = True) -> None:
        self.fail = fail
        self.member = member
        self.calls: list[str] = []
        self.CreateJobObjectW = self._step("CreateJobObjectW", 123)
        self.SetInformationJobObject = self._step("SetInformationJobObject", 1)
        self.AssignProcessToJobObject = self._step("AssignProcessToJobObject", 1)
        self.CloseHandle = self._step("CloseHandle", 1)
        self.IsProcessInJob = self._membership_step()

    def _step(self, name: str, ok: int) -> Any:
        def call(*_args: object) -> int:
            self.calls.append(name)
            return 0 if self.fail == name else ok

        return call

    def _membership_step(self) -> Any:
        def call(_process: object, _job: object, result: Any) -> int:
            self.calls.append("IsProcessInJob")
            if self.fail == "IsProcessInJob":
                return 0
            result._obj.value = 1 if self.member else 0
            return 1

        return call


class _FakeProcess:
    pid = 4242
    _handle = 77

    def poll(self) -> int | None:
        return 0  # already gone, so there is nothing for kill_tree to do


def _job(kernel32: _FakeKernel32) -> Any:
    return runner.KillOnCloseJob(kernel32, platform="win32", last_error=lambda: 5)


def test_a_job_object_that_cannot_be_created_or_configured_stops_the_run() -> None:
    with pytest.raises(runner.JobObjectError, match="CreateJobObjectW"):
        _job(_FakeKernel32(fail="CreateJobObjectW"))
    kernel32 = _FakeKernel32(fail="SetInformationJobObject")
    with pytest.raises(runner.JobObjectError, match="SetInformationJobObject"):
        _job(kernel32)
    assert "CloseHandle" in kernel32.calls  # the half-made job is not leaked


def test_a_process_that_cannot_be_assigned_is_reported_and_killed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed: list[object] = []
    monkeypatch.setattr(runner, "kill_tree", killed.append)
    job = _job(_FakeKernel32(fail="AssignProcessToJobObject"))
    with pytest.raises(runner.JobObjectError, match="AssignProcessToJobObject"):
        job.contain(_FakeProcess())
    assert len(killed) == 1  # the uncontained child does not keep running


def test_a_process_that_is_not_a_member_after_assignment_is_not_accepted() -> None:
    with pytest.raises(runner.JobObjectError, match="not in the job"):
        _job(_FakeKernel32(member=False)).add(_FakeProcess())
    with pytest.raises(runner.JobObjectError):
        _job(_FakeKernel32(fail="IsProcessInJob")).add(_FakeProcess())


def test_a_contained_process_is_accepted_and_posix_has_no_job() -> None:
    _job(_FakeKernel32()).add(_FakeProcess())
    assert runner.KillOnCloseJob(platform="linux").handle is None
