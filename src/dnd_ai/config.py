"""Application configuration (docs/LOCAL_DEPLOYMENT.md, ADR 0012).

Every application-owned field is namespaced under the `DND_AI_`
environment-variable prefix so this model never collides with, or silently
absorbs, unrelated variables the host process carries for other tooling —
the AWS CLI, Terraform, Docker Compose itself (`DND_AI_TEST_DATABASE_URL`
already established this prefix for the test harness; see
tests/conftest.py).

`.env` is loaded through `python-dotenv`'s `load_dotenv()` into the process
environment — the same mechanism tests/conftest.py already uses — rather
than through pydantic-settings' own `env_file` file-parsing. That choice
matters: pydantic-settings' dotenv source reads a file as one flat dict, so
every key in it (prefixed or not) becomes a candidate field and an
unprefixed shared key like `AWS_REGION` would trip `extra="forbid"`; its
plain environment-variable source, by contrast, looks up only each field's
own expected name and silently ignores everything else. Routing `.env`
through `os.environ` gets namespacing for free without a second config
file. `_reject_unrecognized_env_vars()` then closes the resulting gap —
since ignoring extras silently is also what would let a genuine
`DND_AI_DATABAWSE_URL` typo through unnoticed — by scanning `os.environ`
itself for any `DND_AI_*` name that isn't a field this module knows about,
covering both a typo added directly to `.env` and one exported into the
shell or a container's `environment:` block.

`database_url` is the one deliberate unprefixed exception: it additionally
accepts the pervasive `DATABASE_URL` already used throughout this repo by
Alembic, pytest, and CI (docs/DEVELOPMENT.md §3, §8) so a local developer's
existing `.env` keeps working for the application too, without requiring
the same value under two different names. Production is expected to supply
`DND_AI_DATABASE_URL` explicitly (typically via a Compose secret/env file,
docs/LOCAL_DEPLOYMENT.md "Compose responsibilities and network policy") —
see `_require_explicit_database_url_outside_local_dev` for why there is no
silent fallback once `environment` is not `local`/`test`.

Host-mounted secret files (same LOCAL_DEPLOYMENT.md section — "credentials
in host-readable environment/secret files or mounted secrets outside the
repository") are read from `DND_AI_SECRETS_DIR` (default `/run/secrets`,
the conventional Docker/Compose secrets mount) whenever that directory
actually exists; one file per field, named for the field.
"""

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Fills in os.environ from .env for anything not already set there (the
# default, non-overriding behavior) — matches tests/conftest.py's own
# load_dotenv() call, which already runs this before any test imports this
# module, so this is a no-op in that case rather than a second, conflicting
# load.
load_dotenv()

_LOCAL_DEV_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/dnd_ai"

_SECRETS_DIR = os.environ.get("DND_AI_SECRETS_DIR", "/run/secrets")

# Kept in sync with the fields below by tests/unit/test_config.py's
# metadata-completeness check (docs/DEVELOPMENT.md §2.1's established
# pattern), rather than derived at runtime from validation_alias internals.
_KNOWN_APPLICATION_ENV_VARS = frozenset(
    {
        "DND_AI_ENVIRONMENT",
        "DND_AI_LOG_LEVEL",
        "DND_AI_DATABASE_URL",
        "DATABASE_URL",
        "DND_AI_FEATURE_AI_NPC_DIALOGUE",
        "DND_AI_FEATURE_DISCORD_INTEGRATION",
        "DND_AI_FEATURE_FOUNDRY_INTEGRATION",
        # Not a Settings field — read directly, before the class body even
        # runs, to decide secrets_dir below — but still an application-owned
        # DND_AI_* knob, so it belongs in this list too.
        "DND_AI_SECRETS_DIR",
    }
)


def _reject_unrecognized_env_vars() -> None:
    unrecognized = sorted(
        name
        for name in os.environ
        if name.upper().startswith("DND_AI_") and name.upper() not in _KNOWN_APPLICATION_ENV_VARS
    )
    if unrecognized:
        raise RuntimeError(
            "Unrecognized application environment variable(s): "
            f"{', '.join(unrecognized)}. Check for a typo against the fields "
            "declared in dnd_ai.config.Settings."
        )


class Settings(BaseSettings):
    """Application settings loaded from `DND_AI_*` environment variables
    (including those `.env` supplies via `load_dotenv()` above) and, in
    production, host-mounted secret files."""

    model_config = SettingsConfigDict(
        env_prefix="DND_AI_",
        case_sensitive=False,
        secrets_dir=_SECRETS_DIR if Path(_SECRETS_DIR).is_dir() else None,
        extra="forbid",
    )

    environment: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"

    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DND_AI_DATABASE_URL", "DATABASE_URL"),
    )

    feature_ai_npc_dialogue: bool = False
    feature_discord_integration: bool = False
    feature_foundry_integration: bool = False

    @model_validator(mode="after")
    def _require_explicit_database_url_outside_local_dev(self) -> "Settings":
        """No silent fallback to the local development database/credentials
        once `environment` leaves `local`/`test` (finding 1: "Production
        must not silently fall back to the default localhost database or
        development credentials"). Convenience defaults stay convenient
        only where they're safe."""
        if self.database_url is None:
            if self.environment == "production":
                raise ValueError(
                    "DND_AI_DATABASE_URL (or DATABASE_URL) is required when "
                    "DND_AI_ENVIRONMENT=production — refusing to fall back to the "
                    "local development database."
                )
            self.database_url = _LOCAL_DEV_DATABASE_URL
        return self


_reject_unrecognized_env_vars()
settings = Settings()
