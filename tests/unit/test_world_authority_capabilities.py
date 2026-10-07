import uuid

import pytest

from dnd_ai.domain.world_authority import (
    GLOBAL_CAPABILITIES,
    WORLD_MANAGEMENT_CAPABILITIES,
    WORLD_ROLE_CAPABILITIES,
    WorldAuthority,
    capabilities_for_roles,
)

pytestmark = pytest.mark.unit


def _authority(
    *roles: str, may_administer: bool = True, has_use_grant: bool = False
) -> WorldAuthority:
    return WorldAuthority(
        world_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role_codes=frozenset(roles),
        world_lifecycle_status="active",
        may_administer=may_administer,
        has_use_grant=has_use_grant,
    )


OWNER = {
    "world.view",
    "world.canon.read",
    "world.canon.read_private",
    "world.canon.edit",
    "world.canon.review",
    "world.manage",
    "timeline.manage",
    "world.share",
    "world.transfer",
    "campaign.create",
}
EDITOR = {
    "world.view",
    "world.canon.read",
    "world.canon.read_private",
    "world.canon.edit",
    "timeline.manage",
}
REVIEWER = {"world.view", "world.canon.read", "world.canon.read_private", "world.canon.review"}
READER = {"world.view", "world.canon.read"}


def test_each_role_carries_its_explicit_capability_set() -> None:
    assert _authority("world_owner").capabilities == OWNER
    assert _authority("world_editor").capabilities == EDITOR
    assert _authority("world_reviewer").capabilities == REVIEWER
    assert _authority("world_reader").capabilities == READER


def test_roles_combine_as_a_union_without_hierarchy() -> None:
    assert _authority("world_editor", "world_reviewer").capabilities == EDITOR | REVIEWER
    assert _authority("world_reader", "world_editor").capabilities == EDITOR
    assert "world.canon.review" not in _authority("world_editor").capabilities
    assert "world.canon.edit" not in _authority("world_reviewer").capabilities


def test_a_reader_sees_published_canon_only() -> None:
    reader = _authority("world_reader")
    assert reader.has_capability("world.canon.read")
    assert not reader.has_capability("world.canon.read_private")
    assert not reader.has_capability("campaign.create")


def test_a_use_grant_confers_view_and_hosting_and_nothing_else() -> None:
    grant = _authority(has_use_grant=True)
    assert grant.capabilities == {"world.view", "campaign.create"}
    # Reading is a separate permission from using the world.
    assert not grant.has_capability("world.canon.read")


def test_reader_access_does_not_imply_world_use() -> None:
    assert not _authority("world_reader").has_capability("campaign.create")


def test_timeline_management_is_owner_and_editor_only() -> None:
    assert _authority("world_owner").has_capability("timeline.manage")
    assert _authority("world_editor").has_capability("timeline.manage")
    assert not _authority("world_reviewer").has_capability("timeline.manage")
    assert not _authority("world_reader").has_capability("timeline.manage")
    assert not _authority(has_use_grant=True).has_capability("timeline.manage")


def test_without_system_gm_the_world_management_capabilities_are_withheld() -> None:
    owner = _authority("world_owner", may_administer=False)
    assert owner.capabilities == OWNER - WORLD_MANAGEMENT_CAPABILITIES
    # Editing, reviewing, reading and timeline work are unaffected.
    for capability in ("world.canon.edit", "world.canon.review", "timeline.manage", "world.view"):
        assert owner.has_capability(capability)
    assert not _authority(has_use_grant=True, may_administer=False).has_capability(
        "campaign.create"
    )


def test_unknown_role_carries_nothing() -> None:
    authority = _authority("mystery_role")
    assert authority.capabilities == frozenset()
    assert not authority.has_capability("world.view")


def test_no_roles_means_no_capabilities() -> None:
    assert capabilities_for_roles(frozenset(), may_administer=True) == frozenset()


def test_world_codes_are_not_campaign_capability_codes() -> None:
    campaign_codes = {"campaign.view", "canon.edit", "access.manage", "import.approve"}
    for caps in WORLD_ROLE_CAPABILITIES.values():
        assert not caps & campaign_codes


def test_only_world_create_is_global() -> None:
    assert {"world.create"} == GLOBAL_CAPABILITIES
