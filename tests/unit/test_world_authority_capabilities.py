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
    WORLD_ROLE_CAPABILITIES,
    WorldAuthority,
    authorized_actions,
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
    viewer = capabilities_for_roles(frozenset({"world_viewer"}))
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
    owner = capabilities_for_roles(frozenset({"world_owner"}))
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
