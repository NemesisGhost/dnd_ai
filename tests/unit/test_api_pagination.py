"""Pure unit tests for `dnd_ai.api.pagination` — the keyset-cursor helper
introduced for the Phase 13D World Explorer and Knowledge browse endpoints
(docs/PHASE13D_BACKEND_READINESS.md §9's "focused pure unit tests for
cursor encode/decode/validation"). No database.
"""

import base64
import json
import uuid

import pytest

from dnd_ai.api.errors import InvalidCursorError
from dnd_ai.api.pagination import (
    _MAX_CURSOR_BYTES,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    build_page,
    decode_cursor,
    decode_typed_cursor,
    encode_cursor,
)

pytestmark = pytest.mark.unit


def test_round_trips_a_string_and_uuid_keyset() -> None:
    raw = encode_cursor("world_entities", ["Amber Keep", "11111111-1111-1111-1111-111111111111"])
    assert decode_cursor(raw, keyset="world_entities", arity=2) == (
        "Amber Keep",
        "11111111-1111-1111-1111-111111111111",
    )


def test_round_trips_an_int_and_none_component() -> None:
    raw = encode_cursor("recent_discoveries", [None, 42])
    assert decode_cursor(raw, keyset="recent_discoveries", arity=2) == (None, 42)


def test_no_cursor_is_the_first_page() -> None:
    assert decode_cursor(None, keyset="world_entities", arity=2) is None
    assert decode_cursor("", keyset="world_entities", arity=2) is None


def test_cursor_is_opaque_not_plaintext() -> None:
    raw = encode_cursor("world_entities", ["Secret Name", "id"])
    assert "Secret Name" not in raw


def test_a_cursor_for_a_different_keyset_is_rejected() -> None:
    raw = encode_cursor("world_entities", ["x", "y"])
    with pytest.raises(InvalidCursorError):
        decode_cursor(raw, keyset="world_relationships", arity=2)


def test_wrong_arity_is_rejected() -> None:
    raw = encode_cursor("world_entities", ["x", "y"])
    with pytest.raises(InvalidCursorError):
        decode_cursor(raw, keyset="world_entities", arity=3)


@pytest.mark.parametrize(
    "bad",
    [
        "not base64!!!",
        "",  # handled as first-page, but the '=' padded variant below is not
        base64.urlsafe_b64encode(b"not json").decode().rstrip("="),
        base64.urlsafe_b64encode(json.dumps({"v": 1}).encode()).decode().rstrip("="),
        base64.urlsafe_b64encode(json.dumps([1, "world_entities"]).encode()).decode().rstrip("="),
        base64.urlsafe_b64encode(json.dumps([999, "world_entities", ["x", "y"]]).encode())
        .decode()
        .rstrip("="),
        base64.urlsafe_b64encode(
            json.dumps([1, "world_entities", ["x", {"nested": "obj"}]]).encode()
        )
        .decode()
        .rstrip("="),
        base64.urlsafe_b64encode(json.dumps([1, "world_entities", ["x", True]]).encode())
        .decode()
        .rstrip("="),
    ],
)
def test_malformed_cursors_raise_invalid_cursor(bad: str) -> None:
    if bad == "":
        assert decode_cursor(bad, keyset="world_entities", arity=2) is None
        return
    with pytest.raises(InvalidCursorError):
        decode_cursor(bad, keyset="world_entities", arity=2)


def test_an_oversized_cursor_is_rejected_without_parsing() -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor("A" * 5000, keyset="world_entities", arity=2)


def test_a_sql_injection_shaped_cursor_component_survives_decode_as_plain_text() -> None:
    # It is not this module's job to reject SQL-shaped text — the value is
    # bound as a parameter downstream — but it must round-trip verbatim and
    # never be interpreted here.
    payload = "'; DROP TABLE core.entities; --"
    raw = encode_cursor("world_entities", [payload, "id"])
    assert decode_cursor(raw, keyset="world_entities", arity=2) == (payload, "id")


def test_encode_rejects_a_non_scalar_value() -> None:
    with pytest.raises(TypeError):
        encode_cursor("world_entities", [{"a": 1}])


@pytest.mark.parametrize(
    "sort_key",
    [
        "\U0001f409" * 200,  # 200 supplementary-plane code points (a dragon emoji)
        "é中ā" * 66 + "é中",  # mixed Latin-1 + CJK, 200 code points
        "\x01\x1f" * 100,  # 200 C0 control chars — the JSON-escape-heavy worst case
        "a" * 200,  # long ASCII
    ],
)
def test_a_200_codepoint_sort_key_round_trips_within_the_size_bound(sort_key: str) -> None:
    """A server-issued cursor for any 200-code-point sort-key prefix (the
    `_STATEMENT_SORT_PREFIX` / `_NAME_SORT_PREFIX` bound) must both fit
    `_MAX_CURSOR_BYTES` and decode back to the exact same value — the
    review's Unicode finding: `ensure_ascii` escaping made emoji cursors
    exceed the decoder limit."""
    raw = encode_cursor(
        "knowledge_by_statement", [sort_key, "11111111-1111-1111-1111-111111111111"]
    )
    assert len(raw) <= _MAX_CURSOR_BYTES
    assert decode_cursor(raw, keyset="knowledge_by_statement", arity=2) == (
        sort_key,
        "11111111-1111-1111-1111-111111111111",
    )


def test_encode_raises_rather_than_emit_a_cursor_it_would_reject() -> None:
    huge = "\U0001f409" * 4000
    with pytest.raises(ValueError, match="over the"):
        encode_cursor("knowledge_by_statement", [huge, "id"])


# ---------------------------------------------------------------------------
# decode_typed_cursor — per-field type validation (Issue 3: 422 not 500)
# ---------------------------------------------------------------------------


def _forged(keyset: str, values: list[object]) -> str:
    return (
        base64.urlsafe_b64encode(
            json.dumps([1, keyset, values], separators=(",", ":")).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )


def test_typed_cursor_returns_already_typed_values() -> None:
    raw = encode_cursor("k", ["a name", "11111111-1111-1111-1111-111111111111"])
    result = decode_typed_cursor(raw, keyset="k", fields=("str", "uuid"))
    assert result == ("a name", uuid.UUID("11111111-1111-1111-1111-111111111111"))


def test_typed_cursor_none_for_the_first_page() -> None:
    assert decode_typed_cursor(None, keyset="k", fields=("uuid",)) is None
    assert decode_typed_cursor("", keyset="k", fields=("str", "uuid")) is None


def test_typed_cursor_allows_a_nullable_int_field() -> None:
    raw = encode_cursor("recent", [None, "11111111-1111-1111-1111-111111111111"])
    assert decode_typed_cursor(raw, keyset="recent", fields=("int_or_none", "uuid")) == (
        None,
        uuid.UUID("11111111-1111-1111-1111-111111111111"),
    )
    raw2 = encode_cursor("recent", [42, "11111111-1111-1111-1111-111111111111"])
    assert decode_typed_cursor(raw2, keyset="recent", fields=("int_or_none", "uuid"))[0] == 42


@pytest.mark.parametrize(
    ("fields", "values"),
    [
        (("str", "uuid"), ["ok", "not-a-uuid"]),  # invalid UUID string
        (("str", "uuid"), ["ok", 12345]),  # number where a UUID string is expected
        (
            ("str", "uuid"),
            [None, "11111111-1111-1111-1111-111111111111"],
        ),  # null where str required
        (("str", "uuid"), [123, "11111111-1111-1111-1111-111111111111"]),  # int where str required
        (("int_or_none", "uuid"), ["12", "11111111-1111-1111-1111-111111111111"]),  # numeric string
        (("int_or_none", "uuid"), [True, "11111111-1111-1111-1111-111111111111"]),  # bool as int
        (("uuid",), [42]),  # number where a UUID is expected
        (("str", "uuid"), ["only one"]),  # missing a required field
        (("str", "uuid"), ["a", "11111111-1111-1111-1111-111111111111", "extra"]),  # wrong arity
    ],
)
def test_typed_cursor_rejects_bad_field_values_with_invalid_cursor(
    fields: tuple[str, ...], values: list[object]
) -> None:
    with pytest.raises(InvalidCursorError):
        decode_typed_cursor(_forged("k", values), keyset="k", fields=fields)  # type: ignore[arg-type]


def test_typed_cursor_rejects_a_cursor_for_a_different_keyset() -> None:
    raw = encode_cursor("world_entities", ["x", "11111111-1111-1111-1111-111111111111"])
    with pytest.raises(InvalidCursorError):
        decode_typed_cursor(raw, keyset="knowledge_recent", fields=("str", "uuid"))


# ---------------------------------------------------------------------------
# build_page
# ---------------------------------------------------------------------------


def _rows(n: int) -> list[dict[str, object]]:
    return [{"name": f"n{i:03d}", "entity_id": f"id{i:03d}"} for i in range(n)]


def _key(row: dict[str, object]) -> list[object]:
    return [row["name"], row["entity_id"]]


def test_build_page_without_an_extra_row_is_the_last_page() -> None:
    page = build_page(_rows(3), limit=5, keyset="world_entities", cursor_key=_key)
    assert len(page.items) == 3
    assert page.next_cursor is None


def test_build_page_with_an_extra_row_trims_and_emits_a_cursor() -> None:
    page = build_page(_rows(6), limit=5, keyset="world_entities", cursor_key=_key)
    assert len(page.items) == 5
    assert page.next_cursor is not None
    assert decode_cursor(page.next_cursor, keyset="world_entities", arity=2) == ("n004", "id004")


def test_build_page_exactly_full_is_the_last_page() -> None:
    page = build_page(_rows(5), limit=5, keyset="world_entities", cursor_key=_key)
    assert len(page.items) == 5
    assert page.next_cursor is None


def test_build_page_empty_result() -> None:
    page = build_page([], limit=5, keyset="world_entities", cursor_key=_key)
    assert page.items == []
    assert page.next_cursor is None


def test_build_page_rejects_a_bad_limit() -> None:
    with pytest.raises(ValueError):
        build_page(_rows(1), limit=0, keyset="world_entities", cursor_key=_key)


def test_page_size_bounds_are_sane() -> None:
    assert 1 <= DEFAULT_PAGE_SIZE <= MAX_PAGE_SIZE
