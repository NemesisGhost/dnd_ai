"""Unit tests for dnd_ai.persistence.seeds — pure logic, no database.

See docs/DEVELOPMENT.md §6 (unit tests use no database).
"""

import pytest

from dnd_ai.persistence.seeds import _adapt_value

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("draft", "draft"),
        (5, 5),
        (True, True),
        (None, None),
    ],
)
def test_adapt_value_passes_scalars_through(value: object, expected: object) -> None:
    assert _adapt_value(value) is expected or _adapt_value(value) == expected


def test_adapt_value_serializes_dict_to_json_text() -> None:
    assert _adapt_value({"a": 1}) == '{"a": 1}'


def test_adapt_value_serializes_list_to_json_text() -> None:
    assert _adapt_value([1, 2, 3]) == "[1, 2, 3]"
