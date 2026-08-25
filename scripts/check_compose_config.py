"""Asserts invariants about the merged, interpolated Compose configuration.

Usage (CI only — needs a real `docker compose`, not a source-level check):

    docker compose -f compose.yaml -f compose.ci.yaml config --format json \
      | python3 scripts/check_compose_config.py

Reads the merged config as JSON from stdin and checks:

  - `db` and `api` publish no host ports — CI must never expose PostgreSQL
    or the API on a host port (compose.yaml's base topology publishes
    neither by design; this guards against a future regression re-adding
    one to compose.yaml or compose.ci.yaml).
  - `db` mounts its data volume at /var/lib/postgresql, the PostgreSQL 18
    image's actual data-directory parent (PGDATA defaults to
    /var/lib/postgresql/18/docker) — not /var/lib/postgresql/data, the
    pre-18 convention that would silently miss where the server writes.
  - `api` is explicitly configured for production: `DND_AI_ENVIRONMENT`
    resolves to exactly `"production"`. Regression guard for the Phase 10
    workstream 11 defect where `api` ran with no `DND_AI_ENVIRONMENT` at
    all — `dnd_ai.config.Settings`' own `"local"` default silently skipped
    production's fail-closed database-identity/HTTPS validation.
  - The three `DND_AI_OIDC_*` settings, if any of them is present and
    non-empty, are all present and non-empty — external OIDC bearer-token
    compatibility is optional (Phase 13B correction: a local-authentication-
    only deployment must be able to start `api` with none of the three
    set), but a partial configuration can never actually serve an
    authenticated route, so this still guards against that half-configured
    state reaching a real deployment.

Deliberately checks these specific invariants rather than diffing the
whole rendered document, so an unrelated, intentional change to the merged
config doesn't fail this check.

check_no_published_ports(), check_data_volume_mount(), and
check_api_environment_configured() take a plain dict (no docker
invocation) so tests/unit/test_check_compose_config.py can exercise both
the pass and fail paths without Docker.
"""

from __future__ import annotations

import json
import sys
from typing import Any


class ComposeConfigError(RuntimeError):
    """One of the invariants below did not hold."""


def check_no_published_ports(config: dict[str, Any], service_name: str = "db") -> None:
    service = config["services"][service_name]
    ports = service.get("ports") or []
    if ports:
        raise ComposeConfigError(
            f"CI's merged compose config publishes host port(s) for `{service_name}`: "
            f"{ports!r} — compose.yaml or compose.ci.yaml regressed; CI must never expose "
            f"{service_name} on a host port (see compose.yaml's header comment)."
        )


def check_data_volume_mount(config: dict[str, Any]) -> None:
    db = config["services"]["db"]
    volumes = db.get("volumes") or []
    targets = [v.get("target") for v in volumes if isinstance(v, dict)]
    if "/var/lib/postgresql" not in targets:
        raise ComposeConfigError(
            "CI's merged compose config does not mount PostgreSQL 18's data "
            f"directory at /var/lib/postgresql (got targets: {targets!r}) — "
            "see compose.yaml's comment on the PostgreSQL 18 image's data-directory layout."
        )


_REQUIRED_API_OIDC_ENV_VARS = ("DND_AI_OIDC_ISSUER", "DND_AI_OIDC_AUDIENCE", "DND_AI_OIDC_JWKS_URL")


def check_api_environment_configured(config: dict[str, Any]) -> None:
    api = config["services"]["api"]
    environment = api.get("environment") or {}
    if environment.get("DND_AI_ENVIRONMENT") != "production":
        raise ComposeConfigError(
            "CI's merged compose config does not run `api` with DND_AI_ENVIRONMENT="
            f"production (got: {environment.get('DND_AI_ENVIRONMENT')!r}) — compose.yaml "
            "regressed; running outside production silently skips database-identity/HTTPS "
            "validation (see compose.yaml's own comment on the api service's environment)."
        )
    configured = [name for name in _REQUIRED_API_OIDC_ENV_VARS if environment.get(name)]
    if configured and len(configured) != len(_REQUIRED_API_OIDC_ENV_VARS):
        missing = sorted(set(_REQUIRED_API_OIDC_ENV_VARS) - set(configured))
        raise ComposeConfigError(
            "CI's merged compose config has a partial OIDC configuration for `api`: "
            f"{configured!r} set, {missing!r} missing or empty — external OIDC bearer-token "
            "compatibility is optional (all three unset is valid), but a partial "
            "configuration can never actually serve an authenticated route (see "
            "compose.yaml's own comment on the api service's environment)."
        )


def check_config(config: dict[str, Any]) -> None:
    check_no_published_ports(config, "db")
    check_no_published_ports(config, "api")
    check_data_volume_mount(config)
    check_api_environment_configured(config)


def main() -> None:
    config = json.load(sys.stdin)
    try:
        check_config(config)
    except ComposeConfigError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
    print(
        "PASS: CI compose config publishes no db/api host port, mounts PostgreSQL 18's "
        "data directory correctly, runs api in production, and has no partial OIDC "
        "configuration."
    )


if __name__ == "__main__":
    main()
