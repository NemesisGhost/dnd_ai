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
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VERIFY_SH = REPO_ROOT / "scripts" / "verify.sh"

# Bounded so a candidate that hangs (rather than failing outright) can't
# stall collection — a real, usable bash answers "exit 0" in well under a
# second; this only needs to be comfortably larger than that.
_BASH_PROBE_TIMEOUT_SECONDS = 5.0


def _probe_bash(path: str) -> bool:
    """True if `path` is a genuinely runnable bash: launching it and
    running a trivial command succeeds. Resolving a path (shutil.which(),
    a PATH scan, a known install location) only proves *something* exists
    there — on Windows, C:\\Windows\\System32\\bash.exe is commonly a WSL
    launcher stub that resolves fine but fails outright (nonzero exit, or
    a GUI/console prompt) unless a real WSL distro is installed and set
    default, so every candidate must actually be run, not just found."""
    try:
        result = subprocess.run(
            [path, "-c", "exit 0"],
            capture_output=True,
            timeout=_BASH_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def find_usable_bash(candidates: Sequence[str], probe: Callable[[str], bool]) -> str | None:
    """Pure selection logic, independent of how candidates are discovered
    or probed — returns the first candidate `probe` reports as usable, or
    None if none are. Kept separate from _resolve_bash() below so this can
    be unit-tested with fake candidates/probes, without depending on what
    bash (if any) is actually installed on the machine running the test
    suite."""
    for candidate in candidates:
        if probe(candidate):
            return candidate
    return None


def _candidate_bash_paths() -> list[str]:
    """Ordered candidates to probe: whatever `bash` resolves to on PATH
    first (correct and sufficient on Linux/macOS, and the common case on
    Windows too), then well-known Git-for-Windows install locations as
    fallbacks — covering per-machine, per-user, and 32-bit-on-64-bit
    installs — since Git Bash may be installed but not (yet) win the PATH
    resolution race against a WSL launcher stub (see _probe_bash's
    docstring)."""
    candidates: list[str] = []
    on_path = shutil.which("bash")
    if on_path:
        candidates.append(on_path)

    if sys.platform == "win32":
        for env_var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LocalAppData"):
            base = os.environ.get(env_var)
            if not base:
                continue
            for suffix in (r"Git\bin\bash.exe", r"Programs\Git\bin\bash.exe"):
                candidate = str(Path(base) / suffix)
                if candidate not in candidates:
                    candidates.append(candidate)

    return candidates


def _resolve_bash() -> str:
    """Full path to a genuinely usable `bash`, not just a resolved-but-
    maybe-broken one — see _probe_bash()'s docstring for why resolution
    alone (shutil.which() or otherwise) isn't sufficient on Windows.

    Called once, at module import time (see BASH_EXECUTABLE below), so a
    missing/broken bash surfaces as a single collection-time error for
    this whole module rather than every test independently raising the
    same RuntimeError — this project's tests/unit runs everywhere pytest
    does and must never silently skip, the same false-green
    tests/conftest.py's DatabaseConfigurationError exists to avoid for the
    database tiers.
    """
    candidates = _candidate_bash_paths()
    usable = find_usable_bash(candidates, _probe_bash)
    if usable is None:
        checked = ", ".join(candidates) if candidates else "(none found)"
        raise RuntimeError(
            "No usable `bash` found — required to exercise scripts/verify.sh "
            f"(tests/unit/test_verify_sh.py). Checked: {checked}. A resolved "
            "path isn't enough: C:\\Windows\\System32\\bash.exe (a WSL launcher "
            "stub, if anything has ever registered it — e.g. Docker Desktop's "
            "Windows integration) resolves but fails outright without a real "
            "WSL distro installed and set default. Install Git for Windows (or "
            "another real bash) and ensure it's usable."
        )
    return usable


BASH_EXECUTABLE = _resolve_bash()


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
        [BASH_EXECUTABLE, str(VERIFY_SH), *args],
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


# --- find_usable_bash() resolver logic ---------------------------------
#
# Exercised with fake candidate lists and fake probe functions rather than
# real paths/subprocess calls, so these never depend on what bash (if any)
# is actually installed on the machine running the suite — unlike the
# tests above, which all shell out to the real BASH_EXECUTABLE this module
# resolved once at import time.


def test_find_usable_bash_skips_a_broken_first_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    probed: list[str] = []

    def fake_probe(path: str) -> bool:
        probed.append(path)
        return path == "/working/bash"

    result = find_usable_bash(["/broken/bash", "/working/bash"], fake_probe)

    assert result == "/working/bash"
    assert probed == ["/broken/bash", "/working/bash"]


def test_find_usable_bash_returns_none_with_no_usable_candidate() -> None:
    result = find_usable_bash(
        ["/broken/bash", "/also/broken/bash"],
        lambda _path: False,
    )

    assert result is None


def test_find_usable_bash_returns_none_for_an_empty_candidate_list() -> None:
    assert find_usable_bash([], lambda _path: True) is None


def test_find_usable_bash_takes_a_working_path_candidate_immediately() -> None:
    probed: list[str] = []

    def fake_probe(path: str) -> bool:
        probed.append(path)
        return True

    result = find_usable_bash(["/usr/bin/bash", "/never/reached"], fake_probe)

    # Short-circuits on the first working candidate — never probes the rest.
    assert result == "/usr/bin/bash"
    assert probed == ["/usr/bin/bash"]


def test_resolve_bash_raises_with_no_usable_candidate_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # _resolve_bash() itself (not just find_usable_bash()) must fail
    # loudly — this is what BASH_EXECUTABLE's module-level assignment
    # relies on to turn "nothing usable" into one clear collection-time
    # error instead of every test independently raising later.
    monkeypatch.setattr(
        "tests.unit.test_verify_sh._candidate_bash_paths",
        lambda: ["/broken/bash", "/also/broken/bash"],
    )
    monkeypatch.setattr("tests.unit.test_verify_sh._probe_bash", lambda _path: False)

    with pytest.raises(RuntimeError, match="No usable `bash` found"):
        _resolve_bash()


def test_resolve_bash_returns_the_first_working_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tests.unit.test_verify_sh._candidate_bash_paths",
        lambda: ["/broken/bash", "/working/bash"],
    )
    monkeypatch.setattr(
        "tests.unit.test_verify_sh._probe_bash", lambda path: path == "/working/bash"
    )

    assert _resolve_bash() == "/working/bash"


# --- _probe_bash() itself -----------------------------------------------
#
# Unlike the pure find_usable_bash() tests above, these do exercise a real
# subprocess — but only ever the module's own already-resolved
# BASH_EXECUTABLE (proving a genuine bash probes as usable) or paths that
# can't possibly resolve to anything real, so no *additional* host
# dependency is introduced beyond what the rest of this module already
# requires to run at all.


def test_probe_bash_accepts_the_resolved_bash_executable() -> None:
    assert _probe_bash(BASH_EXECUTABLE) is True


def test_probe_bash_rejects_a_nonexistent_path() -> None:
    assert _probe_bash(str(REPO_ROOT / "no-such-executable-here")) is False


def test_probe_bash_rejects_a_real_executable_that_is_not_actually_bash() -> None:
    # A real, resolvable, launchable executable — just not one that
    # understands `-c "exit 0"` the way bash does: `python -c "exit 0"` is
    # a SyntaxError (bash's `exit` is a shell builtin; Python's is a
    # callable, so bare `exit 0` doesn't parse), which is exactly the
    # "resolves but is broken" case _probe_bash exists to catch — a
    # cross-platform stand-in for the WSL-launcher-stub scenario without
    # depending on WSL actually being present (or absent) on this host.
    assert _probe_bash(sys.executable) is False
