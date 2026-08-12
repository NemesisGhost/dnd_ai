"""check_compose_config's pure invariant checks, exercised against fabricated
merged-config dicts rather than a real `docker compose config` — no Docker
needed. See scripts/check_compose_config.py's module docstring for what
these two invariants protect and why.
"""

import pytest
from check_compose_config import (
    ComposeConfigError,
    check_config,
    check_data_volume_mount,
    check_no_published_ports,
)

pytestmark = pytest.mark.unit


def _config(
    *, ports: list[object] | None = None, volume_target: str = "/var/lib/postgresql"
) -> dict:
    db: dict[str, object] = {"volumes": [{"type": "volume", "target": volume_target}]}
    if ports is not None:
        db["ports"] = ports
    return {"services": {"db": db}}


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
