"""Source-level regression coverage for compose.yaml/compose.ci.yaml/
compose.override.yaml — parses the committed YAML directly (no Docker, no
`docker compose config`) so these invariants are checked even where Docker
isn't available. scripts/check_compose_config.py plus
tests/unit/test_check_compose_config.py cover the corresponding checks
against the real *merged* configuration in CI, where Docker is available.
"""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load(name: str) -> dict:
    with (REPO_ROOT / name).open() as f:
        return yaml.safe_load(f)


def _volume_targets(db: dict) -> set[str]:
    return {v.get("target") for v in db["volumes"] if isinstance(v, dict)}


def test_base_compose_mounts_postgresql_18_data_directory_correctly() -> None:
    targets = _volume_targets(_load("compose.yaml")["services"]["db"])
    assert "/var/lib/postgresql" in targets
    assert "/var/lib/postgresql/data" not in targets


def test_ci_override_mounts_the_same_target_as_the_base_file() -> None:
    # compose merges `volumes:` entries by target path — the CI override
    # only replaces the base's named-volume mount (rather than stacking a
    # second mount alongside it) if this target matches compose.yaml's
    # exactly.
    base_targets = _volume_targets(_load("compose.yaml")["services"]["db"])
    ci_targets = _volume_targets(_load("compose.ci.yaml")["services"]["db"])
    assert base_targets == ci_targets == {"/var/lib/postgresql"}


def test_base_compose_does_not_publish_a_host_port_for_db() -> None:
    db = _load("compose.yaml")["services"]["db"]
    assert "ports" not in db, (
        "compose.yaml's db service must not publish a host port by default — "
        "see compose.yaml's header comment. Local development gets one from "
        "compose.override.yaml instead."
    )


def test_ci_override_does_not_publish_a_host_port_for_db() -> None:
    db = _load("compose.ci.yaml")["services"]["db"]
    assert not db.get("ports")


def test_dev_override_binds_the_published_port_to_localhost_only() -> None:
    db = _load("compose.override.yaml")["services"]["db"]
    (port_entry,) = db["ports"]
    assert port_entry.startswith("127.0.0.1:"), (
        f"compose.override.yaml must bind to 127.0.0.1, not every interface: {port_entry!r}"
    )


def test_postgres_password_has_no_fallback_default() -> None:
    # Guards against regressing to `${POSTGRES_PASSWORD:-postgres}` (or any
    # other silent default) — the required-variable form (`:?...`) must be
    # what the db service interpolates. POSTGRES_PASSWORD itself is not
    # embedded in a URL anywhere in this file (see
    # test_migrate_service_requires_an_explicit_database_url below), so it
    # carries no URL-character restriction.
    content = (REPO_ROOT / "compose.yaml").read_text()
    assert "POSTGRES_PASSWORD:-" not in content, (
        "compose.yaml must not give POSTGRES_PASSWORD a fallback default — "
        "it is required, per docs/DEVELOPMENT.md §3.6."
    )
    assert content.count("POSTGRES_PASSWORD:?") >= 1, (
        "The db service must require POSTGRES_PASSWORD explicitly."
    )


def test_migrate_service_requires_an_explicit_database_url() -> None:
    # The migrate service must take a complete, pre-built connection URL
    # (MIGRATION_DATABASE_URL) rather than Compose assembling one from
    # POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB by string interpolation —
    # that would silently break for a password containing URL-special
    # characters (@ : / ? # [ ] %), since interpolation is not a URL
    # encoder. No fallback default, same as POSTGRES_PASSWORD.
    migrate = _load("compose.yaml")["services"]["migrate"]
    database_url = migrate["environment"]["DATABASE_URL"]
    assert "MIGRATION_DATABASE_URL" in database_url
    assert ":?" in database_url, "MIGRATION_DATABASE_URL must be required, not defaulted"
    assert ":-" not in database_url, "MIGRATION_DATABASE_URL must not have a fallback default"
    # And it must not still be building the URL from the three POSTGRES_*
    # variables directly — that's the exact pattern this fix replaced.
    assert "POSTGRES_PASSWORD" not in database_url
    assert "POSTGRES_USER" not in database_url


def test_api_service_requires_an_explicit_database_url() -> None:
    # Same reasoning as test_migrate_service_requires_an_explicit_database_url
    # above, applied to the api service's DND_AI_DATABASE_URL — a distinct
    # host-side variable (API_DATABASE_URL) from MIGRATION_DATABASE_URL, per
    # compose.yaml's own comment on why (no least-privileged application
    # database role exists yet).
    api = _load("compose.yaml")["services"]["api"]
    database_url = api["environment"]["DND_AI_DATABASE_URL"]
    assert "API_DATABASE_URL" in database_url
    assert ":?" in database_url, "API_DATABASE_URL must be required, not defaulted"
    assert ":-" not in database_url, "API_DATABASE_URL must not have a fallback default"
    assert "POSTGRES_PASSWORD" not in database_url
    assert "POSTGRES_USER" not in database_url


def test_base_compose_does_not_publish_a_host_port_for_api() -> None:
    api = _load("compose.yaml")["services"]["api"]
    assert "ports" not in api, (
        "compose.yaml's api service must not publish a host port by default — "
        "see compose.yaml's header comment. Local development gets one from "
        "compose.override.yaml instead."
    )


def test_dev_override_binds_the_api_published_port_to_localhost_only() -> None:
    api = _load("compose.override.yaml")["services"]["api"]
    (port_entry,) = api["ports"]
    assert port_entry.startswith("127.0.0.1:"), (
        f"compose.override.yaml must bind to 127.0.0.1, not every interface: {port_entry!r}"
    )


def test_api_service_is_not_gated_behind_a_tools_profile() -> None:
    # Unlike migrate (a one-off job), api is a standing service that plain
    # `docker compose up` must start — see compose.yaml's own comment on
    # this distinction.
    api = _load("compose.yaml")["services"]["api"]
    assert "profiles" not in api


def test_api_service_builds_from_the_same_dockerfile_as_migrate() -> None:
    services = _load("compose.yaml")["services"]
    assert services["api"]["build"] == services["migrate"]["build"]


def test_api_healthcheck_targets_healthz_not_readyz() -> None:
    # /healthz is deliberately DB-independent (dnd_ai.api.app's own
    # docstring) — a container healthcheck that instead depended on the
    # database would make the container look unhealthy during a database
    # outage rather than merely not-ready, the exact failure mode /healthz
    # exists to avoid.
    api = _load("compose.yaml")["services"]["api"]
    test_command = " ".join(api["healthcheck"]["test"])
    assert "/healthz" in test_command
    assert "/readyz" not in test_command


# ---------------------------------------------------------------------------
# api's production configuration and optional OIDC bearer-token
# compatibility (Phase 10 workstream 11 correction pass; Phase 13B
# correction) — regression guard for the defect where api ran with no
# DND_AI_ENVIRONMENT at all, silently defaulting to dnd_ai.config.Settings'
# own "local" mode: /healthz and /readyz still passed, but production's
# fail-closed database-identity/HTTPS validation never ran at all. The
# three DND_AI_OIDC_* settings are deliberately optional, with soft `:-`
# defaults — a fully local-authentication-only deployment must be able to
# start `api` with none of the three set (dnd_ai.config.Settings' own
# all-or-nothing validator is what rejects a genuinely partial
# configuration at process startup; this file only proves compose.yaml
# itself no longer hard-requires them).
# ---------------------------------------------------------------------------


def test_api_runs_with_environment_hardcoded_to_production() -> None:
    # A fixed literal, never a variable (no `${...}` at all) — this file is
    # the self-hosted/production deployment topology, not a "local"
    # convenience default, so no missing/misconfigured host-side setting
    # can ever silently leave the container in "local" mode again.
    api = _load("compose.yaml")["services"]["api"]
    assert api["environment"]["DND_AI_ENVIRONMENT"] == "production"


@pytest.mark.parametrize(
    ("container_var", "host_var"),
    [
        ("DND_AI_OIDC_ISSUER", "API_OIDC_ISSUER"),
        ("DND_AI_OIDC_AUDIENCE", "API_OIDC_AUDIENCE"),
        ("DND_AI_OIDC_JWKS_URL", "API_OIDC_JWKS_URL"),
    ],
)
def test_api_oidc_settings_have_safe_soft_defaults_not_hard_requirements(
    container_var: str, host_var: str
) -> None:
    # Mirrors test_api_ai_provider_settings_have_safe_soft_defaults_not_hard_
    # requirements below: each of the three OIDC settings must come from its
    # own optional (`:-`), never-required (`:?`) host-side variable — a
    # distinct name per setting, not all three sharing one variable, and not
    # reusing API_DATABASE_URL's own host-side name.
    api = _load("compose.yaml")["services"]["api"]
    value = api["environment"][container_var]
    assert host_var in value
    assert ":-" in value, f"{host_var} must have a soft (`:-`) fallback default"
    assert ":?" not in value, f"{host_var} must not be a hard requirement"


def test_api_oidc_settings_default_to_blank_not_a_placeholder_value() -> None:
    api = _load("compose.yaml")["services"]["api"]
    assert api["environment"]["DND_AI_OIDC_ISSUER"] == "${API_OIDC_ISSUER:-}"
    assert api["environment"]["DND_AI_OIDC_AUDIENCE"] == "${API_OIDC_AUDIENCE:-}"
    assert api["environment"]["DND_AI_OIDC_JWKS_URL"] == "${API_OIDC_JWKS_URL:-}"


def test_api_oidc_settings_use_three_distinct_host_side_variables() -> None:
    api = _load("compose.yaml")["services"]["api"]
    values = [
        api["environment"]["DND_AI_OIDC_ISSUER"],
        api["environment"]["DND_AI_OIDC_AUDIENCE"],
        api["environment"]["DND_AI_OIDC_JWKS_URL"],
    ]
    assert len(set(values)) == 3, "each OIDC setting must interpolate its own host-side variable"


# ---------------------------------------------------------------------------
# api's AI provider configuration (Phase 12 deployment-gap fix) — regression
# guard for the defect where compose.yaml never forwarded
# DND_AI_FEATURE_AI_NPC_DIALOGUE/DND_AI_AI_PROVIDER_*, so the documented
# Compose deployment could never configure hosted OpenAI or a local
# OpenAI-compatible endpoint at all; every request resolved to HTTP 503.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("container_var", "host_var"),
    [
        ("DND_AI_FEATURE_AI_NPC_DIALOGUE", "API_FEATURE_AI_NPC_DIALOGUE"),
        ("DND_AI_AI_PROVIDER_BASE_URL", "API_AI_PROVIDER_BASE_URL"),
        ("DND_AI_AI_PROVIDER_MODEL", "API_AI_PROVIDER_MODEL"),
        ("DND_AI_AI_PROVIDER_API_KEY", "API_AI_PROVIDER_API_KEY"),
    ],
)
def test_api_ai_provider_settings_are_forwarded_from_distinct_host_variables(
    container_var: str, host_var: str
) -> None:
    api = _load("compose.yaml")["services"]["api"]
    assert container_var in api["environment"], f"api service must set {container_var}"
    value = api["environment"][container_var]
    assert host_var in value, f"{container_var} must interpolate {host_var}"


def test_api_ai_provider_settings_have_safe_soft_defaults_not_hard_requirements() -> None:
    # Unlike API_DATABASE_URL/API_OIDC_* (`:?`, hard-required), the AI
    # provider settings must stay optional — mirrors
    # API_FEATURE_FOUNDRY_INTEGRATION/API_FOUNDRY_ALLOWED_ORIGINS above: a
    # self-hosted deployment that never turns AI on must still start `api`
    # with no configuration at all.
    api = _load("compose.yaml")["services"]["api"]
    for container_var in (
        "DND_AI_FEATURE_AI_NPC_DIALOGUE",
        "DND_AI_AI_PROVIDER_BASE_URL",
        "DND_AI_AI_PROVIDER_MODEL",
        "DND_AI_AI_PROVIDER_API_KEY",
    ):
        value = api["environment"][container_var]
        assert ":-" in value, f"{container_var} must have a soft (`:-`) fallback default"
        assert ":?" not in value, f"{container_var} must not be a hard requirement"


def test_api_ai_provider_feature_flag_defaults_to_disabled() -> None:
    api = _load("compose.yaml")["services"]["api"]
    assert (
        api["environment"]["DND_AI_FEATURE_AI_NPC_DIALOGUE"]
        == "${API_FEATURE_AI_NPC_DIALOGUE:-false}"
    )


def test_api_ai_provider_key_defaults_to_blank_not_a_placeholder_secret() -> None:
    # Compose cannot omit an unset variable's key entirely — the safe
    # fallback is a blank string, which dnd_ai.config.Settings then
    # normalizes to None (see _normalize_ai_provider_api_key), never a
    # committed placeholder value that could be mistaken for a real key.
    api = _load("compose.yaml")["services"]["api"]
    assert api["environment"]["DND_AI_AI_PROVIDER_API_KEY"] == "${API_AI_PROVIDER_API_KEY:-}"


def test_api_ai_provider_base_url_defaults_to_real_hosted_openai() -> None:
    api = _load("compose.yaml")["services"]["api"]
    assert api["environment"]["DND_AI_AI_PROVIDER_BASE_URL"] == (
        "${API_AI_PROVIDER_BASE_URL:-https://api.openai.com/v1}"
    )


def test_env_example_documents_the_ai_provider_host_side_variables() -> None:
    content = (REPO_ROOT / ".env.example").read_text()
    for host_var in (
        "API_FEATURE_AI_NPC_DIALOGUE",
        "API_AI_PROVIDER_API_KEY",
        "API_AI_PROVIDER_MODEL",
        "API_AI_PROVIDER_BASE_URL",
    ):
        assert host_var in content, f".env.example must document {host_var}"
    # Never a real, usable-looking secret committed as a default value.
    assert "API_AI_PROVIDER_API_KEY=sk-" not in content
    assert "sk-proj-" not in content
    assert "sk-test-" not in content


# ---------------------------------------------------------------------------
# api's trusted-reverse-proxy configuration (Phase 13B correction) —
# regression guard for the defect where the IP-wide login rate limiter
# always read `request.client.host`, which collapses to one shared bucket
# across every real client once a reverse proxy sits in front of `api`.
# `DND_AI_TRUSTED_PROXIES` is the one setting dnd_ai.config.Settings and
# dnd_ai.api.client_address.resolve_client_ip both read to decide whether an
# inbound X-Forwarded-For may be trusted; this file's own environment
# mapping must expose exactly that same container-side variable name — not
# a differently spelled or second, parallel setting — so a deployment that
# configures the documented host-side variable is actually changing the
# same trust boundary the application (and this suite's own
# tests/database/test_api_local_auth.py trusted-proxy tests, and
# tests/unit/test_client_address.py) exercises.
# ---------------------------------------------------------------------------


def test_api_trusted_proxies_is_forwarded_from_a_distinct_host_side_variable() -> None:
    api = _load("compose.yaml")["services"]["api"]
    assert "DND_AI_TRUSTED_PROXIES" in api["environment"], (
        "api service must set DND_AI_TRUSTED_PROXIES — the exact setting "
        "dnd_ai.config.Settings/dnd_ai.api.client_address.resolve_client_ip read"
    )
    value = api["environment"]["DND_AI_TRUSTED_PROXIES"]
    assert "API_TRUSTED_PROXIES" in value


def test_api_trusted_proxies_has_a_safe_soft_default_not_a_hard_requirement() -> None:
    # Unset must mean "trust nothing" (dnd_ai.config.Settings' own safe
    # default), never a hard startup requirement — most self-hosted
    # deployments run `api` directly exposed, with no reverse proxy at all.
    api = _load("compose.yaml")["services"]["api"]
    value = api["environment"]["DND_AI_TRUSTED_PROXIES"]
    assert value == "${API_TRUSTED_PROXIES:-}"


def test_env_example_documents_the_trusted_proxies_host_side_variable() -> None:
    content = (REPO_ROOT / ".env.example").read_text()
    assert "API_TRUSTED_PROXIES" in content
    assert "DND_AI_TRUSTED_PROXIES" in content
