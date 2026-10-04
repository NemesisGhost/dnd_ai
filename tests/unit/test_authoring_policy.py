"""State-precondition policy shared by commands and read models."""

import pytest

from dnd_ai.domain import authoring_policy as policy
from dnd_ai.domain.authoring import (
    LifecycleTransitionNotAllowedError,
    WorldArchivedError,
    WorldHasActiveCampaignsError,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("action", ["update", "create_timeline", "create_campaign"])
def test_world_edits_need_an_active_world(action: str) -> None:
    assert (
        policy.world_blocked_reason(action, lifecycle_status="active", has_blocking_campaigns=False)
        is None
    )
    assert (
        policy.world_blocked_reason(
            action, lifecycle_status="archived", has_blocking_campaigns=False
        )
        == "world_archived"
    )


def test_archive_needs_an_active_world_without_blocking_campaigns() -> None:
    assert (
        policy.world_blocked_reason(
            "archive", lifecycle_status="active", has_blocking_campaigns=False
        )
        is None
    )
    assert (
        policy.world_blocked_reason(
            "archive", lifecycle_status="active", has_blocking_campaigns=True
        )
        == "world_has_active_campaigns"
    )
    assert (
        policy.world_blocked_reason(
            "archive", lifecycle_status="archived", has_blocking_campaigns=False
        )
        == "lifecycle_transition_not_allowed"
    )


def test_restore_needs_an_archived_world() -> None:
    assert (
        policy.world_blocked_reason(
            "restore", lifecycle_status="archived", has_blocking_campaigns=True
        )
        is None
    )
    assert (
        policy.world_blocked_reason(
            "restore", lifecycle_status="active", has_blocking_campaigns=False
        )
        == "lifecycle_transition_not_allowed"
    )


def test_actions_partition_into_available_and_blocked() -> None:
    available, blocked = policy.world_actions(
        lifecycle_status="archived", has_blocking_campaigns=False
    )
    assert available == ["restore"]
    assert {b.action for b in blocked} == set(policy.WORLD_ACTIONS) - {"restore"}


def test_reasons_map_to_the_matching_domain_errors() -> None:
    for reason, error in (
        ("world_archived", WorldArchivedError),
        ("world_has_active_campaigns", WorldHasActiveCampaignsError),
        ("lifecycle_transition_not_allowed", LifecycleTransitionNotAllowedError),
    ):
        with pytest.raises(error):
            policy.raise_for_reason(reason)


def test_unknown_action_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        policy.world_blocked_reason(
            "explode", lifecycle_status="active", has_blocking_campaigns=False
        )
