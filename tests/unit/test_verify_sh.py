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
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VERIFY_SH = REPO_ROOT / "scripts" / "verify.sh"


def _resolve_bash() -> str:
    """Full path to a real `bash`, not the bare name.

    On Windows, subprocess.run(["bash", ...]) resolves the executable via
    CreateProcess's own search order, which checks System32 *before* PATH
    (Microsoft's documented lpApplicationName=NULL behavior) — so if
    anything has ever registered C:\\Windows\\System32\\bash.exe (the WSL
    launcher stub; Docker Desktop's Windows integration does this), it wins
    over Git Bash even when Git Bash appears earlier in PATH. That stub
    fails outright unless a real WSL distro with /bin/bash is installed and
    set default.

    shutil.which() does a plain left-to-right PATH scan instead of
    replicating that OS search order, so it finds Git Bash first whenever
    Git Bash actually precedes System32 in PATH (the normal case here) —
    passing its resolved absolute path to subprocess.run sidesteps
    CreateProcess's own resolution entirely, since a full path is used
    as-is with no search.
    """
    bash = shutil.which("bash")
    if bash is None:
        # Fails loudly rather than skipping — this project's tests/unit
        # runs everywhere pytest does, and a skip here would silently drop
        # coverage of scripts/verify.sh's control flow rather than
        # reporting it, the same false-green tests/conftest.py's
        # DatabaseConfigurationError exists to avoid for the database tiers.
        raise RuntimeError(
            "No `bash` found on PATH — required to exercise scripts/verify.sh "
            "(tests/unit/test_verify_sh.py). Install Git for Windows or another "
            "bash and ensure it's on PATH."
        )
    return bash


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
        [_resolve_bash(), str(VERIFY_SH), *args],
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


# Per ADR 0011, open_ingress() is a no-op unless DATABASE_URL names an AWS RDS
# endpoint (see needs_ingress() in verify.sh and the two tests below this
# module). Every test in this file that means to exercise the open/close
# path — as opposed to the local-target no-op path, tested separately —
# must supply this, or open_ingress() will skip the stub entirely regardless
# of STUB_OPEN_EXIT/STUB_CLOSE_EXIT.
_RDS_DATABASE_URL = (
    "postgresql+psycopg://dnd_admin:pw@dnd-ai-dev-db.abc123.us-east-1.rds.amazonaws.com"
    ":5432/dnd_ai?sslmode=require"
)


def test_successful_stage_and_successful_revocation_passes(sandbox: Path) -> None:
    result = _run_verify(
        sandbox,
        ["database"],
        env_overrides={
            "STUB_UV_EXIT": "0",
            "STUB_OPEN_EXIT": "0",
            "STUB_CLOSE_EXIT": "0",
            "DATABASE_URL": _RDS_DATABASE_URL,
        },
    )
    assert result.returncode == 0
    assert "PASS: pytest tests/database" in result.stdout
    assert "All requested stages passed." in result.stdout


def test_successful_stage_with_failed_revocation_fails_the_run(sandbox: Path) -> None:
    result = _run_verify(
        sandbox,
        ["database"],
        env_overrides={
            "STUB_UV_EXIT": "0",
            "STUB_OPEN_EXIT": "0",
            "STUB_CLOSE_EXIT": "1",
            "DATABASE_URL": _RDS_DATABASE_URL,
        },
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
        env_overrides={
            "STUB_UV_EXIT": "1",
            "STUB_OPEN_EXIT": "0",
            "STUB_CLOSE_EXIT": "1",
            "DATABASE_URL": _RDS_DATABASE_URL,
        },
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


def test_database_mode_does_not_open_ingress_for_a_local_database_url(sandbox: Path) -> None:
    """Per ADR 0011, a local PostgreSQL DATABASE_URL must never trigger the
    AWS ingress open/close path. Both stubs are configured to fail if
    invoked at all, so this only passes if needs_ingress() correctly gates
    open_ingress() on an *.rds.amazonaws.com host and skips it here."""
    result = _run_verify(
        sandbox,
        ["database"],
        env_overrides={
            "STUB_UV_EXIT": "0",
            "STUB_OPEN_EXIT": "1",
            "STUB_CLOSE_EXIT": "1",
            "DATABASE_URL": "postgresql+psycopg://postgres:postgres@localhost:5432/dnd_ai",
        },
    )
    assert result.returncode == 0
    assert "PASS: pytest tests/database" in result.stdout
    assert "All requested stages passed." in result.stdout


def test_database_mode_opens_and_closes_ingress_for_an_rds_database_url(sandbox: Path) -> None:
    """The converse of the local case above: an *.rds.amazonaws.com
    DATABASE_URL must still open and close ingress exactly as before."""
    result = _run_verify(
        sandbox,
        ["database"],
        env_overrides={
            "STUB_UV_EXIT": "0",
            "STUB_OPEN_EXIT": "0",
            "STUB_CLOSE_EXIT": "1",
            "DATABASE_URL": _RDS_DATABASE_URL,
        },
    )
    assert result.returncode == 1
    assert "PASS: pytest tests/database" in result.stdout
    assert "ingress revocation failed" in result.stderr


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
