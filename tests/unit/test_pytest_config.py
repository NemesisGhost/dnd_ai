"""Source-level regression coverage for pyproject.toml's pytest tmp/cache
directory configuration.

A bare `.pytest_tmp`/the default `.pytest_cache` at the repo root can end
up owned by an ACL a later session can neither read, write, nor take
ownership of (observed on at least one Windows development sandbox — see
the comment on `[tool.pytest.ini_options]` in pyproject.toml itself) —
silently masking every tmp_path-dependent test's real result behind a
fixture-teardown PermissionError rather than that test's own assertions.
Parses the committed pyproject.toml directly (no live pytest invocation,
matching tests/unit/test_compose_files.py's approach for compose.yaml) so
a reversion to the poisoned paths is caught here, fast, before it ever
reaches a real test run.
"""

import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_LEGACY_LOCKED_BASETEMP = ".pytest_tmp"
_LEGACY_LOCKED_CACHE_DIR = ".pytest_cache"
_WORKSPACE_TMP_PREFIX = ".tmp/"


def _pytest_ini_options() -> dict[str, object]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        data = tomllib.load(f)
    options = data["tool"]["pytest"]["ini_options"]
    assert isinstance(options, dict)
    return options


def _basetemp() -> str:
    options = _pytest_ini_options()
    addopts = options["addopts"]
    assert isinstance(addopts, list)
    for opt in addopts:
        assert isinstance(opt, str)
        if opt.startswith("--basetemp="):
            return opt.removeprefix("--basetemp=")
    raise AssertionError("addopts has no --basetemp= entry")


def _cache_dir() -> str:
    cache_dir = _pytest_ini_options()["cache_dir"]
    assert isinstance(cache_dir, str)
    return cache_dir


def test_basetemp_is_under_the_workspace_tmp_directory() -> None:
    assert _basetemp().replace("\\", "/").startswith(_WORKSPACE_TMP_PREFIX)


def test_basetemp_does_not_point_at_the_legacy_locked_directory() -> None:
    assert _basetemp() != _LEGACY_LOCKED_BASETEMP


def test_cache_dir_is_under_the_workspace_tmp_directory() -> None:
    assert _cache_dir().replace("\\", "/").startswith(_WORKSPACE_TMP_PREFIX)


def test_cache_dir_does_not_point_at_the_legacy_locked_directory() -> None:
    assert _cache_dir() not in {_LEGACY_LOCKED_CACHE_DIR, f"./{_LEGACY_LOCKED_CACHE_DIR}"}


def test_basetemp_and_cache_dir_are_distinct_paths() -> None:
    # Sharing one directory would let pytest's own cache files end up
    # inside a basetemp it clears at the start of every session, or vice
    # versa — keep them independent, as configured.
    assert _basetemp() != _cache_dir()


def test_workspace_tmp_directory_is_gitignored() -> None:
    # Belt-and-suspenders for the actual requirement: both generated
    # paths must never be committed. .gitignore's existing `.tmp/` rule
    # already covers any path under it, including both of the above.
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert _WORKSPACE_TMP_PREFIX in gitignore.replace("\\", "/")
