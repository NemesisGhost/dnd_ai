"""Pure policy for typed world-content authoring (Phase 15.1)."""

import itertools

import pytest

from dnd_ai.domain import entity_lifecycle as el
from dnd_ai.domain.authoring import AuthoringValidationError
from dnd_ai.domain.content_authoring import (
    AUTHORABLE_LOCATION_CATEGORIES,
    LOCATION_CATEGORIES,
    UPDATE,
    content_edit_blocked_reason,
    diff_fields,
    evaluate_content_actions,
    initial_fields,
    is_publish_reference_ready,
    is_reference_eligible,
    location_category,
    normalize_location_fields,
)

CANON = ["draft", "proposed", "approved", "canon", "superseded", "rejected"]
LIFECYCLE = ["active", "archived"]


@pytest.mark.parametrize(
    ("canon", "lifecycle", "expected"),
    [
        ("draft", "active", None),
        ("canon", "active", None),
        ("proposed", "active", "review_in_progress"),
        ("approved", "active", "review_in_progress"),
        ("rejected", "active", "wrong_canon_status"),
        ("superseded", "active", "wrong_canon_status"),
        ("draft", "archived", "entity_archived"),
        ("canon", "archived", "entity_archived"),
    ],
)
def test_edit_policy_table(canon: str, lifecycle: str, expected: str | None) -> None:
    assert content_edit_blocked_reason(canon, lifecycle) == expected


@pytest.mark.parametrize(
    ("canon", "lifecycle", "eligible"),
    [
        ("draft", "active", True),
        ("proposed", "active", True),
        ("approved", "active", True),
        ("canon", "active", True),
        ("rejected", "active", False),
        ("superseded", "active", False),
        ("canon", "archived", False),
        ("draft", "archived", False),
    ],
)
def test_reference_eligibility(canon: str, lifecycle: str, eligible: bool) -> None:
    assert is_reference_eligible(canon, lifecycle) is eligible


def test_only_published_active_records_are_publish_ready() -> None:
    ready = [
        (c, ls)
        for c, ls in itertools.product(CANON, LIFECYCLE)
        if is_publish_reference_ready(c, ls)
    ]
    assert ready == [("canon", "active")]


@pytest.mark.parametrize("type_code", sorted(el.ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES))
@pytest.mark.parametrize(("canon", "lifecycle"), list(itertools.product(CANON, LIFECYCLE)))
def test_the_preview_never_disagrees_with_enforcement(
    type_code: str, canon: str, lifecycle: str
) -> None:
    available, blocked = evaluate_content_actions(
        entity_type_code=type_code, canon_status=canon, lifecycle_status=lifecycle
    )
    assert set(available).isdisjoint({b.action for b in blocked})
    assert (UPDATE in available) == (content_edit_blocked_reason(canon, lifecycle) is None)
    for action in el.ALL_ACTIONS:
        assert (action in available) == (el.blocked_reason(action, canon, lifecycle) is None)
    assert sorted(available + [b.action for b in blocked]) == sorted([UPDATE, *el.ALL_ACTIONS])


def test_a_type_specific_block_only_hides_an_action_the_table_allows() -> None:
    available, blocked = evaluate_content_actions(
        entity_type_code="region",
        canon_status="approved",
        lifecycle_status="active",
        extra_blocked={"publish": "reference_not_published", "approve": "bogus"},
    )
    assert "publish" not in available
    assert {"action": "publish", "reason": "reference_not_published"} in [
        {"action": b.action, "reason": b.reason} for b in blocked
    ]
    # approve is already illegal from `approved`, so its own reason wins.
    assert next(b.reason for b in blocked if b.action == "approve") == "wrong_canon_status"


def test_ineligible_types_report_one_blocked_pseudo_action() -> None:
    available, blocked = evaluate_content_actions(
        entity_type_code="item_instance", canon_status="draft", lifecycle_status="active"
    )
    assert available == [UPDATE]
    assert [b.action for b in blocked] == ["all"]


def test_the_location_catalog_is_closed_and_excludes_dungeons() -> None:
    assert len(LOCATION_CATEGORIES) == 10
    assert AUTHORABLE_LOCATION_CATEGORIES.isdisjoint({"dungeon", "dungeon_area"})
    assert AUTHORABLE_LOCATION_CATEGORIES <= el.ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES
    for code in ("dungeon", "dungeon_area", "npc", "", "Region"):
        with pytest.raises(AuthoringValidationError):
            location_category(code)


def test_location_field_normalization() -> None:
    assert normalize_location_fields(
        category_code="settlement", name="  Hollow  ", summary="  ", population=5, building_use=None
    ) == ("Hollow", None, 5, None)
    assert normalize_location_fields(
        category_code="building", name="Inn", summary="x", population=None, building_use=" Tavern "
    ) == ("Inn", "x", None, "Tavern")
    base = {"name": "x", "summary": None, "population": None, "building_use": None}
    bad = [
        {**base, "category_code": "region", "population": 1},
        {**base, "category_code": "settlement", "building_use": "a"},
        {**base, "category_code": "settlement", "population": -1},
        {**base, "category_code": "settlement", "population": 2**31},
        {**base, "category_code": "settlement", "population": True},
        {**base, "category_code": "building", "building_use": "y" * 201},
        {**base, "category_code": "region", "name": " "},
        {**base, "category_code": "region", "name": "x" * 201},
    ]
    for kwargs in bad:
        with pytest.raises(AuthoringValidationError):
            normalize_location_fields(**kwargs)  # type: ignore[arg-type]


def test_diff_lists_only_changed_fields_and_redacts_content() -> None:
    # Structural fields keep their values; unlisted (content) fields are redacted.
    assert diff_fields({"population": 1, "name": "x"}, {"population": 1, "name": "y"}) == {
        "name": {"from": "x", "to": "y"}
    }
    assert diff_fields({}, {"summary": None}) == {}
    changed = diff_fields({"summary": "old narrative"}, {"summary": "new narrative"})
    assert changed == {"summary": {"from": {"redacted": True}, "to": {"redacted": True}}}
    assert "narrative" not in str(changed)
    # An unknown field is redacted by default (default deny).
    assert diff_fields({}, {"brand_new_field": "secret"}) == {
        "brand_new_field": {"from": None, "to": {"redacted": True}}
    }
    long_name = "z" * 500
    shown = diff_fields({"name": ""}, {"name": long_name})["name"]["to"]
    assert shown == {"value": "z" * 200, "truncated": True}
    assert initial_fields({"summary": None, "population": 2}) == {"population": 2}
    assert initial_fields({"notes": "private"}) == {"notes": {"redacted": True}}
