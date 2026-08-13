"""Application configuration (docs/LOCAL_DEPLOYMENT.md, ADR 0012).

Settings source precedence, by environment
--------------------------------------------

**local** (default) and **test**: `.env` (resolved as `<cwd>/.env` — an
explicit path, never dotenv's own frame/search-based default, so behavior
is the same whether this runs under pytest, `uvicorn`, or a container) is
loaded into the process environment via `load_dotenv()` before `Settings()`
runs — the same mechanism tests/conftest.py already uses. `database_url`
then accepts, in priority order: (1) `DND_AI_DATABASE_URL`, whether set as
a real environment variable or via a mounted secret file (see "Host-mounted
secret files" below — pydantic-settings' own source order already prefers
an environment variable over a secrets file for the same setting, so that
precedence is inherited here, not reimplemented); (2) legacy unprefixed
`DATABASE_URL`, the pre-existing convention Alembic/pytest/CI already use
(docs/DEVELOPMENT.md §3, §8); (3) the hardcoded local-dev default.

**production** (`DND_AI_ENVIRONMENT=production`, checked directly against
`os.environ` *before* any `.env` loading decision is made — see
`_production_requested()`): `.env` is never loaded, so nothing the
repository's developer convenience file might contain can reach this
process at all. Only `DND_AI_DATABASE_URL` — the real environment variable
or the mounted secret file below — satisfies startup; both the legacy
`DATABASE_URL` alias and the local-dev default are refused, and `Settings()`
raises immediately rather than silently falling back. This is enforced by
checking *which field/source populated the value*, never by inspecting the
URL text for whether it "looks local" — a URL that happens to mention
`localhost` is exactly as acceptable in production, if it arrived through
`DND_AI_DATABASE_URL`, as one that doesn't.

Production is *selected*, not merely *satisfied*, by the real process
environment only: `.env` cannot promote a process into production, even one
that sets both `DND_AI_ENVIRONMENT=production` and a `DND_AI_DATABASE_URL`
that would otherwise look completely valid. `_load_settings()` checks
`DND_AI_ENVIRONMENT` again immediately after loading `.env` and treats a
transition to `production` there as a configuration error (`.env` loading
only ever *fills in* variables the real environment didn't already have —
see that function's docstring) — it is a startup failure, not a value that
gets silently ignored or silently honored.

Every application-owned field is namespaced under the `DND_AI_`
environment-variable prefix so this model never collides with, or silently
absorbs, unrelated variables the host process carries for other tooling —
the AWS CLI, Terraform, Docker Compose itself. That namespace is shared,
though: several other `DND_AI_*` variables are real, currently used, and
owned by a *different* subsystem entirely — `DND_AI_TEST_DATABASE_URL`
(tests/conftest.py, scripts/ci_ephemeral_database.py — the ephemeral
per-test-run database pointer), `DND_AI_CI_DB_NAME` (the same CI scripts —
that database's own name, for teardown), and `DND_AI_SEEDS_DIR`
(src/dnd_ai/persistence/seeds.py — an override for the seed-data
directory). None of those are `Settings` fields and none of them should
ever be — rejecting them as "unrecognized" would break CI and local seed
overrides outright. `_NON_APPLICATION_DND_AI_ENV_VARS` below is a closed,
explicitly cited allowlist for exactly those three (and only those three);
`_reject_unrecognized_env_vars()` still catches a typo of any of them, or
of an actual `Settings` field — it does not fall back to "allow anything
`DND_AI_*`".

`database_url` is the one deliberate unprefixed exception: it additionally
accepts `DATABASE_URL` so a local developer's existing `.env` keeps
working for the application too, without requiring the same value under
two different names — but, per the production rule above, only outside
production.

`oidc_issuer`/`oidc_audience`/`oidc_jwks_url` (`DND_AI_OIDC_ISSUER`,
`DND_AI_OIDC_AUDIENCE`, `DND_AI_OIDC_JWKS_URL`) follow the identical
production-fail-closed shape as `database_url`: all three default to
`None` locally/in tests (no OIDC provider is required to run the API
skeleton or its non-authenticated endpoints yet), but `Settings()` raises
immediately in production unless all three are populated. `_validate_oidc_
settings` goes further than mere presence, in both environments:

- **Production** additionally requires `oidc_issuer`/`oidc_jwks_url` to be
  absolute, credential-free, fragment-free **HTTPS** URLs with a host, and
  `oidc_audience` to be non-empty with no leading/trailing whitespace. A
  plain-HTTP JWKS endpoint lets a network-positioned attacker substitute
  the key set and forge tokens for arbitrary issuer/subject identities —
  refused outright at `Settings()` construction (process startup, before
  `/readyz` can report success or an authenticated route is ever called),
  never merely warned about or discovered lazily on first use.
- **Local/test** may configure an HTTP identity provider (`OIDC_LOCAL_URL_
  SCHEMES` — a private/in-process test IdP has no equivalent network-
  attacker threat model), but a *partial* configuration — some but not all
  three fields set — is rejected exactly like production's all-or-nothing
  rule, and whichever fields *are* set still go through the same
  structural checks (non-empty, well-formed, no credentials, no fragment)
  minus the scheme restriction. An incomplete or malformed OIDC
  configuration can never actually serve an authenticated route, so
  accepting it silently would only defer an otherwise-immediate startup
  failure to first use.

Deliberately never trimmed, rewritten, or otherwise normalized beyond
this validation: `dnd_ai.domain.tokens.verify_bearer_token` compares a
token's `iss` claim against `oidc_issuer` byte-for-byte, so silently
reshaping the configured string — even adding/removing a trailing slash —
would change what it matches, not just how it's spelled. See
`dnd_ai.api.auth`/`dnd_ai.domain.tokens` for what reads these fields, and
`dnd_ai.api.auth._JWKSClient`/`get_jwks_client()` for the matching
redirect-scheme enforcement applied to the actual JWKS network fetch
(`OIDC_PRODUCTION_URL_SCHEMES`/`OIDC_LOCAL_URL_SCHEMES` below are the
single shared source of truth both modules validate against).

Host-mounted secret files (docs/LOCAL_DEPLOYMENT.md "Compose
responsibilities and network policy" — "credentials in host-readable
environment/secret files or mounted secrets outside the repository") are
read from `DND_AI_SECRETS_DIR` (default `/run/secrets`, the conventional
Docker/Compose secrets mount) whenever that directory actually exists; one
file per field, named for the field's environment-variable name in
lowercase. For `database_url` that is the exact filename
**`dnd_ai_database_url`** — mount the secret at
`${DND_AI_SECRETS_DIR}/dnd_ai_database_url` (default
`/run/secrets/dnd_ai_database_url`); see `tests/unit/test_config.py`'s
mounted-secret test for a worked example. `DND_AI_SECRETS_DIR` itself is
read directly from the real process environment only (never from `.env`,
and evaluated before `Settings` is even defined) — it names *where other
secrets live*, so it is exactly the kind of thing that must always be a
real deployment-supplied variable, not a developer-convenience default.
"""

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_DEV_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/dnd_ai"

_SECRETS_DIR = os.environ.get("DND_AI_SECRETS_DIR", "/run/secrets")

_DATABASE_URL_SECRET_FILENAME = "dnd_ai_database_url"

# The single shared source of truth for which URL schemes an OIDC
# issuer/JWKS URL may use, by environment — imported by
# dnd_ai.api.auth._JWKSClient/get_jwks_client() so the same policy governs
# both static config validation here and the actual network fetch's
# redirect handling there. Public (no leading underscore) specifically so
# that cross-module import.
OIDC_PRODUCTION_URL_SCHEMES = frozenset({"https"})
OIDC_LOCAL_URL_SCHEMES = frozenset({"http", "https"})

# Variables dnd_ai.config.Settings itself declares (kept in sync with the
# fields below by tests/unit/test_config.py's metadata-completeness check,
# docs/DEVELOPMENT.md §2.1's established pattern, rather than derived at
# runtime from validation_alias internals) plus the one pre-Settings knob
# (DND_AI_SECRETS_DIR) this module reads directly.
_APPLICATION_SETTINGS_ENV_VARS = frozenset(
    {
        "DND_AI_ENVIRONMENT",
        "DND_AI_LOG_LEVEL",
        "DND_AI_DATABASE_URL",
        "DATABASE_URL",
        "DND_AI_FEATURE_AI_NPC_DIALOGUE",
        "DND_AI_FEATURE_DISCORD_INTEGRATION",
        "DND_AI_FEATURE_FOUNDRY_INTEGRATION",
        "DND_AI_SECRETS_DIR",
        "DND_AI_OIDC_ISSUER",
        "DND_AI_OIDC_AUDIENCE",
        "DND_AI_OIDC_JWKS_URL",
    }
)

# Real, currently used DND_AI_* variables owned by a different subsystem —
# see the module docstring's "Every application-owned field..." paragraph
# for what each one is and where it's actually read. Not Settings fields;
# listed here only so the typo scan below doesn't reject them.
_NON_APPLICATION_DND_AI_ENV_VARS = frozenset(
    {
        "DND_AI_TEST_DATABASE_URL",
        "DND_AI_CI_DB_NAME",
        "DND_AI_SEEDS_DIR",
    }
)

_KNOWN_DND_AI_ENV_VARS = _APPLICATION_SETTINGS_ENV_VARS | _NON_APPLICATION_DND_AI_ENV_VARS


def _reject_unrecognized_env_vars() -> None:
    """pydantic-settings' own env-var source only looks up each field's
    expected name in `os.environ` rather than enumerating it, so a
    misspelled `DND_AI_*` variable would otherwise be silently ignored —
    unlike a typo added to `.env` alone, which never even reaches
    `os.environ` for this scan to see once `.env` isn't loaded (production)
    or *is* caught here too once it is (local/test, since `load_dotenv()`
    runs before this). Covers both this module's own settings and the
    other subsystems' variables listed above; nothing else with the
    `DND_AI_` prefix is assumed safe by default."""
    unrecognized = sorted(
        name
        for name in os.environ
        if name.upper().startswith("DND_AI_") and name.upper() not in _KNOWN_DND_AI_ENV_VARS
    )
    if unrecognized:
        raise RuntimeError(
            "Unrecognized DND_AI_* environment variable(s): "
            f"{', '.join(unrecognized)}. Check for a typo against the fields declared in "
            "dnd_ai.config.Settings, or against _NON_APPLICATION_DND_AI_ENV_VARS if this is "
            "meant for a different subsystem (tests/CI/seeding)."
        )


def _production_requested() -> bool:
    """Read directly from the real process environment — never from
    `.env`, and evaluated before any decision about loading `.env` is made
    — so that decision cannot be influenced by the very file it's deciding
    whether to load."""
    return os.environ.get("DND_AI_ENVIRONMENT", "local").strip().lower() == "production"


def _default_env_file() -> Path:
    return Path.cwd() / ".env"


def _validate_oidc_url(value: str, *, field_name: str, allowed_schemes: frozenset[str]) -> None:
    """Structural validation shared by production and local/test — only
    the allowed scheme set differs (`OIDC_PRODUCTION_URL_SCHEMES` vs.
    `OIDC_LOCAL_URL_SCHEMES`). Rejects, rather than silently repairs,
    every problem: empty/whitespace-padded values, a missing or
    unparseable host, embedded credentials (`user:pass@host`), a URL
    fragment, and any scheme outside the allowed set (in production,
    that means plain HTTP is refused outright — see this module's
    docstring for why). Never trims or otherwise rewrites `value` itself;
    see the module docstring's "Deliberately never trimmed..." paragraph
    for why even that would be unsafe here."""
    if not value or value != value.strip():
        raise ValueError(
            f"{field_name} must not be empty and must not have leading/trailing whitespace"
        )
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} is not a valid URL: {exc}") from exc
    if parsed.scheme.lower() not in allowed_schemes:
        allowed = " or ".join(sorted(allowed_schemes))
        raise ValueError(f"{field_name} must be an absolute {allowed} URL, got {value!r}")
    if not parsed.hostname:
        raise ValueError(f"{field_name} must include a host, got {value!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not contain embedded credentials")
    if parsed.fragment:
        raise ValueError(f"{field_name} must not contain a URL fragment")


def _validate_oidc_audience(value: str) -> None:
    if not value or value != value.strip():
        raise ValueError(
            "DND_AI_OIDC_AUDIENCE must not be empty and must not have leading/trailing whitespace"
        )


class Settings(BaseSettings):
    """Application settings loaded from `DND_AI_*` environment variables
    (including those `.env` supplies outside production — see
    `_load_settings` below) and, in production, host-mounted secret
    files."""

    model_config = SettingsConfigDict(
        env_prefix="DND_AI_",
        case_sensitive=False,
        secrets_dir=_SECRETS_DIR if Path(_SECRETS_DIR).is_dir() else None,
        extra="forbid",
    )

    environment: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"

    # DND_AI_DATABASE_URL (env var or the dnd_ai_database_url secret file) —
    # the only source that satisfies production; see _resolve_database_url.
    database_url: str | None = None

    # The pre-existing unprefixed DATABASE_URL convention — local/test
    # compatibility only, deliberately excluded from the production check.
    legacy_database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")

    feature_ai_npc_dialogue: bool = False
    feature_discord_integration: bool = False
    feature_foundry_integration: bool = False

    # Required together only in production — see _require_oidc_settings_in_production.
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None

    @model_validator(mode="after")
    def _resolve_database_url(self) -> "Settings":
        """No silent fallback to the local development database/credentials
        — or to the legacy `DATABASE_URL` alias — once `environment` is
        `production` (finding: "production must not silently fall back").
        Convenience defaults, and the legacy alias, stay available only
        where they're safe.

        Deliberately runs (and, on failure, raises) before
        `_require_oidc_settings_in_production` below — `model_validator
        (mode="after")` methods execute in class-body order, and the first
        one to raise stops the chain, so a production process missing both
        `database_url` and the OIDC settings reports the (pre-existing,
        already-tested) database error first rather than the two errors
        racing to decide which message a caller sees."""
        if self.database_url is not None:
            return self
        if self.environment == "production":
            raise ValueError(
                "DND_AI_DATABASE_URL (as an environment variable, or the mounted secret at "
                f"${{DND_AI_SECRETS_DIR}}/{_DATABASE_URL_SECRET_FILENAME}) is required when "
                "DND_AI_ENVIRONMENT=production — the legacy DATABASE_URL alias and the local "
                "development database are not accepted in production."
            )
        self.database_url = (
            self.legacy_database_url
            if self.legacy_database_url is not None
            else _LOCAL_DEV_DATABASE_URL
        )
        return self

    @model_validator(mode="after")
    def _validate_oidc_settings(self) -> "Settings":
        """No silent partial or malformed OIDC configuration, in either
        environment — see the module docstring's `oidc_issuer`/
        `oidc_audience`/`oidc_jwks_url` paragraph for the full policy.
        Presence (all-or-nothing) is checked first and identically in
        both branches below; only the allowed URL scheme set differs
        between them."""
        configured = (self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url)
        if self.environment == "production":
            missing = [
                name
                for name, value in (
                    ("DND_AI_OIDC_ISSUER", self.oidc_issuer),
                    ("DND_AI_OIDC_AUDIENCE", self.oidc_audience),
                    ("DND_AI_OIDC_JWKS_URL", self.oidc_jwks_url),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    f"{', '.join(missing)} (as environment variables, or mounted secrets) "
                    "are required when DND_AI_ENVIRONMENT=production — all three OIDC settings "
                    "must be configured together, or none of them."
                )
            allowed_schemes = OIDC_PRODUCTION_URL_SCHEMES
        else:
            if any(value is not None for value in configured) and not all(
                value is not None for value in configured
            ):
                raise ValueError(
                    "DND_AI_OIDC_ISSUER, DND_AI_OIDC_AUDIENCE, and DND_AI_OIDC_JWKS_URL must be "
                    "configured together, or none of them — a partially configured OIDC "
                    "provider can never actually serve an authenticated route."
                )
            if all(value is None for value in configured):
                return self
            allowed_schemes = OIDC_LOCAL_URL_SCHEMES

        assert self.oidc_issuer is not None
        assert self.oidc_audience is not None
        assert self.oidc_jwks_url is not None
        _validate_oidc_url(
            self.oidc_issuer, field_name="DND_AI_OIDC_ISSUER", allowed_schemes=allowed_schemes
        )
        _validate_oidc_url(
            self.oidc_jwks_url, field_name="DND_AI_OIDC_JWKS_URL", allowed_schemes=allowed_schemes
        )
        _validate_oidc_audience(self.oidc_audience)
        return self


def _load_settings(*, env_file: str | os.PathLike[str] | None = None) -> Settings:
    """Build `Settings`, deciding first — from the real process
    environment only — whether `.env` should be loaded at all (never in
    production; see the module docstring). `env_file` lets tests point at
    an isolated temporary dotenv without touching the repository's real
    `.env` or relying on process-wide monkeypatching of `Path.cwd()`.

    `.env` cannot promote a non-production process into production either.
    `load_dotenv()`'s default `override=False` means it only fills in
    variables `os.environ` doesn't already have — so the *only* way
    `DND_AI_ENVIRONMENT` can read back as `production` immediately after
    loading `.env`, having read back as anything else just before, is that
    `.env` itself supplied it. That is exactly the case
    `_production_requested()`'s pre-load check exists to prevent (a
    production process is selected by the real deployment environment, not
    by a file this repository ships a `.env.example` for) — so it is
    treated as a configuration error, not silently ignored or silently
    honored.
    """
    if _production_requested():
        _reject_unrecognized_env_vars()
        return Settings()

    load_dotenv(dotenv_path=Path(env_file) if env_file is not None else _default_env_file())

    if _production_requested():
        raise RuntimeError(
            "DND_AI_ENVIRONMENT=production was found in .env, not in the real process "
            "environment. Production must be selected by the real deployment environment — "
            "remove DND_AI_ENVIRONMENT from .env, or set it there as an actual environment "
            "variable instead."
        )

    _reject_unrecognized_env_vars()
    return Settings()


settings = _load_settings()
