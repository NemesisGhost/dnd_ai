import re

import pytest

from dnd_ai.domain.authoring import (
    AuthoringValidationError,
    normalize_description,
    normalize_label,
    normalize_name,
    normalize_reason,
    slugify,
)

pytestmark = pytest.mark.unit


def test_name_is_stripped_and_bounded() -> None:
    assert normalize_name("  Eberron  ") == "Eberron"
    assert normalize_name("x" * 200) == "x" * 200
    for bad in (None, "", "   ", "x" * 201):
        with pytest.raises(AuthoringValidationError):
            normalize_name(bad)


def test_description_blank_becomes_none() -> None:
    assert normalize_description(None) is None
    assert normalize_description("  ") is None
    assert normalize_description(" hi ") == "hi"
    with pytest.raises(AuthoringValidationError):
        normalize_description("x" * 4001)


def test_reason_optional_unless_required() -> None:
    assert normalize_reason(None) is None
    assert normalize_reason("  ") is None
    with pytest.raises(AuthoringValidationError):
        normalize_reason("  ", required=True)
    with pytest.raises(AuthoringValidationError):
        normalize_reason("x" * 1001)
    assert normalize_reason(" why ", required=True) == "why"


def test_label_is_required_and_bounded() -> None:
    assert normalize_label(" The Fall ") == "The Fall"
    with pytest.raises(AuthoringValidationError):
        normalize_label("")
    with pytest.raises(AuthoringValidationError):
        normalize_label("x" * 201)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Eberron", "eberron"),
        ("The  Sword Coast!", "the-sword-coast"),
        ("", "world"),
        ("!!!", "world"),
        ("2nd Age", "world-2nd-age"),
        ("é", "world"),
    ],
)
def test_slugify(name: str, expected: str) -> None:
    assert slugify(name) == expected


def test_slugify_truncates_and_matches_the_column_pattern() -> None:
    slug = slugify("a" * 200)
    assert len(slug) <= 60
    assert re.fullmatch(r"[a-z][a-z0-9-]*", slug)
    assert re.fullmatch(r"[a-z][a-z0-9-]*", slugify("a" + "-" * 70 + "b"))
