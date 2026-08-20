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
    PRODUCTION_REQUIRED_DATABASE_ROLE,
    Settings,
    _load_settings,
    _reject_unrecognized_env_vars,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_database_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DND_AI_DATABASE_URL", raising=False)


@pytest.fixture(autouse=True)
def _clear_oidc_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DND_AI_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("DND_AI_OIDC_AUDIENCE", raising=False)
    monkeypatch.delenv("DND_AI_OIDC_JWKS_URL", raising=False)


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
    monkeypatch.setenv(
        "DND_AI_DATABASE_URL", "postgresql+psycopg://app_read_write:prod@dbhost/dnd_ai"
    )
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    settings = Settings()
    assert settings.environment == "production"
    assert settings.database_url == "postgresql+psycopg://app_read_write:prod@dbhost/dnd_ai"


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
# database_url identity — production must connect as app_read_write, never
# postgres/migration_runner/migration_owner (in-process). This is the
# static half of the enforcement only: it proves what the configured URL
# *claims*; tests/database/test_database_identity_enforcement.py proves
# what a real connection actually authenticates as.
# ---------------------------------------------------------------------------


def test_production_rejects_the_postgres_superuser_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    monkeypatch.setenv("DND_AI_DATABASE_URL", "postgresql+psycopg://postgres:prod@dbhost/dnd_ai")
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    with pytest.raises(ValidationError, match="app_read_write"):
        Settings()


def test_production_rejects_the_migration_runner_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "DND_AI_DATABASE_URL", "postgresql+psycopg://migration_runner:prod@dbhost/dnd_ai"
    )
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    with pytest.raises(ValidationError, match="app_read_write"):
        Settings()


def test_production_rejects_the_migration_owner_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """migration_owner is NOLOGIN (001_bootstrap) so a real connection could
    never actually use it — this only proves the URL-identity check itself
    rejects the name, independent of whether PostgreSQL would also refuse
    the login."""
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "DND_AI_DATABASE_URL", "postgresql+psycopg://migration_owner:prod@dbhost/dnd_ai"
    )
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    with pytest.raises(ValidationError, match="app_read_write"):
        Settings()


def test_production_accepts_the_app_read_write_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    assert PRODUCTION_REQUIRED_DATABASE_ROLE == "app_read_write"
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "DND_AI_DATABASE_URL", "postgresql+psycopg://app_read_write:prod@dbhost/dnd_ai"
    )
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    settings = Settings()
    assert settings.database_url == "postgresql+psycopg://app_read_write:prod@dbhost/dnd_ai"


def test_the_identity_check_does_not_apply_outside_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """local/test intentionally connect as the postgres admin credential —
    this check must never fire there."""
    monkeypatch.setenv("DND_AI_DATABASE_URL", "postgresql+psycopg://postgres:postgres@dbhost/db")
    settings = Settings()  # must not raise
    assert settings.environment == "local"


def test_production_rejects_an_unparseable_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    monkeypatch.setenv("DND_AI_DATABASE_URL", "not a valid url::: at all")
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    with pytest.raises(ValidationError, match="DND_AI_DATABASE_URL"):
        Settings()


def test_the_identity_check_failure_never_leaks_the_url_or_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requirement: the failure contract must not leak credentials or the
    database URL — only the fixed expected-role literal may appear."""
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "DND_AI_DATABASE_URL",
        "postgresql+psycopg://postgres:super-secret-password@dbhost/dnd_ai",
    )
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    message = str(excinfo.value)
    assert "super-secret-password" not in message
    assert "dbhost" not in message


# ---------------------------------------------------------------------------
# OIDC settings — production fail-closed behavior, mirroring database_url
# (in-process)
# ---------------------------------------------------------------------------


def test_oidc_settings_default_to_none_outside_production() -> None:
    settings = Settings()
    assert settings.oidc_issuer is None
    assert settings.oidc_audience is None
    assert settings.oidc_jwks_url is None


def test_production_without_oidc_settings_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "DND_AI_DATABASE_URL", "postgresql+psycopg://app_read_write:prod@dbhost/dnd_ai"
    )
    with pytest.raises(ValidationError, match="DND_AI_OIDC_ISSUER"):
        Settings()


@pytest.mark.parametrize(
    "present_fields",
    [
        {"DND_AI_OIDC_ISSUER": "https://idp.example"},
        {"DND_AI_OIDC_ISSUER": "https://idp.example", "DND_AI_OIDC_AUDIENCE": "dnd-ai-api"},
        {"DND_AI_OIDC_AUDIENCE": "dnd-ai-api", "DND_AI_OIDC_JWKS_URL": "https://idp.example/jwks"},
    ],
)
def test_production_with_partial_oidc_settings_raises(
    present_fields: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "DND_AI_DATABASE_URL", "postgresql+psycopg://app_read_write:prod@dbhost/dnd_ai"
    )
    for name, value in present_fields.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_production_with_all_oidc_settings_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "DND_AI_DATABASE_URL", "postgresql+psycopg://app_read_write:prod@dbhost/dnd_ai"
    )
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/.well-known/jwks.json")
    settings = Settings()
    assert settings.oidc_issuer == "https://idp.example"
    assert settings.oidc_audience == "dnd-ai-api"
    assert settings.oidc_jwks_url == "https://idp.example/.well-known/jwks.json"


# ---------------------------------------------------------------------------
# OIDC settings — production URL/audience structural validation. A
# plain-HTTP JWKS endpoint lets a network-positioned attacker substitute
# the key set and forge tokens, so production requires HTTPS, a host, no
# embedded credentials, and no fragment on both URL fields, and a
# whitespace-clean, non-empty audience — all in-process.
# ---------------------------------------------------------------------------

_PRODUCTION_ENV = {
    "DND_AI_ENVIRONMENT": "production",
    "DND_AI_DATABASE_URL": "postgresql+psycopg://app_read_write:prod@dbhost/dnd_ai",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_production_rejects_http_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, _PRODUCTION_ENV)
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "http://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    with pytest.raises(ValidationError, match="DND_AI_OIDC_ISSUER"):
        Settings()


def test_production_rejects_http_jwks_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, _PRODUCTION_ENV)
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "http://idp.example/jwks")
    with pytest.raises(ValidationError, match="DND_AI_OIDC_JWKS_URL"):
        Settings()


@pytest.mark.parametrize("bad_value", ["", "   ", " dnd-ai-api", "dnd-ai-api "])
def test_production_rejects_empty_or_whitespace_padded_audience(
    bad_value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, _PRODUCTION_ENV)
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", bad_value)
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    with pytest.raises(ValidationError, match="DND_AI_OIDC_AUDIENCE"):
        Settings()


@pytest.mark.parametrize(
    "bad_url",
    [
        "not-a-url",
        "https://",
        "https:///path-no-host",
        "https://[invalid/jwks",
    ],
)
def test_production_rejects_malformed_or_missing_host_issuer(
    bad_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, _PRODUCTION_ENV)
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", bad_url)
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    with pytest.raises(ValidationError, match="DND_AI_OIDC_ISSUER"):
        Settings()


def test_production_rejects_embedded_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, _PRODUCTION_ENV)
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://user:pass@idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    with pytest.raises(ValidationError, match="DND_AI_OIDC_ISSUER"):
        Settings()


def test_production_rejects_url_fragment(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, _PRODUCTION_ENV)
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks#frag")
    with pytest.raises(ValidationError, match="DND_AI_OIDC_JWKS_URL"):
        Settings()


def test_production_issuer_is_never_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    """JWT issuer matching must stay exact — a trailing slash must survive
    validation unchanged, never silently added or stripped, since that
    would change what a token's `iss` claim is compared against."""
    _set_env(monkeypatch, _PRODUCTION_ENV)
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example/")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    settings = Settings()
    assert settings.oidc_issuer == "https://idp.example/"


# ---------------------------------------------------------------------------
# OIDC settings — local/test policy: HTTP permitted for a private/in-
# process test identity provider, but partial or structurally malformed
# configuration is still rejected (docs: dnd_ai.config's own module
# docstring, "Local/test may configure an HTTP identity provider...").
# ---------------------------------------------------------------------------


def test_local_allows_http_oidc_urls_when_fully_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "http://localhost:8080/realms/test")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "http://localhost:8080/realms/test/jwks")
    settings = Settings()
    assert settings.oidc_issuer == "http://localhost:8080/realms/test"
    assert settings.oidc_jwks_url == "http://localhost:8080/realms/test/jwks"


def test_local_still_rejects_malformed_oidc_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "not-a-url")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "http://localhost:8080/jwks")
    with pytest.raises(ValidationError, match="DND_AI_OIDC_ISSUER"):
        Settings()


def test_local_still_rejects_empty_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "http://localhost:8080/realms/test")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "http://localhost:8080/realms/test/jwks")
    with pytest.raises(ValidationError, match="DND_AI_OIDC_AUDIENCE"):
        Settings()


def test_local_still_rejects_embedded_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "http://user:pass@localhost:8080/realms/test")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "http://localhost:8080/realms/test/jwks")
    with pytest.raises(ValidationError, match="DND_AI_OIDC_ISSUER"):
        Settings()


@pytest.mark.parametrize(
    "present_fields",
    [
        {"DND_AI_OIDC_ISSUER": "http://localhost:8080/realms/test"},
        {
            "DND_AI_OIDC_ISSUER": "http://localhost:8080/realms/test",
            "DND_AI_OIDC_AUDIENCE": "dnd-ai-api",
        },
    ],
)
def test_local_rejects_partial_oidc_configuration(
    present_fields: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in present_fields.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
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
    "DND_AI_OIDC_ISSUER",
    "DND_AI_OIDC_AUDIENCE",
    "DND_AI_OIDC_JWKS_URL",
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
        "postgresql+psycopg://app_read_write:prod@dbhost/dnd_ai", encoding="utf-8"
    )
    result = _run_config_import(
        {
            "DND_AI_ENVIRONMENT": "production",
            "DND_AI_SECRETS_DIR": str(secrets_dir),
            "DND_AI_OIDC_ISSUER": "https://idp.example",
            "DND_AI_OIDC_AUDIENCE": "dnd-ai-api",
            "DND_AI_OIDC_JWKS_URL": "https://idp.example/jwks",
        },
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["database_url"] == "postgresql+psycopg://app_read_write:prod@dbhost/dnd_ai"


# ---------------------------------------------------------------------------
# The five scenarios finding 1 (correction pass) lists explicitly, all via
# the real module-import path — this is exactly the bug that pass fixes: a
# process whose real environment never asked for production could
# previously be promoted into it by .env alone.
# ---------------------------------------------------------------------------


def test_process_environment_selects_production_env_file_is_ignored(tmp_path: Path) -> None:
    """The real environment's own DND_AI_DATABASE_URL wins even when a
    present .env sets a *different* one — proving the file is genuinely
    never read in production, not merely that its absence is harmless."""
    (tmp_path / ".env").write_text(
        "DND_AI_DATABASE_URL=postgresql+psycopg://from-file:from-file@dbhost/dnd_ai\n",
        encoding="utf-8",
    )
    result = _run_config_import(
        {
            "DND_AI_ENVIRONMENT": "production",
            "DND_AI_DATABASE_URL": "postgresql+psycopg://app_read_write:from-real-env@dbhost/dnd_ai",
            "DND_AI_OIDC_ISSUER": "https://idp.example",
            "DND_AI_OIDC_AUDIENCE": "dnd-ai-api",
            "DND_AI_OIDC_JWKS_URL": "https://idp.example/jwks",
        },
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["database_url"] == (
        "postgresql+psycopg://app_read_write:from-real-env@dbhost/dnd_ai"
    )


def test_env_file_alone_selecting_production_fails_startup(tmp_path: Path) -> None:
    """The bug this correction pass fixes: a real process environment that
    never mentions DND_AI_ENVIRONMENT at all must not end up in production
    merely because .env says so. Startup must fail loudly, not start in
    production sourced entirely from a developer convenience file."""
    (tmp_path / ".env").write_text(
        "DND_AI_ENVIRONMENT=production\n"
        "DND_AI_DATABASE_URL=postgresql+psycopg://from-file:from-file@dbhost/dnd_ai\n",
        encoding="utf-8",
    )
    result = _run_config_import({}, cwd=tmp_path)
    assert result.returncode != 0
    assert "production" in result.stderr.lower()
    assert ".env" in result.stderr
    # The failure must not itself leak the credential .env supplied.
    assert "from-file" not in result.stderr


def test_env_file_selecting_local_or_test_is_accepted(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DND_AI_ENVIRONMENT=test\n", encoding="utf-8")
    result = _run_config_import({}, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["environment"] == "test"


def test_production_with_real_environment_plus_mounted_secret_is_accepted(
    tmp_path: Path,
) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "dnd_ai_database_url").write_text(
        "postgresql+psycopg://app_read_write:prod@dbhost/dnd_ai", encoding="utf-8"
    )
    result = _run_config_import(
        {
            "DND_AI_ENVIRONMENT": "production",
            "DND_AI_SECRETS_DIR": str(secrets_dir),
            "DND_AI_OIDC_ISSUER": "https://idp.example",
            "DND_AI_OIDC_AUDIENCE": "dnd-ai-api",
            "DND_AI_OIDC_JWKS_URL": "https://idp.example/jwks",
        },
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["environment"] == "production"
    assert payload["database_url"] == "postgresql+psycopg://app_read_write:prod@dbhost/dnd_ai"


# ---------------------------------------------------------------------------
# foundry_allowed_origins — the CORS allowlist for the FoundryVTT module's
# browser-origin requests (Issue 1, transport-layer correction). Mirrors the
# OIDC settings' shape: production requires HTTPS on every origin, and (only
# when the Foundry feature flag is also on) requires the setting to be
# present at all; local/test also permit HTTP and never require it.
# ---------------------------------------------------------------------------


def test_foundry_allowed_origins_defaults_to_none_outside_production() -> None:
    settings = Settings()
    assert settings.foundry_allowed_origins is None


def test_production_without_foundry_integration_does_not_require_allowed_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, _PRODUCTION_ENV)
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    settings = Settings()  # must not raise — feature_foundry_integration defaults False
    assert settings.foundry_allowed_origins is None


def test_production_with_foundry_integration_enabled_requires_allowed_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, _PRODUCTION_ENV)
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    monkeypatch.setenv("DND_AI_FEATURE_FOUNDRY_INTEGRATION", "true")
    with pytest.raises(ValidationError, match="DND_AI_FOUNDRY_ALLOWED_ORIGINS"):
        Settings()


def test_production_with_foundry_integration_enabled_accepts_a_configured_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, _PRODUCTION_ENV)
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    monkeypatch.setenv("DND_AI_FEATURE_FOUNDRY_INTEGRATION", "true")
    monkeypatch.setenv("DND_AI_FOUNDRY_ALLOWED_ORIGINS", "https://foundry.example.com")
    settings = Settings()
    assert settings.foundry_allowed_origins == "https://foundry.example.com"


def test_a_blank_foundry_allowed_origins_value_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose interpolating an unset host variable to an empty string
    (`${VAR:-}`) must not be a validation error — it means "not
    configured," identically to the variable being absent."""
    monkeypatch.setenv("DND_AI_FOUNDRY_ALLOWED_ORIGINS", "")
    settings = Settings()
    assert settings.foundry_allowed_origins is None


def test_foundry_allowed_origins_rejects_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_FOUNDRY_ALLOWED_ORIGINS", "*")
    with pytest.raises(ValidationError, match="wildcard"):
        Settings()


def test_foundry_allowed_origins_rejects_wildcarded_subdomain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DND_AI_FOUNDRY_ALLOWED_ORIGINS", "https://*.example.com")
    with pytest.raises(ValidationError, match="wildcard"):
        Settings()


def test_foundry_allowed_origins_rejects_http_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, _PRODUCTION_ENV)
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/jwks")
    monkeypatch.setenv("DND_AI_FOUNDRY_ALLOWED_ORIGINS", "http://foundry.example.com")
    with pytest.raises(ValidationError, match="https"):
        Settings()


def test_foundry_allowed_origins_permits_http_outside_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DND_AI_FOUNDRY_ALLOWED_ORIGINS", "http://localhost:30000")
    settings = Settings()
    assert settings.foundry_allowed_origins == "http://localhost:30000"


@pytest.mark.parametrize(
    "bad_origin",
    [
        "https://foundry.example.com/some-path",
        "https://foundry.example.com?query=1",
        "https://foundry.example.com#frag",
        "https://user:pass@foundry.example.com",
        "not-a-url",
        "ftp://foundry.example.com",
    ],
)
def test_foundry_allowed_origins_rejects_malformed_entries(
    bad_origin: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DND_AI_FOUNDRY_ALLOWED_ORIGINS", bad_origin)
    with pytest.raises(ValidationError, match="DND_AI_FOUNDRY_ALLOWED_ORIGINS"):
        Settings()


def test_foundry_allowed_origins_normalizes_default_port_and_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DND_AI_FOUNDRY_ALLOWED_ORIGINS",
        "HTTPS://Foundry.Example.com:443, https://foundry.example.com, https://other.example.com:8443",
    )
    settings = Settings()
    assert settings.foundry_allowed_origins == (
        "https://foundry.example.com,https://other.example.com:8443"
    )


def test_production_with_only_legacy_database_url_is_rejected(tmp_path: Path) -> None:
    result = _run_config_import(
        {
            "DND_AI_ENVIRONMENT": "production",
            "DATABASE_URL": "postgresql+psycopg://legacy:legacy@dbhost/dnd_ai",
        },
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "DND_AI_DATABASE_URL" in result.stderr


# ---------------------------------------------------------------------------
# ai_provider_api_key / ai_provider_base_url (dnd_ai.domain.ai_provider.
# OpenAiCompatibleProvider) — required only in production, only for the
# real hosted OpenAI default, and only once feature_ai_npc_dialogue is on.
# ---------------------------------------------------------------------------


def _production_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "DND_AI_DATABASE_URL", "postgresql+psycopg://app_read_write:prod@dbhost/dnd_ai"
    )
    monkeypatch.setenv("DND_AI_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("DND_AI_OIDC_AUDIENCE", "dnd-ai-api")
    monkeypatch.setenv("DND_AI_OIDC_JWKS_URL", "https://idp.example/.well-known/jwks.json")


def test_ai_provider_defaults_to_real_openai_with_no_key_required_outside_production() -> None:
    settings = Settings()
    assert settings.ai_provider_base_url == "https://api.openai.com/v1"
    assert settings.ai_provider_api_key is None


def test_production_with_dialogue_feature_on_and_no_key_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production_env(monkeypatch)
    monkeypatch.setenv("DND_AI_FEATURE_AI_NPC_DIALOGUE", "true")
    with pytest.raises(ValidationError, match="DND_AI_AI_PROVIDER_API_KEY"):
        Settings()


def test_production_with_dialogue_feature_on_and_a_key_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production_env(monkeypatch)
    monkeypatch.setenv("DND_AI_FEATURE_AI_NPC_DIALOGUE", "true")
    monkeypatch.setenv("DND_AI_AI_PROVIDER_API_KEY", "sk-test-key")
    settings = Settings()
    assert settings.ai_provider_api_key == "sk-test-key"


def test_production_with_dialogue_feature_on_and_a_local_base_url_needs_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production_env(monkeypatch)
    monkeypatch.setenv("DND_AI_FEATURE_AI_NPC_DIALOGUE", "true")
    monkeypatch.setenv("DND_AI_AI_PROVIDER_BASE_URL", "http://model-server.internal:8000/v1")
    settings = Settings()
    assert settings.ai_provider_api_key is None
    assert settings.ai_provider_base_url == "http://model-server.internal:8000/v1"


def test_production_with_dialogue_feature_off_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _production_env(monkeypatch)
    settings = Settings()
    assert settings.ai_provider_api_key is None
