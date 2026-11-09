"""The pure parts of scripts/run_sharded_tests.py (the local four-shard runner).

The runner itself is exercised end to end by running it; these pin the pieces that decide what each
shard is given, so a change cannot quietly drop CI's partition variable, the configuration
isolation, or a shard's private temporary directories.
"""

import importlib.util
import sys
from pathlib import Path

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
    assert "DND_AI_TEST_DATABASE_URL" not in environment  # always provision a throwaway database
    assert environment["DATABASE_URL"].endswith(f"@127.0.0.1:54002/{runner._DB_NAME}")
    assert environment["PGAPPNAME"] == "dnd_ai_shard_2"
    scratch = str(tmp_path / "shard-2" / "tmp")
    assert environment["TEMP"] == environment["TMP"] == environment["TMPDIR"] == scratch
    assert str(tmp_path / "isolation") in environment["PYTHONPATH"].split(runner.os.pathsep)


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
