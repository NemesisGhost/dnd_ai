"""Pure canon-lifecycle policy: transition table, eligibility registry, previews."""

import pytest

from dnd_ai.domain import entity_lifecycle as el
from dnd_ai.domain.authoring import LifecycleNotSupportedError, LifecycleTransitionNotAllowedError

pytestmark = pytest.mark.unit

CANON = ["draft", "proposed", "approved", "canon", "superseded", "rejected", "deprecated"]

ALLOWED_CANON = {
    (el.SUBMIT_FOR_REVIEW, "draft"): "proposed",
    (el.RETURN_TO_DRAFT, "proposed"): "draft",
    (el.RETURN_TO_DRAFT, "approved"): "draft",
    (el.RETURN_TO_DRAFT, "rejected"): "draft",
    (el.APPROVE, "proposed"): "approved",
    (el.REJECT, "draft"): "rejected",
    (el.REJECT, "proposed"): "rejected",
    (el.PUBLISH, "approved"): "canon",
    (el.SUPERSEDE, "canon"): "superseded",
}


@pytest.mark.parametrize("action", sorted({a for a, _ in ALLOWED_CANON}))
@pytest.mark.parametrize("canon", CANON)
def test_canon_transitions_match_the_table_exactly(action: str, canon: str) -> None:
    expected = ALLOWED_CANON.get((action, canon))
    assert el.target_canon_status(action, canon) == expected
    if expected is None:
        with pytest.raises(LifecycleTransitionNotAllowedError):
            el.require_transition(action, canon, "active")
    else:
        el.require_transition(action, canon, "active")


@pytest.mark.parametrize("action", sorted({a for a, _ in ALLOWED_CANON}))
@pytest.mark.parametrize("lifecycle", ["archived", "inactive", "pending", "deleted"])
def test_canon_transitions_need_an_active_entity(action: str, lifecycle: str) -> None:
    canon = next(c for (a, c) in ALLOWED_CANON if a == action)
    with pytest.raises(LifecycleTransitionNotAllowedError):
        el.require_transition(action, canon, lifecycle)


@pytest.mark.parametrize("canon", CANON)
def test_archive_is_blocked_only_during_review(canon: str) -> None:
    blocked = canon in ("proposed", "approved")
    assert (el.blocked_reason(el.ARCHIVE, canon, "active") is not None) == blocked
    assert el.blocked_reason(el.ARCHIVE, canon, "archived") == el.BLOCKED_ENTITY_ARCHIVED


@pytest.mark.parametrize("canon", CANON)
def test_restore_needs_an_archived_entity_and_ignores_canon(canon: str) -> None:
    assert el.blocked_reason(el.RESTORE, canon, "archived") is None
    assert el.blocked_reason(el.RESTORE, canon, "active") == el.BLOCKED_ENTITY_NOT_ARCHIVED


@pytest.mark.parametrize("canon", CANON)
@pytest.mark.parametrize("lifecycle", ["active", "archived"])
def test_delete_draft_only_for_draft_or_rejected(canon: str, lifecycle: str) -> None:
    ok = canon in ("draft", "rejected")
    assert (el.blocked_reason(el.DELETE_DRAFT, canon, lifecycle) is None) == ok


def test_delete_draft_is_not_available_once_deleted() -> None:
    assert el.blocked_reason(el.DELETE_DRAFT, "draft", "deleted") is not None


def test_deprecated_has_no_transitions() -> None:
    for action in (el.SUBMIT_FOR_REVIEW, el.APPROVE, el.PUBLISH, el.SUPERSEDE, el.REJECT):
        assert el.blocked_reason(action, "deprecated", "active") is not None


def test_registry_excludes_every_documented_exclusion() -> None:
    assert not (
        el.ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES & set(el.ENTITY_LIFECYCLE_EXCLUDED_TYPE_CODES)
    )
    for code in ("character", "player_character", "event", "knowledge_item"):
        assert not el.is_lifecycle_eligible(code)
        with pytest.raises(LifecycleNotSupportedError):
            el.require_lifecycle_eligible(code)
    assert el.is_lifecycle_eligible("location")
    assert el.is_lifecycle_eligible("npc")
    assert el.is_lifecycle_eligible("quest")


def test_previews_use_the_same_policy_as_enforcement() -> None:
    for canon in CANON:
        for lifecycle in ("active", "archived"):
            available, blocked = el.evaluate_actions(
                entity_type_code="location", canon_status=canon, lifecycle_status=lifecycle
            )
            assert set(available).isdisjoint({b.action for b in blocked})
            assert set(available) | {b.action for b in blocked} == set(el.ALL_ACTIONS)
            for action in available:
                el.require_transition(action, canon, lifecycle)


def test_an_ineligible_type_previews_as_wholly_blocked() -> None:
    available, blocked = el.evaluate_actions(
        entity_type_code="player_character", canon_status="draft", lifecycle_status="active"
    )
    assert available == []
    assert [(b.action, b.reason) for b in blocked] == [("all", el.BLOCKED_NOT_SUPPORTED)]
