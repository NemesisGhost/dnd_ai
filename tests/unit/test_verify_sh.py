"""scripts/verify.sh's own control-flow logic: argument handling and the
stage/ingress-revocation failure combinator (Phase 5 twelfth exit review §1).

Runs the real script under `bash` against a stubbed `uv` (on PATH) and a
stubbed ingress-open/close script (via VERIFY_SH_INGRESS_SCRIPT) so this
never runs the real quality/test suites and never contacts AWS — safe to run
anywhere, per docs/DEVELOPMENT.md §6 (unit tests use no database, and this
needs neither database nor network).
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VERIFY_SH = REPO_ROOT / "scripts" / "verify.sh"

_UV_STUB = """#!/usr/bin/env bash
# Ignores its arguments entirely; only STUB_UV_EXIT decides pass/fail, so a
# single stub stands in for ruff/mypy/pytest/alembic without running any of
# them.
exit "${STUB_UV_EXIT:-0}"
"""

_INGRESS_STUB = """#!/usr/bin/env bash
case "$1" in
  open) exit "${STUB_OPEN_EXIT:-0}" ;;
  close) exit "${STUB_CLOSE_EXIT:-0}" ;;
esac
"""


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A throwaway CWD with a stub `uv` (on PATH) and a stub ingress script,
    so running scripts/verify.sh here can never shell out to the real
    quality tools or to AWS."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    ingress_stub = scripts_dir / "ingress-stub.sh"
    ingress_stub.write_text(_INGRESS_STUB)
    _make_executable(ingress_stub)

    uv_stub = bin_dir / "uv"
    uv_stub.write_text(_UV_STUB)
    _make_executable(uv_stub)

    return tmp_path


def _run_verify(
    sandbox: Path,
    args: list[str],
    *,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PATH"] = f"{sandbox / 'bin'}{os.pathsep}{env['PATH']}"
    env["VERIFY_SH_INGRESS_SCRIPT"] = "scripts/ingress-stub.sh"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(VERIFY_SH), *args],
        cwd=sandbox,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_help_as_first_argument_prints_usage_and_exits_zero(sandbox: Path) -> None:
    result = _run_verify(sandbox, ["--help"])
    assert result.returncode == 0
    assert "Usage:" in result.stderr


def test_short_help_as_first_argument_prints_usage_and_exits_zero(sandbox: Path) -> None:
    result = _run_verify(sandbox, ["-h"])
    assert result.returncode == 0
    assert "Usage:" in result.stderr


def test_no_arguments_exits_two(sandbox: Path) -> None:
    result = _run_verify(sandbox, [])
    assert result.returncode == 2


def test_unknown_mode_exits_two(sandbox: Path) -> None:
    result = _run_verify(sandbox, ["bogus-mode"])
    assert result.returncode == 2


def test_unknown_trailing_argument_exits_two(sandbox: Path) -> None:
    result = _run_verify(sandbox, ["quality", "--nonsense"])
    assert result.returncode == 2


def test_failing_stage_fails_the_run_and_prints_its_output(sandbox: Path) -> None:
    result = _run_verify(sandbox, ["quality"], env_overrides={"STUB_UV_EXIT": "1"})
    assert result.returncode == 1
    assert "FAIL: ruff format --check" in result.stdout
    assert "All requested stages passed." not in result.stdout


def test_successful_stage_and_successful_revocation_passes(sandbox: Path) -> None:
    result = _run_verify(
        sandbox,
        ["database"],
        env_overrides={"STUB_UV_EXIT": "0", "STUB_OPEN_EXIT": "0", "STUB_CLOSE_EXIT": "0"},
    )
    assert result.returncode == 0
    assert "PASS: pytest tests/database" in result.stdout
    assert "All requested stages passed." in result.stdout


def test_successful_stage_with_failed_revocation_fails_the_run(sandbox: Path) -> None:
    result = _run_verify(
        sandbox,
        ["database"],
        env_overrides={"STUB_UV_EXIT": "0", "STUB_OPEN_EXIT": "0", "STUB_CLOSE_EXIT": "1"},
    )
    assert result.returncode == 1
    assert "PASS: pytest tests/database" in result.stdout
    assert "ingress revocation failed" in result.stderr
    assert "All requested stages passed." not in result.stdout


def test_failed_stage_with_failed_revocation_preserves_stage_failure_as_primary(
    sandbox: Path,
) -> None:
    result = _run_verify(
        sandbox,
        ["database"],
        env_overrides={"STUB_UV_EXIT": "1", "STUB_OPEN_EXIT": "0", "STUB_CLOSE_EXIT": "1"},
    )
    assert result.returncode == 1
    assert "FAIL: pytest tests/database" in result.stdout
    assert "close dev-database ingress rule" in result.stderr
    assert "stage failure remains primary" in result.stderr


def test_close_ingress_is_a_no_op_when_ingress_was_never_opened(sandbox: Path) -> None:
    """quality/unit never call open_ingress, so a close stub configured to
    fail must never even be invoked — proves revocation is conditioned on
    having actually opened, not run unconditionally regardless of mode."""
    result = _run_verify(
        sandbox,
        ["quality"],
        env_overrides={"STUB_UV_EXIT": "0", "STUB_CLOSE_EXIT": "1"},
    )
    assert result.returncode == 0
    assert "All requested stages passed." in result.stdout


@pytest.mark.parametrize(
    ("args", "expected_returncode"),
    [
        (["quality"], 0),
        (["unit"], 0),
        (["database"], 0),
        (["scenario"], 0),
        (["full"], 0),
        (["migration-round-trip"], 2),  # refuses without --confirm-destructive
        (["migration-round-trip", "--confirm-destructive"], 0),
    ],
)
def test_documented_invocations_work_exactly_as_written(
    sandbox: Path, args: list[str], expected_returncode: int
) -> None:
    result = _run_verify(
        sandbox,
        args,
        env_overrides={"STUB_UV_EXIT": "0", "STUB_OPEN_EXIT": "0", "STUB_CLOSE_EXIT": "0"},
    )
    assert result.returncode == expected_returncode, result.stdout + result.stderr
