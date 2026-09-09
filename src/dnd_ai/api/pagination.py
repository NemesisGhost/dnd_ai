"""Keyset (cursor) pagination for the Phase 13D World Explorer and Knowledge
browse endpoints — introduced narrowly for exactly those routes, not as a
generalized query framework (docs/PHASE13D_BACKEND_READINESS.md §3/§9,
docs/DATABASE_CONVENTIONS.md §30.4 "use keyset pagination for large tables
where practical").

Why keyset, not offset: an `OFFSET n` skips rows *after* the audience
filter has run, so if a resource-grant deny (or a discovery rule) removes a
row between two page requests the offsets shift and a genuinely-visible row
is silently skipped or repeated — the "no offset-dependent hidden-record
leakage" property this workstream's own spec requires. A keyset cursor
carries the *sort key of the last row already returned*; the next page is
`WHERE (sort key) > (cursor)` under the identical, deterministic
`ORDER BY`, so paging is stable regardless of inserts, deletes, or
visibility changes between requests.

The cursor is an **opaque, validated** token, not a signed one: this
application has no general signing secret (a search of `dnd_ai.config`
found none), and it does not need one here. `decode_cursor` strictly
validates structure and value types on the way in, and every decoded value
is passed to the query layer as a **bound SQL parameter**, never
interpolated — so a tampered cursor can neither inject SQL nor widen
access: the keyset predicate is applied *after* every authorization and
visibility filter and can only ever narrow an already-authorized,
already-filtered result set (it moves the start of the window forward, it
never adds rows). The embedded `keyset` name additionally binds a cursor
to the one endpoint family that issued it, so a cursor minted by one
browse endpoint is rejected by another rather than silently
mis-interpreted.

No total count is returned by any endpoint built on this module — a count
that included inaccessible rows would violate the non-disclosure rules
(docs/UI_DESIGN.md §9: "Counts describe only accessible records";
"Pagination totals exclude inaccessible records"), and an
audience-filtered count is both unnecessary for the World/Knowledge MVP
screens and an extra full scan per request. A page simply reports whether
a `next_cursor` exists.
"""

import base64
import binascii
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from .errors import InvalidCursorError

# The wire format version embedded in every cursor. Bump only on an
# incompatible change to the encoded shape; an older/newer value is
# rejected by `decode_cursor` exactly like any other malformed cursor.
_CURSOR_VERSION: Final = 1

# A decoded cursor value is always one of these JSON scalar types. UUIDs
# travel as their canonical string form and are re-parsed by the caller;
# `None` is permitted so a keyset whose trailing component is a nullable
# column (e.g. a world-time sort key that may be absent) can still be
# expressed. Anything else in the decoded array is a malformed cursor.
CursorValue = str | int | None

# Bound for the base64 payload we will even attempt to decode — a keyset is
# at most a handful of short scalars, so anything larger is not a cursor
# this module ever produced.
_MAX_CURSOR_BYTES: Final = 2048

# The default and hard-maximum page size shared by every browse endpoint
# in this workstream. `limit` is validated by FastAPI's own
# `Query(ge=1, le=MAX_PAGE_SIZE)` at each route (a 422 `invalid_request` on
# violation — the standard request-validation contract), so this module
# only needs to name the two bounds.
DEFAULT_PAGE_SIZE: Final = 25
MAX_PAGE_SIZE: Final = 100


@dataclass(frozen=True)
class Page[Row]:
    """One keyset page: the rows to return (already trimmed to the
    requested `limit`, in the query's own order) and the cursor for the
    following page, or `None` when this is the last page.

    `next_cursor` is `None` iff the underlying query returned no more than
    `limit` rows — see `build_page`, which fetches `limit + 1` and uses the
    presence of the extra row as the "there is a next page" signal without
    ever counting the full result set.
    """

    items: list[Row]
    next_cursor: str | None


def encode_cursor(keyset: str, values: Sequence[object]) -> str:
    """Serialize a keyset tuple into an opaque cursor string.

    `keyset` names the endpoint family (e.g. `"world_entities"`); it is
    embedded so `decode_cursor` can reject a cursor replayed against a
    different endpoint. `values` is the ordered sort-key tuple of the last
    row on the current page — each element a `str`/`int`/`None`, or a
    `uuid.UUID` (stored as its canonical text). Anything else raises
    `TypeError` at the call site rather than producing an unusable cursor.
    """
    normalized: list[CursorValue] = []
    for value in values:
        if isinstance(value, uuid.UUID):
            normalized.append(str(value))
        elif isinstance(value, bool):
            raise TypeError("a bool is not a valid cursor sort key")
        elif isinstance(value, (str, int)) or value is None:
            normalized.append(value)
        else:
            raise TypeError(f"cursor value {value!r} is not a str, int, UUID, or None")
    raw = json.dumps([_CURSOR_VERSION, keyset, normalized], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(raw: str | None, *, keyset: str, arity: int) -> tuple[CursorValue, ...] | None:
    """Parse a cursor produced by `encode_cursor`, or `None` when no cursor
    was supplied (the first page).

    Raises `InvalidCursorError` (a fixed 422, non-disclosing) for anything
    that is not a well-formed cursor for this exact `keyset` with exactly
    `arity` key components: bad base64, bad JSON, wrong version, wrong
    keyset name, wrong component count, or a component that is not a JSON
    scalar. The error never echoes the offending value.
    """
    if raw is None or raw == "":
        return None
    if len(raw) > _MAX_CURSOR_BYTES:
        raise InvalidCursorError()

    padding = "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw + padding)
    except (binascii.Error, ValueError) as exc:
        raise InvalidCursorError() from exc

    try:
        parsed = json.loads(decoded)
    except (json.JSONDecodeError, ValueError) as exc:
        raise InvalidCursorError() from exc

    if (
        not isinstance(parsed, list)
        or len(parsed) != 3
        or parsed[0] != _CURSOR_VERSION
        or parsed[1] != keyset
        or not isinstance(parsed[2], list)
        or len(parsed[2]) != arity
    ):
        raise InvalidCursorError()

    values = parsed[2]
    for value in values:
        # `bool` is an `int` subclass — reject it explicitly so a cursor
        # can never smuggle a boolean where a scalar sort key is expected.
        if isinstance(value, bool) or not (isinstance(value, (str, int)) or value is None):
            raise InvalidCursorError()

    return tuple(values)


def build_page[Row](
    rows: Sequence[Row],
    *,
    limit: int,
    keyset: str,
    cursor_key: Callable[[Row], Sequence[object]],
) -> Page[Row]:
    """Trim an over-fetched result set to one page.

    The caller runs its query with `LIMIT limit + 1` under the page's
    deterministic `ORDER BY`; if `limit + 1` rows come back there is a next
    page, and its cursor is built from `cursor_key(last_kept_row)`.
    `cursor_key` must return the exact sort-key tuple, in order, that the
    query's own `ORDER BY` uses, so the emitted cursor reproduces that
    ordering on the following request.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    has_more = len(rows) > limit
    kept = list(rows[:limit])
    next_cursor: str | None = None
    if has_more and kept:
        next_cursor = encode_cursor(keyset, list(cursor_key(kept[-1])))
    return Page(items=kept, next_cursor=next_cursor)
