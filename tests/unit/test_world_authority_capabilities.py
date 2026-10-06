import uuid

import pytest

from dnd_ai.domain.world_authority import (
    GLOBAL_CAPABILITIES,
    WORLD_ROLE_CAPABILITIES,
    WorldAuthority,
    capabilities_for_roles,
)

pytestmark = pytest.mark.unit


def _authority(*roles: str) -> WorldAuthority:
    return WorldAuthority(
        world_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role_codes=frozenset(roles),
        world_lifecycle_status="active",
    )


def test_world_owner_carries_the_closed_capability_set() -> None:
    assert _authority("world_owner").capabilities == {
        "world.view",
        "world.manage",
        "timeline.manage",
        "campaign.create",
    }


def test_unknown_role_carries_nothing() -> None:
    authority = _authority("mystery_role")
    assert authority.capabilities == frozenset()
    assert not authority.has_capability("world.view")


def test_no_roles_means_no_capabilities() -> None:
    assert capabilities_for_roles(frozenset()) == frozenset()


def test_world_codes_are_not_campaign_capability_codes() -> None:
    campaign_codes = {"campaign.view", "canon.edit", "access.manage", "import.approve"}
    for caps in WORLD_ROLE_CAPABILITIES.values():
        assert not caps & campaign_codes


def test_only_world_create_is_global() -> None:
    assert {"world.create"} == GLOBAL_CAPABILITIES
