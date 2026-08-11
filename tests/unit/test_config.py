"""Tests for dnd_ai.config.Settings — namespacing, fail-closed production
startup, and the documented settings-source precedence
(docs/LOCAL_DEPLOYMENT.md, ADR 0012).

Two testing styles are used deliberately:

- Most scenarios construct `Settings`/call `_load_settings()` directly,
  with `monkeypatch` controlling `os.environ` and (where relevant) an
  explicit temporary `env_file` path — fast, and sufficient for anything
  that isn't fixed at class-definition time.
- `secrets_dir` (docs/LOCAL_DEPLOYMENT.md's host-mounted secret files) is
  baked into `Settings.model_config` once, at module-import time, from
  whatever `DND_AI_SECRETS_DIR` happened to be set to then — monkeypatching
  it inside an already-running test process cannot change that. Those
  scenarios, plus the ones this task specifically calls out as needing to
  "reproduce the module-import/startup path, not merely call a helper in
  isolation", spawn a fresh `python -c "import dnd_ai.config"` via
  `_run_config_import()` instead, with a fully isolated environment and
  working directory — never the real repository `.env`.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_ai.config import (
    _APPLICATION_SETTINGS_ENV_VARS,
    _NON_APPLICATION_DND_AI_ENV_VARS,
    Settings,
    _load_settings,
    _reject_unrecognized_env_vars,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_database_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DND_AI_DATABASE_URL", raising=False)


# ---------------------------------------------------------------------------
# database_url resolution and precedence (in-process — none of this depends
# on class-definition-time state)
# ---------------------------------------------------------------------------


def test_defaults_to_local_dev_database_url_when_unset() -> None:
    settings = Settings()
    assert settings.environment == "local"
    assert settings.database_url == "postgresql+psycopg://postgres:postgres@localhost:5432/dnd_ai"


def test_test_environment_also_gets_the_local_dev_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "test")
    settings = Settings()
    assert settings.database_url == "postgresql+psycopg://postgres:postgres@localhost:5432/dnd_ai"


def test_accepts_prefixed_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_DATABASE_URL", "postgresql+psycopg://a:b@prefixed/db")
    assert Settings().database_url == "postgresql+psycopg://a:b@prefixed/db"


def test_accepts_legacy_unprefixed_database_url_alias_outside_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://a:b@legacy/db")
    assert Settings().database_url == "postgresql+psycopg://a:b@legacy/db"


def test_prefixed_database_url_takes_precedence_over_legacy_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DND_AI_DATABASE_URL", "postgresql+psycopg://a:b@prefixed/db")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://a:b@legacy/db")
    assert Settings().database_url == "postgresql+psycopg://a:b@prefixed/db"


def test_rejects_invalid_environment_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "prod")  # not the literal "production"
    with pytest.raises(ValidationError):
        Settings()


# ---------------------------------------------------------------------------
# Production fail-closed behavior (finding 1) — in-process
# ---------------------------------------------------------------------------


def test_production_without_database_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    with pytest.raises(ValidationError, match="DND_AI_DATABASE_URL"):
        Settings()


def test_production_with_prefixed_database_url_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    monkeypatch.setenv("DND_AI_DATABASE_URL", "postgresql+psycopg://prod:prod@dbhost/dnd_ai")
    settings = Settings()
    assert settings.environment == "production"
    assert settings.database_url == "postgresql+psycopg://prod:prod@dbhost/dnd_ai"


def test_production_with_only_legacy_database_url_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """finding 5, scenario (d): a bare DATABASE_URL — even set as a real
    environment variable, not via .env — must not satisfy production. The
    validator never consults legacy_database_url once environment is
    production; it isn't a matter of one source beating another here."""
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://legacy:legacy@dbhost/dnd_ai")
    with pytest.raises(ValidationError, match="DND_AI_DATABASE_URL"):
        Settings()


# ---------------------------------------------------------------------------
# _load_settings() — the .env loading decision itself (in-process, using an
# isolated temporary dotenv file — never the repository's real .env)
# ---------------------------------------------------------------------------


def test_load_settings_reads_explicit_env_file_outside_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "local")
    env_file = tmp_path / "isolated.env"
    env_file.write_text(
        "DND_AI_DATABASE_URL=postgresql+psycopg://a:b@fromfile/db\n", encoding="utf-8"
    )
    settings = _load_settings(env_file=env_file)
    assert settings.database_url == "postgresql+psycopg://a:b@fromfile/db"


def test_load_settings_ignores_explicit_env_file_in_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    env_file = tmp_path / "isolated.env"
    env_file.write_text(
        "DATABASE_URL=postgresql+psycopg://dev:dev@localhost/dnd_ai\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="DND_AI_DATABASE_URL"):
        _load_settings(env_file=env_file)


# ---------------------------------------------------------------------------
# Namespace boundary (finding 2) — application settings vs. other
# subsystems' DND_AI_* variables, in-process
# ---------------------------------------------------------------------------


def test_unrelated_shared_env_vars_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # AWS_REGION/AWS_PROFILE live in the same .env for the AWS CLI/Terraform,
    # not this model — see docs/LOCAL_DEPLOYMENT.md and the module docstring.
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_PROFILE", "dnd-ai-dev")
    Settings()  # must not raise
    _reject_unrecognized_env_vars()  # must not raise


@pytest.mark.parametrize(
    "name,value",
    [
        ("DND_AI_TEST_DATABASE_URL", "postgresql+psycopg://ci:ci@ci-host/dnd_ai_ci_abc"),
        ("DND_AI_CI_DB_NAME", "dnd_ai_ci_abc123"),
        ("DND_AI_SEEDS_DIR", "/some/override/path"),
    ],
)
def test_non_application_dnd_ai_variables_do_not_raise(
    name: str, value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(name, value)
    Settings()  # must not raise
    _reject_unrecognized_env_vars()  # must not raise


def test_unrecognized_application_env_var_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_DATABAWSE_URL", "typo")
    with pytest.raises(RuntimeError, match="DND_AI_DATABAWSE_URL"):
        _reject_unrecognized_env_vars()


def test_misspelled_non_application_variable_is_also_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The allowlist is closed, not "allow anything DND_AI_*" — a typo of a
    known non-application variable is still caught."""
    monkeypatch.setenv("DND_AI_TEST_DATABSE_URL", "typo")
    with pytest.raises(RuntimeError, match="DND_AI_TEST_DATABSE_URL"):
        _reject_unrecognized_env_vars()


def test_application_settings_env_vars_matches_declared_fields() -> None:
    """Guards _APPLICATION_SETTINGS_ENV_VARS against drifting away from the
    fields it exists to protect (docs/DEVELOPMENT.md §2.1's established
    metadata-completeness pattern). legacy_database_url is excluded from
    the automatic prefix-derived name because its validation_alias replaces
    that convention entirely — it is DATABASE_URL, already covered below."""
    expected = {
        f"DND_AI_{name.upper()}" for name in Settings.model_fields if name != "legacy_database_url"
    }
    expected |= {"DATABASE_URL", "DND_AI_SECRETS_DIR"}
    assert expected == _APPLICATION_SETTINGS_ENV_VARS
    assert _APPLICATION_SETTINGS_ENV_VARS.isdisjoint(_NON_APPLICATION_DND_AI_ENV_VARS)


# ---------------------------------------------------------------------------
# The real module-import/startup path, in an isolated subprocess — never
# the developer's actual .env, never a helper called in isolation.
# ---------------------------------------------------------------------------

_CONFIG_IMPORT_PROBE = (
    "import json\n"
    "import dnd_ai.config as config\n"
    "print(json.dumps({'environment': config.settings.environment, "
    "'database_url': config.settings.database_url}))\n"
)

# Every variable any test in this file (or dnd_ai.config itself) cares
# about — cleared unconditionally before applying a scenario's overrides, so
# nothing this subprocess's parent happens to have set (e.g. this pytest
# session's own DATABASE_URL) leaks into the isolated run.
_ALL_TEST_MANAGED_ENV_VARS = (
    "DND_AI_ENVIRONMENT",
    "DND_AI_LOG_LEVEL",
    "DND_AI_DATABASE_URL",
    "DATABASE_URL",
    "DND_AI_FEATURE_AI_NPC_DIALOGUE",
    "DND_AI_FEATURE_DISCORD_INTEGRATION",
    "DND_AI_FEATURE_FOUNDRY_INTEGRATION",
    "DND_AI_SECRETS_DIR",
    "DND_AI_TEST_DATABASE_URL",
    "DND_AI_CI_DB_NAME",
    "DND_AI_SEEDS_DIR",
)


def _run_config_import(
    env_overrides: dict[str, str], *, cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Spawn `python -c "import dnd_ai.config"` fresh — the actual
    module-import/startup path, not `_load_settings()` called directly.
    `sys.executable` is this same test run's interpreter (the project venv,
    with `dnd_ai` installed), so no extra setup is needed for the import to
    succeed. `cwd` isolates `.env` discovery (`dnd_ai.config` resolves it as
    `<cwd>/.env`, an explicit path — never a frame/search-based default) from
    the real repository checkout; it is always a pytest `tmp_path`, never
    this repository's own directory.
    """
    env = os.environ.copy()
    for name in _ALL_TEST_MANAGED_ENV_VARS:
        env.pop(name, None)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", _CONFIG_IMPORT_PROBE],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_import_path_succeeds_with_ci_test_database_url_preset(tmp_path: Path) -> None:
    """Verification requirement: exercise the pre-provisioned CI
    configuration path with DND_AI_TEST_DATABASE_URL already set before
    importing application modules — scripts/ci_ephemeral_database.py sets
    exactly this (plus DND_AI_CI_DB_NAME) for every later CI step,
    including the pytest run itself."""
    result = _run_config_import(
        {
            "DND_AI_TEST_DATABASE_URL": "postgresql+psycopg://ci:ci@ci-host/dnd_ai_ci_abc123",
            "DND_AI_CI_DB_NAME": "dnd_ai_ci_abc123",
        },
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["environment"] == "local"


def test_import_path_succeeds_with_seeds_dir_override(tmp_path: Path) -> None:
    result = _run_config_import({"DND_AI_SEEDS_DIR": str(tmp_path)}, cwd=tmp_path)
    assert result.returncode == 0, result.stderr


def test_import_path_fails_on_misspelled_application_setting(tmp_path: Path) -> None:
    result = _run_config_import({"DND_AI_DATABAWSE_URL": "typo"}, cwd=tmp_path)
    assert result.returncode != 0
    assert "DND_AI_DATABAWSE_URL" in result.stderr


def test_production_ignores_developer_env_file_and_fails_closed(tmp_path: Path) -> None:
    """finding 1/5: a normal repository-style .env, sitting right where
    dnd_ai.config would otherwise look for it, must not satisfy production
    startup — because production never reads it in the first place."""
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql+psycopg://dev:dev@localhost/dnd_ai\n", encoding="utf-8"
    )
    result = _run_config_import({"DND_AI_ENVIRONMENT": "production"}, cwd=tmp_path)
    assert result.returncode != 0
    assert "DND_AI_DATABASE_URL" in result.stderr


def test_production_succeeds_with_mounted_secret_file(tmp_path: Path) -> None:
    """finding 1: the documented mounted-secret path — a file named exactly
    dnd_ai_database_url under DND_AI_SECRETS_DIR — satisfies production
    startup exactly like the environment variable does."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "dnd_ai_database_url").write_text(
        "postgresql+psycopg://prod:prod@dbhost/dnd_ai", encoding="utf-8"
    )
    result = _run_config_import(
        {"DND_AI_ENVIRONMENT": "production", "DND_AI_SECRETS_DIR": str(secrets_dir)},
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["database_url"] == "postgresql+psycopg://prod:prod@dbhost/dnd_ai"
