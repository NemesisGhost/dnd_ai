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
    # what both services interpolate.
    content = (REPO_ROOT / "compose.yaml").read_text()
    assert "POSTGRES_PASSWORD:-" not in content, (
        "compose.yaml must not give POSTGRES_PASSWORD a fallback default — "
        "it is required, per docs/DEVELOPMENT.md §3.6."
    )
    assert content.count("POSTGRES_PASSWORD:?") >= 2, (
        "Both the db and migrate services must require POSTGRES_PASSWORD explicitly."
    )
