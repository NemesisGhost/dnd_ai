"""Tests for dnd_ai.config.Settings — namespacing, fail-safes, and the
no-silent-production-fallback rule (docs/LOCAL_DEPLOYMENT.md, ADR 0012).

These construct `Settings` directly rather than using the module-level
`dnd_ai.config.settings` singleton, and delete both `DATABASE_URL` and
`DND_AI_DATABASE_URL` from the environment first — the repo's own `.env`
normally supplies one, and `dnd_ai.config`'s module-level `load_dotenv()`
has already run by the time these tests execute (tests/conftest.py imports
it too), so a test that wants to see the "unset" case has to remove it
explicitly rather than relying on it never having been loaded.
"""

import pytest
from pydantic import ValidationError

from dnd_ai.config import _KNOWN_APPLICATION_ENV_VARS, Settings, _reject_unrecognized_env_vars

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_database_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DND_AI_DATABASE_URL", raising=False)


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


def test_accepts_legacy_unprefixed_database_url_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://a:b@legacy/db")
    assert Settings().database_url == "postgresql+psycopg://a:b@legacy/db"


def test_prefixed_database_url_takes_precedence_over_legacy_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DND_AI_DATABASE_URL", "postgresql+psycopg://a:b@prefixed/db")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://a:b@legacy/db")
    assert Settings().database_url == "postgresql+psycopg://a:b@prefixed/db"


def test_production_without_database_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    with pytest.raises(ValidationError, match="DND_AI_DATABASE_URL"):
        Settings()


def test_production_with_database_url_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "production")
    monkeypatch.setenv("DND_AI_DATABASE_URL", "postgresql+psycopg://prod:prod@dbhost/dnd_ai")
    settings = Settings()
    assert settings.environment == "production"
    assert settings.database_url == "postgresql+psycopg://prod:prod@dbhost/dnd_ai"


def test_rejects_invalid_environment_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_ENVIRONMENT", "prod")  # not the literal "production"
    with pytest.raises(ValidationError):
        Settings()


def test_unrelated_shared_env_vars_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # AWS_REGION/AWS_PROFILE live in the same .env for the AWS CLI/Terraform,
    # not this model — see docs/LOCAL_DEPLOYMENT.md and the module docstring.
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_PROFILE", "dnd-ai-dev")
    Settings()  # must not raise
    _reject_unrecognized_env_vars()  # must not raise


def test_unrecognized_application_env_var_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DND_AI_DATABAWSE_URL", "typo")
    with pytest.raises(RuntimeError, match="DND_AI_DATABAWSE_URL"):
        _reject_unrecognized_env_vars()


def test_known_application_env_vars_matches_declared_fields() -> None:
    """Guards _KNOWN_APPLICATION_ENV_VARS against drifting away from the
    fields it exists to protect (docs/DEVELOPMENT.md §2.1's established
    metadata-completeness pattern)."""
    expected = {f"DND_AI_{name.upper()}" for name in Settings.model_fields}
    # database_url's extra legacy alias, and the pre-Settings DND_AI_SECRETS_DIR
    # knob, are documented exceptions this check doesn't derive automatically.
    expected |= {"DATABASE_URL", "DND_AI_SECRETS_DIR"}
    assert expected == _KNOWN_APPLICATION_ENV_VARS
