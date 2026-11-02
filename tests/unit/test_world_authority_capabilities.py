import uuid

import pytest

from dnd_ai.domain.authoring_policy import (
    TIMELINE_ACTIONS,
    WORLD_ACTIONS,
    BlockedAction,
    timeline_actions,
    world_actions,
)
from dnd_ai.domain.world_authority import (
    GLOBAL_CAPABILITIES,
    TIMELINE_ACTION_CAPABILITIES,
    WORLD_ACTION_CAPABILITIES,
    WORLD_MANAGEMENT_CAPABILITIES,
    WORLD_ROLE_CAPABILITIES,
    WorldAuthority,
    authorized_actions,
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


def test_world_viewer_carries_world_view_only() -> None:
    authority = _authority("world_viewer")
    assert authority.capabilities == {"world.view"}
    for capability in ("world.manage", "timeline.manage", "campaign.create", "world.create"):
        assert not authority.has_capability(capability)


def test_owner_and_viewer_together_are_the_owner() -> None:
    assert (
        _authority("world_owner", "world_viewer").capabilities
        == _authority("world_owner").capabilities
    )


def _all_world_actions() -> tuple[list[str], list[BlockedAction]]:
    return world_actions(lifecycle_status="active", has_blocking_campaigns=True)


def test_a_viewer_is_offered_no_world_or_timeline_action() -> None:
    viewer = capabilities_for_roles(frozenset({"world_viewer"}), may_administer=True)
    assert authorized_actions(
        *_all_world_actions(), capabilities=viewer, required=WORLD_ACTION_CAPABILITIES
    ) == ([], [])
    assert authorized_actions(
        *timeline_actions(
            world_status="active",
            timeline_status="active",
            is_primary=True,
            has_blocking_campaigns=False,
        ),
        capabilities=viewer,
        required=TIMELINE_ACTION_CAPABILITIES,
    ) == ([], [])


def test_an_owner_keeps_every_world_action_and_its_blocked_reasons() -> None:
    owner = capabilities_for_roles(frozenset({"world_owner"}), may_administer=True)
    assert (
        authorized_actions(
            *_all_world_actions(), capabilities=owner, required=WORLD_ACTION_CAPABILITIES
        )
        == _all_world_actions()
    )


def test_each_action_needs_its_own_capability_and_unknown_actions_are_dropped() -> None:
    available, blocked = authorized_actions(
        ["update", "create_timeline", "create_campaign", "mystery"],
        [BlockedAction(action="archive", reason="world_has_active_campaigns")],
        capabilities=frozenset({"world.view", "campaign.create"}),
        required=WORLD_ACTION_CAPABILITIES,
    )
    assert (available, blocked) == (["create_campaign"], [])


def test_every_reportable_action_has_a_required_capability() -> None:
    assert set(WORLD_ACTIONS) == set(WORLD_ACTION_CAPABILITIES)
    assert set(TIMELINE_ACTIONS) == set(TIMELINE_ACTION_CAPABILITIES)
