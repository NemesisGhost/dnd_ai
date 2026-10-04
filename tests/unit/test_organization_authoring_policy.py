"""Pure contract for typed Organization authoring (Phase 15.1)."""

import pytest

from dnd_ai.domain.authoring import AuthoringValidationError
from dnd_ai.domain.entity_lifecycle import ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES
from dnd_ai.domain.organization_authoring import (
    AUTHORABLE_ORGANIZATION_KINDS,
    GENERIC_ORGANIZATION_TYPES,
    ORGANIZATION_ENTITY_TYPE_CODES,
    ORGANIZATION_KINDS,
    normalize_optional_text,
    normalize_typed_fields,
    organization_kind,
    organization_type_for,
)


def test_the_catalog_matches_the_lifecycle_eligible_organization_types() -> None:
    assert AUTHORABLE_ORGANIZATION_KINDS == ORGANIZATION_ENTITY_TYPE_CODES
    assert ORGANIZATION_ENTITY_TYPE_CODES <= ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES
    assert len(ORGANIZATION_KINDS) == 6


def test_only_the_generic_kind_chooses_its_organization_type() -> None:
    for kind in ORGANIZATION_KINDS:
        if kind.code == "organization":
            assert kind.organization_type is None
        else:
            assert kind.organization_type == kind.code
    generic = {value for value, _ in GENERIC_ORGANIZATION_TYPES}
    # None of the fixed kinds can be chosen through the generic kind.
    assert generic.isdisjoint({k.code for k in ORGANIZATION_KINDS})


def test_organization_type_resolution() -> None:
    generic = organization_kind("organization")
    assert (
        organization_type_for(generic, {"organization_type": "secret_society"}) == "secret_society"
    )
    assert organization_type_for(organization_kind("government"), {}) == "government"


@pytest.mark.parametrize("code", ["", "Government", "dungeon", "npc", "religion", "location"])
def test_unknown_kinds_are_refused(code: str) -> None:
    with pytest.raises(AuthoringValidationError):
        organization_kind(code)


def test_typed_field_normalization() -> None:
    business = organization_kind("business")
    assert normalize_typed_fields(
        business, {"business_type": "  Forge ", "operating_status": "closed", "reputation": -100}
    ) == {"business_type": "Forge", "operating_status": "closed", "reputation": -100}
    assert normalize_typed_fields(business, {}) == {
        "business_type": None,
        "operating_status": None,
        "reputation": None,
    }
    assert normalize_typed_fields(organization_kind("government"), {"government_form": "  "}) == {
        "government_form": None
    }


@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        ("business", {"operating_status": "thriving"}),
        ("business", {"reputation": 101}),
        ("business", {"reputation": -101}),
        ("business", {"reputation": True}),
        ("business", {"reputation": "5"}),
        ("business", {"business_type": "x" * 201}),
        ("business", {"unit_type": "x"}),
        ("government", {"ideology": "x"}),
        ("government", {"government_form": 5}),
        ("political_faction", {"ideology": "x" * 4001}),
        ("organization", {}),
        ("organization", {"organization_type": "government"}),
        ("religious_organization", {"government_form": "x"}),
    ],
)
def test_invalid_typed_fields_are_refused(kind: str, raw: dict) -> None:
    with pytest.raises(AuthoringValidationError):
        normalize_typed_fields(organization_kind(kind), raw)


def test_explicit_none_for_an_inapplicable_field_is_ignored() -> None:
    assert normalize_typed_fields(organization_kind("government"), {"unit_type": None}) == {
        "government_form": None
    }


def test_optional_text_bounds() -> None:
    assert normalize_optional_text("  x ", field="f", max_length=3) == "x"
    assert normalize_optional_text("  ", field="f", max_length=3) is None
    with pytest.raises(AuthoringValidationError):
        normalize_optional_text("xxxx", field="f", max_length=3)
