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
environment-variable prefix so this model never collides with unrelated
variables the host process carries for other tooling. That namespace is
shared, though: several other `DND_AI_*` variables are real, currently used,
and owned by a *different* subsystem entirely — `DND_AI_TEST_DATABASE_URL`
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
`DND_AI_OIDC_AUDIENCE`, `DND_AI_OIDC_JWKS_URL`) are optional **external
bearer-token compatibility** configuration, in every environment including
production — local application authentication (docs/PLAN.md §23.1/§23.4)
is the platform's primary, self-contained login path and must work with
OIDC entirely unconfigured; nothing about local cookie authentication ever
constructs an OIDC verifier or reads these fields (`dnd_ai.api.auth.
get_jwks_client()` is called lazily, only from the OIDC bearer branch of
`get_authenticated_user_id`, never at import or app-startup time). All
three default to `None` in every environment; `_validate_oidc_settings`
enforces an identical **all-or-nothing** rule everywhere — some but not
all three fields set is a `Settings()` construction failure regardless of
`environment` — and, once all three are set, both environments run the
same structural checks (non-empty, well-formed, no embedded credentials,
no URL fragment) with only the allowed URL scheme set differing:

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
  attacker threat model), and, exactly like production, a *partial*
  configuration — some but not all three fields set — is rejected. An
  incomplete or malformed OIDC configuration can never actually serve an
  authenticated route, so accepting it silently would only defer an
  otherwise-immediate startup failure to first use.

A blank/whitespace-only value for any of the three (e.g. Compose
interpolating an unset `API_OIDC_*` host variable to `${API_OIDC_ISSUER:-}`)
is normalized to `None` before the all-or-nothing check runs — the same
"blank means unset, never a validation error" treatment
`_validate_foundry_allowed_origins`/`_normalize_ai_provider_api_key`
already apply to their own optional settings — so a fully-unset Compose
OIDC block and a fully-omitted one are indistinguishable to this module.

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

`foundry_allowed_origins` (`DND_AI_FOUNDRY_ALLOWED_ORIGINS`) is the explicit
CORS allowlist for the FoundryVTT module's browser-origin requests
(`docs/LOCAL_DEPLOYMENT.md`'s documented separate-origin deployment — the
Foundry client and this API sit behind different public hostnames). A
comma-separated list of exact origins (`scheme://host[:port]`, never a
path/query/fragment/credentials, never a wildcard `*` or a wildcarded
subdomain) — `_validate_foundry_allowed_origins` rejects anything else
outright at `Settings()` construction, the same fail-fast posture as the
OIDC settings above, and normalizes each surviving origin (lowercased
scheme/host, default port stripped, order-preserving de-duplication) so
`dnd_ai.api.app` never has to repeat that parsing. Defaults to `None`
(no cross-origin browser access permitted — `dnd_ai.api.app.create_app`
still installs `CORSMiddleware`, just with an empty allowlist, which is a
safe default: it never widens to "allow anything," it simply permits
nothing extra), except when `DND_AI_ENVIRONMENT=production` **and**
`DND_AI_FEATURE_FOUNDRY_INTEGRATION=true` — a production deployment that
has actually turned the integration on cannot silently ship with no
Foundry origin able to reach the API at all, so that combination requires
`DND_AI_FOUNDRY_ALLOWED_ORIGINS` to be set, with no fallback value.
Scheme policy mirrors the OIDC settings exactly: production requires every
origin to use **HTTPS** (a plain-HTTP origin cannot itself be
authenticated as anything, but it does tell a network observer this
deployment's Foundry credential travels in the clear); local/test also
permit `http://`, since a developer's own Foundry instance is routinely
plain HTTP. See `dnd_ai.api.app`'s own `CORSMiddleware` wiring for how
this allowlist is actually enforced, and `foundry-module/README.md`'s
"Trust boundary"/"Transport security" sections for the client-side half of
this correction (the module's own connection validator requires HTTPS for
any non-loopback API base URL).

`trusted_proxies` (`DND_AI_TRUSTED_PROXIES`; Phase 13B correction) is the
single authoritative source of which immediate TCP peers this process
trusts to set `X-Forwarded-For` — a comma-separated list of exact IP
addresses and/or CIDR networks (e.g. `10.0.0.5,172.20.0.0/16`), parsed with
`ipaddress`, never a hostname (a reverse proxy's *container/network*
address, not its DNS name — `ipaddress.ip_network` cannot resolve one, and
resolving one at startup would make trust depend on DNS, a second
attacker-influenced input). Optional in every environment, including
production, and defaults to empty (no peer trusted, `X-Forwarded-For`
never read) — the current `compose.yaml` topology publishes no host port
for `api` and sits behind no reverse proxy yet (PLAN.md §32, Phase 14), so
"trust nothing" is the correct default until an operator actually places
one in front of it. `dnd_ai.api.client_address.resolve_client_ip` is the
one place this setting is read to decide whether an inbound request's
`X-Forwarded-For` header may override `request.client.host` for rate-
limiting purposes — see that module's own docstring for the trust
algorithm (single-hop: the *last* `X-Forwarded-For` entry is trusted, since
that is what the trusted proxy itself observed as its peer). A malformed
entry (not a valid IP address or CIDR network) is a `Settings()`
construction failure, the same fail-fast posture as every other optional
allowlist setting here — there is no safe way to silently drop or repair a
malformed trust-boundary entry. **A production deployment that places this
API behind a reverse proxy and wants the IP-wide login rate limiter (and
any other per-source-address abuse guard) to see real client addresses
instead of one shared proxy address must set this before enabling public
login** — see `compose.yaml`'s own `api` service comment and
`.env.example`'s "Trusted reverse proxy" section.

`database_url` carries one more production-only rule beyond the one
above: `Settings()` also parses it (with SQLAlchemy's own URL parser, not
string splitting) and refuses to start unless its username is exactly
`PRODUCTION_REQUIRED_DATABASE_ROLE` (`app_read_write`) —
`_require_app_read_write_identity_in_production` below. This is the
static half of that enforcement only; it proves what the configured URL
*claims*, not what a real connection actually authenticates as.
`dnd_ai.api.deps.verify_database_identity` proves the live half, run from
`dnd_ai.api.app`'s lifespan startup against `session_user`/`current_user`
on an actual connection, so a stale `postgres`/`migration_runner` URL (or
a connection pooler/`SET ROLE` that silently changes the effective
identity after authentication) can never again start this service and
pass health checks the way it once did.

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

import ipaddress
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import make_url
from sqlalchemy.exc import ArgumentError

_LOCAL_DEV_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/dnd_ai"

# The real, hosted OpenAI API — dnd_ai.domain.ai_provider.OpenAiCompatibleProvider's
# own default. Duplicated here (not imported from that module) to keep this
# module's own layering simple — dnd_ai.config has no dependency on dnd_ai.domain.
_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

# The exact login role the containerized `api` service must authenticate
# to PostgreSQL as, once DND_AI_ENVIRONMENT=production — 001_bootstrap's
# DML-only role (SELECT/INSERT/UPDATE/DELETE on application tables, no
# schema DDL, no role management, no migration_owner membership; see
# docs/DATABASE_CONVENTIONS.md §27.1). Public (no leading underscore) so
# this one literal is shared by both halves of the enforcement: the static
# check below (what the configured URL claims) and
# dnd_ai.api.deps.verify_database_identity (what a real connection actually
# authenticated as — a URL string is only a claim, not proof, of identity).
PRODUCTION_REQUIRED_DATABASE_ROLE = "app_read_write"

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

# docs/PLAN.md §23.4's own documented local dev topology: Vite at :5173
# proxying /api and /auth to FastAPI at :8000 (the browser's Origin stays
# :5173 through that proxy), plus FastAPI's own bare origin for direct
# clients (tests/database, tests/scenario, curl). The zero-configuration
# default for local_session_allowed_origins outside production.
_LOCAL_DEV_SESSION_ORIGINS = ("http://localhost:5173", "http://localhost:8000")

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
        "DND_AI_FOUNDRY_ALLOWED_ORIGINS",
        "DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS",
        "DND_AI_TRUSTED_PROXIES",
        "DND_AI_AI_PROVIDER_API_KEY",
        "DND_AI_AI_PROVIDER_MODEL",
        "DND_AI_AI_PROVIDER_BASE_URL",
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


_FOUNDRY_ORIGIN_DEFAULT_PORTS = {"http": 80, "https": 443}


def _validate_and_normalize_origin(value: str, *, field_name: str, require_https: bool) -> str:
    """One entry of an exact-origin allowlist setting (`DND_AI_FOUNDRY_
    ALLOWED_ORIGINS` or `DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS`) — validated
    and returned in a canonical form (lowercased scheme/host, default port
    stripped) so `dnd_ai.api.app` can pass the result straight to
    `CORSMiddleware(allow_origins=...)`, or `dnd_ai.api.auth` can compare
    a request's `Origin` header against it, without repeating this
    parsing. Shared by both settings — `field_name` is only for error
    messages, the validation rules are identical either way. Rejects,
    rather than silently repairs: a wildcard anywhere in the
    value (an allowlist entry meant to be exact, never a subdomain
    pattern), a scheme outside the allowed set for this environment, a
    missing host, embedded credentials, a path/query/fragment (an Origin
    is scheme+host+port only — CLAUDE.md rule "no unsafe fallback
    values"), or an unparseable/invalid-port URL."""
    if not value or value != value.strip():
        raise ValueError(f"{field_name} contains an empty or whitespace-padded entry: {value!r}")
    if "*" in value:
        raise ValueError(
            f"{field_name} must not contain a wildcard origin: {value!r} — "
            "every entry must be one exact scheme://host[:port], never a pattern"
        )
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} contains a malformed origin {value!r}: {exc}") from exc
    allowed_schemes = {"https"} if require_https else {"http", "https"}
    scheme = parsed.scheme.lower()
    if scheme not in allowed_schemes:
        allowed = " or ".join(sorted(allowed_schemes))
        raise ValueError(f"{field_name} origin {value!r} must use {allowed}")
    if not parsed.hostname:
        raise ValueError(f"{field_name} origin {value!r} must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} origin {value!r} must not contain embedded credentials")
    if parsed.path not in ("", "/"):
        raise ValueError(f"{field_name} origin {value!r} must not contain a path")
    if parsed.query:
        raise ValueError(f"{field_name} origin {value!r} must not contain a query string")
    if parsed.fragment:
        raise ValueError(f"{field_name} origin {value!r} must not contain a URL fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} origin {value!r} has an invalid port") from exc
    host = parsed.hostname.lower()
    if port is not None and port != _FOUNDRY_ORIGIN_DEFAULT_PORTS[scheme]:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def _parse_allowed_origins(raw: str, *, field_name: str, require_https: bool) -> tuple[str, ...]:
    """Splits, validates, normalizes, and order-preserving-deduplicates a
    raw comma-separated exact-origin allowlist value."""
    normalized: list[str] = []
    seen: set[str] = set()
    for entry in raw.split(","):
        origin = _validate_and_normalize_origin(
            entry.strip(), field_name=field_name, require_https=require_https
        )
        if origin not in seen:
            seen.add(origin)
            normalized.append(origin)
    return tuple(normalized)


def foundry_allowed_origins_tuple(settings_obj: "Settings") -> tuple[str, ...]:
    """The parsed, already-validated CORS allowlist `dnd_ai.api.app`
    passes to `CORSMiddleware(allow_origins=...)` — `Settings` itself
    stores the normalized comma-joined string (see
    `_validate_foundry_allowed_origins`), so this only ever re-splits
    already-validated data; it never re-runs validation or can fail."""
    if not settings_obj.foundry_allowed_origins:
        return ()
    return tuple(settings_obj.foundry_allowed_origins.split(","))


_TrustedProxyNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def _parse_trusted_proxies(raw: str) -> tuple[_TrustedProxyNetwork, ...]:
    """Splits, validates, and order-preserving-deduplicates a raw
    comma-separated `DND_AI_TRUSTED_PROXIES` value into parsed networks.
    Each entry must be a literal IP address (treated as a /32 or /128) or
    CIDR network — never a hostname, since `ipaddress.ip_network` performs
    no DNS resolution (see the module docstring's `trusted_proxies`
    paragraph for why that is deliberate, not a limitation to work
    around). `strict=False` permits an entry like `10.0.0.5/24` (host bits
    set) without erroring, matching how an operator is likeliest to copy a
    single proxy address in from `ip addr`/`docker inspect` output."""
    networks: list[_TrustedProxyNetwork] = []
    seen: set[_TrustedProxyNetwork] = set()
    for entry in raw.split(","):
        candidate = entry.strip()
        if not candidate:
            raise ValueError(
                f"DND_AI_TRUSTED_PROXIES contains an empty or whitespace-padded entry: {raw!r}"
            )
        try:
            network = ipaddress.ip_network(candidate, strict=False)
        except ValueError as exc:
            raise ValueError(
                f"DND_AI_TRUSTED_PROXIES entry {candidate!r} is not a valid IP address or CIDR "
                "network"
            ) from exc
        if network not in seen:
            seen.add(network)
            networks.append(network)
    return tuple(networks)


def trusted_proxy_networks_tuple(settings_obj: "Settings") -> tuple[_TrustedProxyNetwork, ...]:
    """The parsed, already-validated set of peer networks
    `dnd_ai.api.client_address.resolve_client_ip` trusts to set
    `X-Forwarded-For` — mirrors `foundry_allowed_origins_tuple`/
    `local_session_allowed_origins_tuple` exactly, over the separate
    `trusted_proxies` setting. Re-parses on every call rather than caching
    a parsed form on `Settings` itself, so a test that directly
    `monkeypatch.setattr(settings, "trusted_proxies", ...)`s a raw string
    (this codebase's established pattern — see `tests/database/
    test_api_auth.py`'s identical use for `oidc_issuer` et al.) is picked
    up immediately, without needing to also reconstruct a `Settings`
    instance to re-run its model validators."""
    if not settings_obj.trusted_proxies:
        return ()
    return _parse_trusted_proxies(settings_obj.trusted_proxies)


def local_session_allowed_origins_tuple(settings_obj: "Settings") -> tuple[str, ...]:
    """The parsed, already-validated `Origin` allowlist `dnd_ai.api.auth`
    checks a cookie-authenticated state-changing request's `Origin` header
    against (docs/PLAN.md §23.4's "an allowed Origin" requirement) — mirrors
    `foundry_allowed_origins_tuple` exactly, over the separate `local_
    session_allowed_origins` setting. Unlike the Foundry allowlist this is
    not passed to `CORSMiddleware`: a same-origin browser session is not a
    CORS request at all in production (docs/PLAN.md §23.4 — portal and API
    share one origin there); it exists only for the local dev topology
    (Vite at :5173 proxying to FastAPI at :8000) and as an explicit,
    server-owned comparison set for the CSRF Origin check either way."""
    if not settings_obj.local_session_allowed_origins:
        return ()
    return tuple(settings_obj.local_session_allowed_origins.split(","))


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

    # Explicit CORS allowlist for the FoundryVTT module's browser-origin
    # requests — required only when production and the Foundry feature
    # flag are both on; see _validate_foundry_allowed_origins and this
    # module's own docstring.
    foundry_allowed_origins: str | None = None

    # Explicit Origin allowlist checked against a cookie-authenticated
    # state-changing request's Origin header (docs/PLAN.md §23.4's CSRF
    # requirement) — required in production (no feature flag gates local
    # authentication; see _validate_local_session_allowed_origins), and
    # defaulting to the documented dev topology outside it.
    local_session_allowed_origins: str | None = None

    # Comma-separated exact IP addresses/CIDR networks trusted to set
    # X-Forwarded-For (Phase 13B correction) — see this module's own
    # docstring's `trusted_proxies` paragraph. Optional, unconditionally,
    # in every environment; empty/unset means "trust nothing," the safe
    # default matching the current no-reverse-proxy-yet compose.yaml
    # topology.
    trusted_proxies: str | None = None

    # Phase 12 AI provider credential/model/endpoint pin (dnd_ai.domain.
    # ai_provider.OpenAiCompatibleProvider). ai_provider_base_url defaults
    # to real, hosted OpenAI; pointing it at a locally hosted, OpenAI-API-
    # compatible model server (Ollama, vLLM, LM Studio, ...) is the
    # supported "path forward for a locally hosted model" — see that
    # module's own docstring. ai_provider_api_key is required, with no
    # fallback, only when talking to the real hosted API in production
    # (_require_ai_provider_key_in_production below) — a self-hosted
    # server the operator controls may need no key at all. Never a default
    # value: an API key is a secret (CLAUDE.md rule 10 — no secrets in code
    # or seed files), so there is nothing safe to default it to.
    ai_provider_api_key: str | None = None
    ai_provider_model: str = "gpt-4o"
    ai_provider_base_url: str = _DEFAULT_OPENAI_BASE_URL

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
    def _require_app_read_write_identity_in_production(self) -> "Settings":
        """Static half of the app_read_write enforcement (finding: a stale
        `postgres`/`migration_runner` URL previously started the container
        successfully and passed /healthz and /readyz, silently recreating
        the exact privileged-API defect 083_schema_usage_grants/690a928
        already fixed once). The live half —
        `dnd_ai.api.deps.verify_database_identity`, checked against a real
        connection's `session_user`/`current_user` — runs separately from
        `dnd_ai.api.app`'s lifespan startup, since a URL string is only a
        claim about identity, not proof of it (a connection pooler, an
        implicit/explicit `SET ROLE`, or plain misconfiguration could all
        make the two disagree).

        Runs after `_resolve_database_url` (definition order — pydantic v2
        executes same-mode model validators in the order they're defined),
        so `self.database_url` is always populated by the time this runs.
        Parses with SQLAlchemy's own URL parser (`make_url`), never by
        splitting the string — a URL can legally contain `@`, `:`, or `/`
        inside a percent-encoded password, which naive splitting would get
        wrong. Never includes `self.database_url` itself, or any parsed
        password, in the raised error — only the fixed expected-role
        literal; a role name is not a secret, but a full connection URL can
        embed one.
        """
        if self.environment != "production":
            return self
        assert self.database_url is not None
        try:
            parsed_url = make_url(self.database_url)
        except ArgumentError as exc:
            raise ValueError(
                "DND_AI_DATABASE_URL could not be parsed as a database URL when "
                "DND_AI_ENVIRONMENT=production."
            ) from exc
        if parsed_url.username != PRODUCTION_REQUIRED_DATABASE_ROLE:
            raise ValueError(
                "DND_AI_DATABASE_URL must authenticate as the "
                f"{PRODUCTION_REQUIRED_DATABASE_ROLE!r} role when DND_AI_ENVIRONMENT=production "
                "— the postgres superuser, migration_runner, and migration_owner credentials "
                "must never be used by the api service (docs/DATABASE_CONVENTIONS.md §27.1)."
            )
        return self

    @model_validator(mode="after")
    def _normalize_oidc_settings(self) -> "Settings":
        """Blank/whitespace-only treated identically to unset, for each of
        the three OIDC fields independently — mirrors `_normalize_ai_
        provider_api_key`'s identical reasoning: Compose cannot omit an
        environment key entirely when the host-side variable is unset
        (`${API_OIDC_ISSUER:-}` interpolates to `""`, never a genuinely
        absent `DND_AI_OIDC_ISSUER`), so a blank value must read as `None`
        here, before `_validate_oidc_settings`' all-or-nothing check ever
        runs — otherwise a fully-unset Compose OIDC block would be rejected
        as "partially configured" instead of accepted as "not configured at
        all". Runs before `_validate_oidc_settings` (definition order) so
        that validator always sees already-normalized values."""
        if self.oidc_issuer is not None and self.oidc_issuer.strip() == "":
            self.oidc_issuer = None
        if self.oidc_audience is not None and self.oidc_audience.strip() == "":
            self.oidc_audience = None
        if self.oidc_jwks_url is not None and self.oidc_jwks_url.strip() == "":
            self.oidc_jwks_url = None
        return self

    @model_validator(mode="after")
    def _validate_oidc_settings(self) -> "Settings":
        """External OIDC bearer-token compatibility is optional in every
        environment, including production — see the module docstring's
        `oidc_issuer`/`oidc_audience`/`oidc_jwks_url` paragraph for the full
        policy this enforces. All three unset is always valid (external
        bearer authentication disabled; local cookie authentication is
        unaffected either way). Otherwise, presence is all-or-nothing,
        identically in every environment — a partial configuration can
        never actually serve an authenticated route, so it is rejected
        here rather than deferred to first use — and, once all three are
        set, only the allowed URL scheme set differs between production
        (HTTPS only) and local/test (HTTP also permitted, for a private/
        in-process test IdP)."""
        configured = (self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url)
        if any(value is not None for value in configured) and not all(
            value is not None for value in configured
        ):
            raise ValueError(
                "DND_AI_OIDC_ISSUER, DND_AI_OIDC_AUDIENCE, and DND_AI_OIDC_JWKS_URL must be "
                "configured together, or none of them — a partially configured OIDC provider "
                "can never actually serve an authenticated route. External OIDC is optional in "
                "every environment; local application authentication does not require it."
            )
        if all(value is None for value in configured):
            return self

        allowed_schemes = (
            OIDC_PRODUCTION_URL_SCHEMES
            if self.environment == "production"
            else OIDC_LOCAL_URL_SCHEMES
        )
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

    @model_validator(mode="after")
    def _validate_foundry_allowed_origins(self) -> "Settings":
        """No unsafe fallback value, ever: unset means "no cross-origin
        Foundry access" (a safe, narrowing default — `dnd_ai.api.app`
        still installs `CORSMiddleware`, just with an empty allowlist),
        never a wildcard. A blank/whitespace-only value (e.g. Compose
        interpolating an unset host variable to `""`) is treated
        identically to unset, not as a validation error. Required, with no
        fallback, only once a production deployment has actually turned
        the Foundry integration on (`feature_foundry_integration`) — see
        the module docstring's `foundry_allowed_origins` paragraph for the
        full policy, which otherwise mirrors the OIDC settings above:
        production requires HTTPS on every origin, local/test also permit
        HTTP. Normalizes the field in place (comma-joined, deduplicated,
        canonical form) so `dnd_ai.api.app.foundry_allowed_origins_tuple`
        never has to re-validate."""
        raw = self.foundry_allowed_origins
        if raw is not None and raw.strip() == "":
            raw = None
        if raw is None:
            if self.environment == "production" and self.feature_foundry_integration:
                raise ValueError(
                    "DND_AI_FOUNDRY_ALLOWED_ORIGINS is required when "
                    "DND_AI_ENVIRONMENT=production and "
                    "DND_AI_FEATURE_FOUNDRY_INTEGRATION=true — a browser-based FoundryVTT "
                    "client needs an explicit CORS allowlist; there is no safe wildcard or "
                    "default origin."
                )
            self.foundry_allowed_origins = None
            return self
        require_https = self.environment == "production"
        origins = _parse_allowed_origins(
            raw, field_name="DND_AI_FOUNDRY_ALLOWED_ORIGINS", require_https=require_https
        )
        self.foundry_allowed_origins = ",".join(origins)
        return self

    @model_validator(mode="after")
    def _validate_local_session_allowed_origins(self) -> "Settings":
        """The `Origin` allowlist `dnd_ai.api.auth` checks a cookie-
        authenticated state-changing request's `Origin` header against
        (docs/PLAN.md §23.4). Unlike `foundry_allowed_origins`, local
        authentication is not behind a feature flag — it is the platform's
        primary authentication mechanism (docs/PLAN.md §23.1: "local
        authentication must work with OIDC entirely unconfigured") — so
        this is required, unconditionally, in production: a same-origin
        production deployment still needs to state what that one origin
        *is*, since nothing in this module can derive "the app's own
        public origin" from any other setting. Local/test defaults to the
        two origins docs/PLAN.md §23.4 itself documents for the dev
        topology (Vite at :5173 proxying `/api`/`/auth` to FastAPI at
        :8000, plus FastAPI's own bare origin for direct/test clients) so
        local development and tests/database/tests/scenario work with zero
        extra configuration. Scheme policy and normalization otherwise
        mirror `_validate_foundry_allowed_origins` exactly."""
        raw = self.local_session_allowed_origins
        if raw is not None and raw.strip() == "":
            raw = None
        if raw is None:
            if self.environment == "production":
                raise ValueError(
                    "DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS is required when "
                    "DND_AI_ENVIRONMENT=production — a browser session's CSRF check needs an "
                    "explicit Origin allowlist; there is no safe wildcard or default origin."
                )
            self.local_session_allowed_origins = ",".join(_LOCAL_DEV_SESSION_ORIGINS)
            return self
        require_https = self.environment == "production"
        origins = _parse_allowed_origins(
            raw, field_name="DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS", require_https=require_https
        )
        self.local_session_allowed_origins = ",".join(origins)
        return self

    @model_validator(mode="after")
    def _validate_trusted_proxies(self) -> "Settings":
        """Blank/whitespace-only treated identically to unset (mirrors
        every other optional allowlist setting's normalization above) —
        never a validation error, never a fallback to "trust everything."
        A non-blank value must fully parse as a comma-separated list of IP
        addresses/CIDR networks (`_parse_trusted_proxies`); any malformed
        entry fails `Settings()` construction outright, the same fail-fast
        posture as `foundry_allowed_origins`/`local_session_allowed_
        origins` — there is no safe way to silently drop or repair a
        malformed trust-boundary entry for a setting that governs which
        peers this process trusts to relabel a request's source address.
        Unconditionally optional, in every environment including
        production: unlike `local_session_allowed_origins`, no rule here
        requires this to be set, since a self-hosted deployment with no
        reverse proxy in front of `api` (this repository's current
        compose.yaml topology) has nothing to configure. Normalizes the
        field in place (canonical `str(network)` form, deduplicated) so
        `trusted_proxy_networks_tuple` never has to re-validate."""
        raw = self.trusted_proxies
        if raw is not None and raw.strip() == "":
            raw = None
        if raw is None:
            self.trusted_proxies = None
            return self
        networks = _parse_trusted_proxies(raw)
        self.trusted_proxies = ",".join(str(network) for network in networks)
        return self

    @model_validator(mode="after")
    def _normalize_ai_provider_api_key(self) -> "Settings":
        """Docker Compose cannot omit an environment key entirely when the
        host-side variable is unset — `${API_AI_PROVIDER_API_KEY:-}`
        interpolates to the literal empty string, never a genuinely absent
        `DND_AI_AI_PROVIDER_API_KEY` (compose.yaml's own comment on this
        setting explains why no fallback default other than blank is safe
        for a secret). Treat blank/whitespace-only identically to unset —
        mirrors `_validate_foundry_allowed_origins`' identical reasoning for
        `DND_AI_FOUNDRY_ALLOWED_ORIGINS` — so both
        `_require_ai_provider_key_in_production` below and
        `dnd_ai.api.ai_npc._resolve_provider` see `None`, never a falsy-but-
        not-`None` `""` that would silently skip the required-key check and
        then send an unauthenticated request to hosted OpenAI. Runs before
        `_require_ai_provider_key_in_production` (definition order) so that
        validator always sees the normalized value."""
        if self.ai_provider_api_key is not None and self.ai_provider_api_key.strip() == "":
            self.ai_provider_api_key = None
        return self

    @model_validator(mode="after")
    def _require_ai_provider_key_in_production(self) -> "Settings":
        """No unsafe fallback: a production deployment that has turned
        `feature_ai_npc_dialogue` on cannot silently ship with no AI
        provider credential configured at all — the same "required, with
        no fallback, once the feature is actually on" posture
        `_validate_foundry_allowed_origins` already applies to its own
        setting. This only applies when `ai_provider_base_url` is still
        the real, hosted OpenAI default: a production deployment pointed
        at its own self-hosted, OpenAI-API-compatible model server (the
        "locally hosted model" path `dnd_ai.domain.ai_provider.
        OpenAiCompatibleProvider` documents) is exactly the case where no
        key may be needed at all, and that operator's own server is
        responsible for whatever access control it wants. Outside
        production, or with the feature flag off, an unconfigured key is a
        safe default (`dnd_ai.api.ai_npc._resolve_provider` returns 503
        rather than silently degrading to a fake/no-op provider)."""
        if (
            self.environment == "production"
            and self.feature_ai_npc_dialogue
            and self.ai_provider_base_url == _DEFAULT_OPENAI_BASE_URL
            and self.ai_provider_api_key is None
        ):
            raise ValueError(
                "DND_AI_AI_PROVIDER_API_KEY (as an environment variable, or a mounted secret) is "
                "required when DND_AI_ENVIRONMENT=production, "
                "DND_AI_FEATURE_AI_NPC_DIALOGUE=true, and DND_AI_AI_PROVIDER_BASE_URL is unset "
                "(still the real, hosted OpenAI API) — a locally hosted model server may not "
                "need one at all."
            )
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
