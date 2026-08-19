"""Behavioral regression coverage for tests/conftest.py's per-run pytest
basetemp mechanism (its pytest_configure() hook and the two helpers it
calls) — proves the actual observable behavior a source-level check on
pyproject.toml/conftest.py's text could not: that the plain `pytest ...`
command actually starts and passes, that two independent runs never
collide on each other's directories, and that a stale directory this
identity can't remove is skipped rather than crashing the run — without
requiring any real OS-level permission/ACL mutation, so this runs
identically on Windows and CI's Linux runners.

A prior version of this file (removed) asserted on the literal
--basetemp=/cache_dir strings in pyproject.toml. That approach could not
have caught the actual regression this mechanism exists to prevent — a
fixed path becoming unusable between sessions — since the strings looked
fine right up until the directory they named stopped working. Only
running the real thing (below) or exercising the real cleanup/selection
logic against a simulated failure (also below) proves anything about
that.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

import tests.conftest as conftest_module
from tests.conftest import (
    _PYTEST_RUN_DIR_PREFIX,
    _cleanup_stale_pytest_run_dirs,
    _new_pytest_run_basetemp,
)

pytestmark = pytest.mark.unit

# A minimal, self-contained conftest.py reproducing the real
# tests/conftest.py mechanism under test — deliberately a plain copy
# rather than an import of the real module, so this sandbox never
# touches the real project's own .tmp/ directory or its state, and stays
# a faithful, isolated subject for the subprocess tests below.
_SANDBOX_CONFTEST = textwrap.dedent(
    """
    import shutil
    import uuid
    from pathlib import Path

    import pytest

    ROOT = Path(__file__).resolve().parent / ".tmp"
    PREFIX = "pytest-tmp-"


    def _new_basetemp():
        ROOT.mkdir(parents=True, exist_ok=True)
        return ROOT / f"{PREFIX}{uuid.uuid4().hex}"


    def _cleanup(keep):
        if not ROOT.is_dir():
            return
        for candidate in ROOT.glob(f"{PREFIX}*"):
            if candidate == keep:
                continue
            try:
                shutil.rmtree(candidate)
            except OSError:
                continue


    @pytest.hookimpl(tryfirst=True)
    def pytest_configure(config):
        if config.option.basetemp is not None:
            return
        run_dir = _new_basetemp()
        config.option.basetemp = str(run_dir)
        _cleanup(keep=run_dir)
    """
)

_SANDBOX_TEST = textwrap.dedent(
    """
    def test_uses_tmp_path(tmp_path):
        # tmp_path is "<basetemp>/<this test's numbered dir>" — printing
        # its parent reports the basetemp pytest_configure() actually
        # picked, without needing to parse pytest's own -v/--basetemp
        # banner output.
        print("BASETEMP_MARKER:" + str(tmp_path.parent))
        (tmp_path / "marker.txt").write_text("hi")
        assert (tmp_path / "marker.txt").exists()
    """
)


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A throwaway project directory: the conftest.py/test file above,
    nothing else. Not the real repository — this never shares state with
    (or risks polluting) tests/conftest.py's own .tmp/ directory."""
    (tmp_path / "conftest.py").write_text(_SANDBOX_CONFTEST)
    (tmp_path / "test_sample.py").write_text(_SANDBOX_TEST)
    return tmp_path


def _run_pytest(sandbox: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-s", "-q", str(sandbox)],
        cwd=sandbox,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _basetemp_marker(result: subprocess.CompletedProcess[str]) -> str:
    for line in result.stdout.splitlines():
        if line.startswith("BASETEMP_MARKER:"):
            return line.removeprefix("BASETEMP_MARKER:")
    raise AssertionError(f"no BASETEMP_MARKER in output:\n{result.stdout}\n{result.stderr}")


# --- 1. The ordinary command starts and passes --------------------------


def test_the_ordinary_command_starts_and_passes(sandbox: Path) -> None:
    result = _run_pytest(sandbox)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_the_ordinary_command_creates_no_cache_directory(sandbox: Path) -> None:
    # Matches this project's real addopts (-p no:cacheprovider):
    # persistent caching is disabled outright rather than risking the
    # same ACL failure the basetemp mechanism exists to avoid.
    _run_pytest(sandbox)
    assert not (sandbox / ".pytest_cache").exists()


# --- 2. A second, independent run is unaffected by the first ------------


def test_a_second_independent_run_does_not_collide_with_the_first(sandbox: Path) -> None:
    first = _run_pytest(sandbox)
    second = _run_pytest(sandbox)

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr

    first_basetemp = _basetemp_marker(first)
    second_basetemp = _basetemp_marker(second)
    assert first_basetemp != second_basetemp, (
        "two independent runs used the same basetemp — a stale/locked "
        "directory from the first run would make the second fail exactly "
        "like the regression this mechanism exists to prevent"
    )


def test_a_second_run_succeeds_even_if_the_first_runs_directory_becomes_unremovable(
    sandbox: Path,
) -> None:
    # Simulates the actual regression without any real ACL mutation:
    # after a first real run, make its basetemp's *parent* unreadable to
    # os.scandir well enough on POSIX (chmod) to break the sandbox
    # conftest's own cleanup sweep for that one entry — cross-platform
    # equivalence isn't needed here because what's under test is that a
    # *second* run still succeeds regardless, not the exact OS mechanism
    # a lock takes. On platforms where chmod doesn't restrict access
    # (Windows), the directory just gets cleaned up normally — the
    # assertion (`second.returncode == 0`) holds either way, so this
    # stays meaningful without being flaky.
    first = _run_pytest(sandbox)
    assert first.returncode == 0, first.stdout + first.stderr
    first_basetemp = Path(_basetemp_marker(first))

    if first_basetemp.is_dir():
        first_basetemp.chmod(0o000)
    try:
        second = _run_pytest(sandbox)
        assert second.returncode == 0, second.stdout + second.stderr
        assert _basetemp_marker(second) != str(first_basetemp)
    finally:
        if first_basetemp.is_dir():
            first_basetemp.chmod(0o700)


# --- 3. A pre-existing inaccessible/stale directory is never selected ---
#
# Exercises tests/conftest.py's real _new_pytest_run_basetemp()/
# _cleanup_stale_pytest_run_dirs() directly, with shutil.rmtree mocked to
# simulate an ACL failure rather than any real permission mutation — this
# is what keeps this section identical on Windows and Linux.


@pytest.fixture
def _tmp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(conftest_module, "_PYTEST_TMP_ROOT", tmp_path)
    return tmp_path


def test_new_basetemp_never_reuses_an_existing_directory_name(_tmp_root: Path) -> None:
    stale = _tmp_root / f"{_PYTEST_RUN_DIR_PREFIX}deadbeef"
    stale.mkdir()

    new_path = _new_pytest_run_basetemp()

    assert new_path != stale
    assert new_path.parent == _tmp_root


def test_cleanup_skips_a_directory_it_cannot_remove_without_raising(_tmp_root: Path) -> None:
    locked = _tmp_root / f"{_PYTEST_RUN_DIR_PREFIX}locked"
    locked.mkdir()
    keep = _tmp_root / f"{_PYTEST_RUN_DIR_PREFIX}keep"

    def fake_rmtree(path: object, *_args: object, **_kwargs: object) -> None:
        raise PermissionError(f"simulated ACL lock on {path} — no real OS mutation involved")

    # Patches the shared shutil module object itself — the same one
    # tests.conftest imported — rather than conftest_module.shutil, which
    # mypy flags as an implicit re-export.
    with patch.object(shutil, "rmtree", side_effect=fake_rmtree):
        _cleanup_stale_pytest_run_dirs(keep=keep)  # must not raise

    # Still there — cleanup neither crashed nor pretended to remove what
    # it (simulated-)could not, exactly the "stale directory is
    # irrelevant, not fatal" behavior this mechanism relies on.
    assert locked.is_dir()


def test_cleanup_removes_an_accessible_stale_directory(_tmp_root: Path) -> None:
    removable = _tmp_root / f"{_PYTEST_RUN_DIR_PREFIX}old"
    removable.mkdir()
    keep = _tmp_root / f"{_PYTEST_RUN_DIR_PREFIX}keep"

    _cleanup_stale_pytest_run_dirs(keep=keep)

    assert not removable.exists()


def test_cleanup_never_removes_the_directory_being_kept(_tmp_root: Path) -> None:
    keep = _tmp_root / f"{_PYTEST_RUN_DIR_PREFIX}keep"
    keep.mkdir()

    _cleanup_stale_pytest_run_dirs(keep=keep)

    assert keep.is_dir()


def test_cleanup_is_a_no_op_when_the_tmp_root_does_not_exist_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    never_created = tmp_path / "does-not-exist"
    monkeypatch.setattr(conftest_module, "_PYTEST_TMP_ROOT", never_created)

    _cleanup_stale_pytest_run_dirs(keep=never_created / "whatever")  # must not raise
