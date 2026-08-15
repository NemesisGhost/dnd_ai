"""check_compose_config's pure invariant checks, exercised against fabricated
merged-config dicts rather than a real `docker compose config` — no Docker
needed. See scripts/check_compose_config.py's module docstring for what
these invariants protect and why.
"""

import pytest
from check_compose_config import (
    ComposeConfigError,
    check_api_environment_configured,
    check_config,
    check_data_volume_mount,
    check_no_published_ports,
)

pytestmark = pytest.mark.unit

# A fully-valid api environment — the default every _config() call gets
# unless a test deliberately overrides it via api_environment, so tests
# targeting an unrelated invariant (ports, volume mount) don't also trip
# over check_api_environment_configured().
_VALID_API_ENVIRONMENT = {
    "DND_AI_ENVIRONMENT": "production",
    "DND_AI_DATABASE_URL": "postgresql+psycopg://postgres:x@db:5432/dnd_ai",
    "DND_AI_OIDC_ISSUER": "https://ci-disposable-idp.example/realm",
    "DND_AI_OIDC_AUDIENCE": "dnd-ai-ci-disposable-audience",
    "DND_AI_OIDC_JWKS_URL": "https://ci-disposable-idp.example/realm/jwks",
}


def _config(
    *,
    ports: list[object] | None = None,
    volume_target: str = "/var/lib/postgresql",
    api_ports: list[object] | None = None,
    api_environment: dict[str, object] | None = _VALID_API_ENVIRONMENT,
) -> dict:
    db: dict[str, object] = {"volumes": [{"type": "volume", "target": volume_target}]}
    if ports is not None:
        db["ports"] = ports
    api: dict[str, object] = {}
    if api_ports is not None:
        api["ports"] = api_ports
    if api_environment is not None:
        api["environment"] = api_environment
    return {"services": {"db": db, "api": api}}


def test_passes_with_no_ports_and_correct_mount() -> None:
    check_config(_config())


def test_passes_when_ports_key_is_absent() -> None:
    check_no_published_ports(_config(ports=None))


def test_fails_when_a_host_port_is_published() -> None:
    with pytest.raises(ComposeConfigError, match="publishes host port"):
        check_no_published_ports(_config(ports=[{"target": 5432, "published": "5432"}]))


def test_fails_when_ports_list_is_nonempty_even_with_odd_shape() -> None:
    with pytest.raises(ComposeConfigError):
        check_no_published_ports(_config(ports=["5432:5432"]))


def test_passes_when_api_publishes_no_port() -> None:
    check_no_published_ports(_config(api_ports=None), "api")


def test_fails_when_api_publishes_a_host_port() -> None:
    with pytest.raises(ComposeConfigError, match="publishes host port.*`api`"):
        check_no_published_ports(_config(api_ports=[{"target": 8000, "published": "8000"}]), "api")


def test_check_config_fails_when_api_publishes_a_host_port() -> None:
    with pytest.raises(ComposeConfigError, match="`api`"):
        check_config(_config(api_ports=[{"target": 8000, "published": "8000"}]))


def test_passes_with_correct_postgresql_18_mount_target() -> None:
    check_data_volume_mount(_config(volume_target="/var/lib/postgresql"))


def test_fails_with_pre_18_mount_target() -> None:
    with pytest.raises(ComposeConfigError, match="does not mount"):
        check_data_volume_mount(_config(volume_target="/var/lib/postgresql/data"))


def test_fails_when_db_has_no_volumes_at_all() -> None:
    with pytest.raises(ComposeConfigError, match="does not mount"):
        check_data_volume_mount({"services": {"db": {}}})


def test_check_config_reports_port_failure_before_mount_failure() -> None:
    # Both invariants are broken; the port check runs first, so its message
    # is what surfaces — pins the ordering so a future reordering is a
    # deliberate change, not an accident.
    with pytest.raises(ComposeConfigError, match="publishes host port"):
        check_config(_config(ports=[{"target": 5432}], volume_target="/var/lib/postgresql/data"))


# ---------------------------------------------------------------------------
# api's production/OIDC configuration (Phase 10 workstream 11 correction
# pass) — regression guard for the defect where api ran with no
# DND_AI_ENVIRONMENT at all, silently defaulting to dnd_ai.config.Settings'
# own "local" mode and skipping OIDC/HTTPS validation entirely.
# ---------------------------------------------------------------------------


def test_passes_with_production_environment_and_all_three_oidc_settings() -> None:
    check_api_environment_configured(_config())


def test_check_config_passes_with_a_fully_valid_api_environment() -> None:
    check_config(_config())


def test_fails_when_environment_is_not_production() -> None:
    with pytest.raises(ComposeConfigError, match="DND_AI_ENVIRONMENT=production"):
        check_api_environment_configured(
            _config(api_environment={**_VALID_API_ENVIRONMENT, "DND_AI_ENVIRONMENT": "local"})
        )


def test_fails_when_environment_key_is_absent_entirely() -> None:
    environment = dict(_VALID_API_ENVIRONMENT)
    del environment["DND_AI_ENVIRONMENT"]
    with pytest.raises(ComposeConfigError, match="DND_AI_ENVIRONMENT=production"):
        check_api_environment_configured(_config(api_environment=environment))


@pytest.mark.parametrize(
    "missing_var", ["DND_AI_OIDC_ISSUER", "DND_AI_OIDC_AUDIENCE", "DND_AI_OIDC_JWKS_URL"]
)
def test_fails_when_an_oidc_setting_is_absent(missing_var: str) -> None:
    environment = dict(_VALID_API_ENVIRONMENT)
    del environment[missing_var]
    with pytest.raises(ComposeConfigError, match=missing_var):
        check_api_environment_configured(_config(api_environment=environment))


@pytest.mark.parametrize(
    "empty_var", ["DND_AI_OIDC_ISSUER", "DND_AI_OIDC_AUDIENCE", "DND_AI_OIDC_JWKS_URL"]
)
def test_fails_when_an_oidc_setting_is_present_but_empty(empty_var: str) -> None:
    # A key present with an empty string is exactly what a broken/omitted
    # `${VAR:?...}` could render as if the required-variable guard ever
    # regressed to a fallback default — this must be treated identically
    # to the key being absent, not treated as "configured".
    environment = {**_VALID_API_ENVIRONMENT, empty_var: ""}
    with pytest.raises(ComposeConfigError, match=empty_var):
        check_api_environment_configured(_config(api_environment=environment))


def test_check_config_fails_when_api_has_no_environment_at_all() -> None:
    with pytest.raises(ComposeConfigError, match="DND_AI_ENVIRONMENT=production"):
        check_config(_config(api_environment=None))
