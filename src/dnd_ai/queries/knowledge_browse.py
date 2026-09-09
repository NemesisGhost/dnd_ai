"""Audience-filtered discovery/browse reads for the Phase 13D Knowledge
screen (docs/UI_DESIGN.md §5.6, docs/PHASE13D_BACKEND_READINESS.md §3/§9).

The existing `dnd_ai.queries.knowledge.get_knowledge_view` answers "show me
*this one* knowledge item" and the portal had no way to discover the ids to
call it with. This module answers "which knowledge items are visible to
this caller, in this campaign and authorized perspective" — the list side
of the screen — across the documented views.

## Views

| `view` | Source table | Audience |
|---|---|---|
| `known` | `campaign.party_knowledge` (authorized party), `knowledge_type` NOT in the rumor set | the party's settled knowledge |
| `rumors` | `campaign.party_knowledge` (authorized party), `knowledge_type` IN the rumor set | the party's unsettled beliefs |
| `party_shared` | `campaign.party_knowledge` (authorized party), every row | the party's collective knowledge |
| `character_private` | `knowledge.entity_knowledge` where `knower_entity_id` = the authorized character | that one character's individual beliefs |
| `recent` | `knowledge.party_discoveries` for the authorized party and/or character | the audience's discovery stream, newest first |
| `public` | `knowledge.public_knowledge` on the timeline | any `campaign.view` caller — no perspective needed |

The `known`/`rumors` split is grounded in the seeded
`knowledge.knowledge_types` vocabulary, not an invented flag:
`_RUMOR_TYPE_CODES` = rumor/belief/misconception/theory/prophecy;
everything else (fact/claim/secret/doctrine/instruction/memory) is
"settled". `party_shared` is the union of both.

**"Sources" is not a `view`.** The domain model has no standalone
provenance table — `learned_via_*`/`discovered_via_*` live on
`entity_knowledge`/`party_discoveries` themselves. So every list item
carries `source_event_id`/`source_interaction_id`/`discovery_world_time_id`
where the caller is authorized to see them, and the portal's "Sources" tab
is a client-side presentation over any view (most naturally `recent`),
exactly as docs/PHASE13D_BACKEND_READINESS.md §4 anticipates.

## Item visibility vs. ground-truth-field visibility (two decisions)

These are resolved independently (the Phase 13D Issue-4 correction):

- **Whether the caller may discover/list the item at all** is `campaign.
  view`. A `knowledge_item_id`-targeted `campaign.view` deny removes the
  item from every view (`denied_item_ids`) — and from the detail route,
  which 404s identically.
- **Whether the caller may see the item's *canonical / GM-only* fields**
  (`canonical_statement` where a view projects it, `truth_status`,
  `sensitivity`) is `canon.edit`, resolved **per item** by
  `_GROUND_TRUTH_EXPR`: baseline `canon.edit` OR a targeted `canon.edit`
  allow for that exact item, and never a targeted `canon.edit` deny. A
  `canon.edit` deny **only** nulls that item's ground-truth fields and,
  where a view would otherwise show the canonical statement, drops it back
  to the belief projection — it never removes an otherwise-visible item.
  A targeted `canon.edit` allow reveals only its own item.

So a baseline `canon.edit` caller with **no** perspective sees *canonical*
data for `known`/`rumors`/`recent`/`public` (minus any per-item `canon.
edit` deny); a non-GM with a targeted `canon.edit` allow sees canonical
data for exactly the allowed items; everyone else sees only their
authorized party's / character's own belief. `party_shared`/
`character_private` still require an authorized party/character perspective
and return an empty page without one. The `truth_status`/`sensitivity`
metadata is populated per row exactly when that per-item `canon.edit`
decision is true — the identical split `get_knowledge_view` applies for the
detail route.

## Ordering

`known`/`rumors`/`party_shared`/`character_private`/`public` order by
`(lower(statement), knowledge_item_id)`. `recent` orders by discovery
world-time (`core.world_times.sort_key`) **descending, NULLS LAST**, then
by an immutable `party_discovery_id` tie-breaker (Phase 13D §4's
"recently discovered" contract — an ordered stream, newest visible
discovery first, no arbitrary wall-clock window). Both are the exact
keysets the opaque `dnd_ai.api.pagination` cursor carries. No total count.

Framework-free, authorizes nothing itself: `include_ground_truth`,
`authorized_party_id`, `authorized_knower_id`, and `denied_item_ids` must
already be resolved decisions.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

KNOWN_KEYSET = "knowledge_by_statement"
RECENT_KEYSET = "knowledge_recent"

# The documented Knowledge-screen views this module serves. "sources" is
# deliberately absent — see the module docstring.
KNOWLEDGE_VIEWS: tuple[str, ...] = (
    "known",
    "rumors",
    "party_shared",
    "character_private",
    "recent",
    "public",
)

# `knowledge.knowledge_types.code` values that make an item a "rumor /
# belief" rather than "settled knowledge" — the seeded vocabulary
# (migration 041/074), not an invented flag.
_RUMOR_TYPE_CODES: tuple[str, ...] = ("rumor", "belief", "misconception", "theory", "prophecy")

_STATEMENT_ORDERED_VIEWS = frozenset(
    {"known", "rumors", "party_shared", "character_private", "public"}
)

# A `canonical_statement` is up to 5000 characters (migration 041's
# `ck_knowledge_items_statement_length`), and an `interpretation` is
# unbounded text; carrying a whole statement in the opaque
# `dnd_ai.api.pagination` cursor would blow past that module's size bound
# (the review's Medium finding — a valid 2000-char statement produced a
# `next_cursor` the decoder then rejected). The statement-ordered views
# therefore sort by, and carry in the cursor, only a bounded lower-cased
# *prefix* of the viewer-safe statement. `(prefix, record_id)` is still a
# strict total order — `record_id` is unique per row — so keyset paging
# over it never skips or repeats a row; rows sharing a 200-char prefix are
# simply ordered by their stable id. The prefix is computed in SQL
# (`lower(left(expr, N))`) and echoed back verbatim, so the value compared
# on the next request is exactly the value the previous page emitted (no
# Python-vs-Postgres `lower()` drift).
_STATEMENT_SORT_PREFIX = 200


def _sort_key_expr(statement_expr: str) -> str:
    """The bounded, case-folded ordering key for a statement-ordered view —
    see `_STATEMENT_SORT_PREFIX`. Used identically in `SELECT`, `ORDER BY`,
    and the keyset predicate so all three agree."""
    return f"lower(left({statement_expr}, {_STATEMENT_SORT_PREFIX}))"


# Whether *this caller* may see the item's canonical / GM-only fields — its
# `canonical_statement` where a view projects it, `truth_status`, and
# `sensitivity`. Baseline `canon.edit` (`:gm`) OR a targeted `canon.edit`
# allow for this exact item, and never a targeted `canon.edit` deny: the
# same deny-overrides-allow-overrides-baseline precedence
# `dnd_ai.domain.access.AccessContext.has_capability` resolves for one item.
#
# This is deliberately *separate* from item visibility. Whether the caller
# may discover/list the item at all is `campaign.view` (a targeted deny
# there removes it, applied via `:denied`). A targeted `canon.edit` deny
# only strips these ground-truth fields — it never removes an
# otherwise-visible item, so a player whose party has a belief about an
# item still sees that belief even when a `canon.edit` deny targets the
# item.
_GROUND_TRUTH_EXPR = (
    "((CAST(:gm AS boolean) OR ki.knowledge_item_id = ANY(CAST(:gt_allowed AS uuid[]))) "
    "AND NOT (ki.knowledge_item_id = ANY(CAST(:gt_denied AS uuid[]))))"
)


@dataclass(frozen=True)
class KnowledgeListItem:
    knowledge_item_id: uuid.UUID
    knowledge_type_code: str
    statement: str
    """The viewer-safe claim: the party's / character's own recorded
    `interpretation` when one exists, else the canonical statement; the
    canonical statement for a GM canonical view."""
    truth_status_code: str | None
    """The item's ground-truth status — populated only when the caller may
    see canonical/GM-only fields for *this item* (baseline `canon.edit`, or
    a targeted `canon.edit` allow, and no targeted `canon.edit` deny);
    `None` otherwise. A `canon.edit` deny nulls this without hiding the
    item."""
    sensitivity: str | None
    """The item's ground-truth sensitivity — same gating as
    `truth_status_code`; `None` when the caller may not see it."""
    awareness_level: str | None
    confidence: int | None
    willing_to_share: bool | None
    scope: str
    """Which authorization path surfaced this row: `party` / `character` /
    `public` / `canonical`."""
    discovery_world_time_id: uuid.UUID | None
    source_event_id: uuid.UUID | None
    source_interaction_id: uuid.UUID | None
    subject_entity_id: uuid.UUID | None
    """The entity this knowledge is about (its raw `knowledge_items.
    subject_entity_id`), or `None`. The API layer additionally **redacts**
    this to `None` unless the caller can independently discover that entity
    (Issue 1 — `dnd_ai.api.knowledge._resolve_related_id_redaction`); the
    same applies to `source_event_id`/`source_interaction_id`. This module
    itself only scopes by timeline/world/party — the cross-resource
    discoverability check belongs at the API boundary that has the caller's
    full `AccessContext`."""
    # --- cursor keying (not part of the public response) --------------
    statement_sort: str
    time_sort: int | None
    record_id: uuid.UUID


def list_knowledge(
    connection: Connection,
    *,
    view: str,
    timeline_id: uuid.UUID,
    world_id: uuid.UUID,
    include_ground_truth: bool,
    authorized_party_id: uuid.UUID | None,
    authorized_knower_id: uuid.UUID | None,
    query_text: str | None,
    knowledge_type_code: str | None,
    denied_item_ids: frozenset[uuid.UUID],
    ground_truth_allowed_item_ids: frozenset[uuid.UUID] = frozenset(),
    ground_truth_denied_item_ids: frozenset[uuid.UUID] = frozenset(),
    limit: int,
    after_statement: str | None,
    after_time_sort: int | None,
    after_record_id: uuid.UUID | None,
) -> tuple[KnowledgeListItem, ...]:
    """Up to `limit + 1` visible knowledge records for `view`. Returns an
    empty tuple (never an error) when the view needs a perspective the
    caller does not have — an empty page is not an existence hint.

    Item *visibility* and *ground-truth-field* visibility are two
    independent decisions (Issue 4 of the Phase 13D corrections). `denied_
    item_ids` are the items a targeted `campaign.view` deny removes
    entirely. `include_ground_truth` is the caller's *baseline* `canon.edit`
    standing; `ground_truth_allowed_item_ids` / `ground_truth_denied_item_
    ids` are the per-item `canon.edit` allow / deny targets layered on top
    (`_GROUND_TRUTH_EXPR` composes them the same way `has_capability` does).
    A `canon.edit` deny never removes an item — it only nulls that item's
    `truth_status`/`sensitivity` and, where a view would otherwise project
    the canonical statement, drops it back to the belief projection."""
    if view not in KNOWLEDGE_VIEWS:
        raise ValueError(f"unknown knowledge view {view!r}")

    like_pattern = f"%{_escape_like(query_text)}%" if query_text else None
    common: dict[str, object] = {
        "timeline_id": timeline_id,
        "world_id": world_id,
        "party_id": authorized_party_id,
        "knower_id": authorized_knower_id,
        "like_pattern": like_pattern,
        "type_code": knowledge_type_code,
        "rumor_codes": list(_RUMOR_TYPE_CODES),
        "denied": list(denied_item_ids),
        "limit_plus_one": limit + 1,
        "gm": include_ground_truth,
        "gt_allowed": list(ground_truth_allowed_item_ids),
        "gt_denied": list(ground_truth_denied_item_ids),
    }

    if view == "recent":
        common.update(
            {
                "after_time_sort": after_time_sort,
                "after_record_id": after_record_id,
                "has_cursor": after_record_id is not None,
            }
        )
        return _list_recent(connection, common)

    common.update(
        {
            "after_statement": after_statement,
            "after_record_id": after_record_id,
            "has_cursor": after_record_id is not None,
        }
    )
    if view == "public":
        return _list_public(connection, common)
    if view == "character_private":
        if authorized_knower_id is None:
            return ()
        return _list_character_private(connection, common)
    # known / rumors / party_shared
    if authorized_party_id is None:
        # The canonical (ground-truth) projection — reachable for a baseline
        # GM, or for a non-GM who holds a targeted `canon.edit` allow for at
        # least one item (`_list_canonical` itself filters to exactly the
        # items this caller may see ground truth for, so a targeted deny is
        # honored and a targeted allow reveals only its own item — never
        # campaign-wide authority). A caller with neither gets an empty page.
        if not include_ground_truth and not ground_truth_allowed_item_ids:
            return ()
        return _list_canonical(connection, common, view=view)
    return _list_party(connection, common, view=view)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_STATEMENT_CURSOR_PREDICATE = """
    (
      NOT CAST(:has_cursor AS boolean)
      OR (:__sort_expr__, :__id_expr__)
         > (CAST(:after_statement AS text), CAST(:after_record_id AS uuid))
    )
"""


def _cursor_predicate(statement_expr: str, id_expr: str) -> str:
    """The keyset `WHERE` clause for a statement-ordered view, bound to
    that view's viewer-safe statement expression and unique record id."""
    return _STATEMENT_CURSOR_PREDICATE.replace(
        ":__sort_expr__", _sort_key_expr(statement_expr)
    ).replace(":__id_expr__", id_expr)


def _statement_filters() -> str:
    """The shared `q` + type-code filters for the statement-ordered views.
    `:__statement_expr__` is substituted by each caller."""
    return """
        AND (
              CAST(:like_pattern AS text) IS NULL
              OR :__statement_expr__ ILIKE CAST(:like_pattern AS text) ESCAPE '\\'
            )
        AND (CAST(:type_code AS text) IS NULL OR kt.code = CAST(:type_code AS text))
        AND NOT (ki.knowledge_item_id = ANY(CAST(:denied AS uuid[])))
    """


def _row_to_item(r: object, *, scope: str) -> KnowledgeListItem:
    # `r` is a SQLAlchemy RowMapping; every _list_* query selects the full
    # column set (padding unused ones with typed NULLs), so a plain
    # subscript is always safe.
    row: dict[str, object] = dict(r)  # type: ignore[call-overload]
    statement = str(row["statement"])
    # Statement-ordered views select the bounded sort key (`_sort_key_expr`)
    # as `statement_sort`; `recent` orders by time and does not, so fall
    # back to the same bounded, case-folded prefix rather than the whole
    # statement (which `recent` never puts in its cursor anyway).
    raw_sort = row.get("statement_sort")
    statement_sort = (
        str(raw_sort) if raw_sort is not None else statement.lower()[:_STATEMENT_SORT_PREFIX]
    )
    # `caller_sees_ground_truth` (`_GROUND_TRUTH_EXPR`) is selected by every
    # `_list_*` query — a per-item decision, not one global `gm` flag, so a
    # targeted `canon.edit` deny nulls exactly this item's ground-truth
    # fields while leaving the rest of the page (and the item itself) alone.
    sees_ground_truth = bool(row["caller_sees_ground_truth"])
    return KnowledgeListItem(
        knowledge_item_id=row["knowledge_item_id"],  # type: ignore[arg-type]
        knowledge_type_code=str(row["knowledge_type_code"]),
        statement=statement,
        truth_status_code=(str(row["truth_status_code"]) if sees_ground_truth else None),
        sensitivity=(str(row["sensitivity"]) if sees_ground_truth else None),
        awareness_level=_opt_str(row["awareness_level"]),
        confidence=_opt_int(row["confidence"]),
        willing_to_share=_opt_bool(row["willing_to_share"]),
        scope=scope,
        discovery_world_time_id=_opt_uuid(row["discovery_world_time_id"]),
        source_event_id=_opt_uuid(row["source_event_id"]),
        source_interaction_id=_opt_uuid(row["source_interaction_id"]),
        subject_entity_id=_opt_uuid(row["subject_entity_id"]),
        statement_sort=statement_sort,
        time_sort=_opt_int(row["time_sort"]),
        record_id=row["record_id"],  # type: ignore[arg-type]
    )


def _opt_str(v: object) -> str | None:
    return str(v) if v is not None else None


def _opt_int(v: object) -> int | None:
    return int(v) if v is not None else None  # type: ignore[call-overload]


def _opt_bool(v: object) -> bool | None:
    return bool(v) if v is not None else None


def _opt_uuid(v: object) -> uuid.UUID | None:
    return v if isinstance(v, uuid.UUID) else None


def _list_party(
    connection: Connection, params: dict[str, object], *, view: str
) -> tuple[KnowledgeListItem, ...]:
    if view == "known":
        type_clause = "AND NOT (kt.code = ANY(CAST(:rumor_codes AS text[])))"
    elif view == "rumors":
        type_clause = "AND kt.code = ANY(CAST(:rumor_codes AS text[]))"
    else:  # party_shared
        type_clause = ""
    statement_expr = "COALESCE(pk.interpretation, ki.canonical_statement)"
    sort_key = _sort_key_expr(statement_expr)
    sql = f"""
        SELECT ki.knowledge_item_id,
               ki.knowledge_item_id AS record_id,
               kt.code AS knowledge_type_code,
               {statement_expr} AS statement,
               {sort_key} AS statement_sort,
               ts.code AS truth_status_code, ki.sensitivity,
               {_GROUND_TRUTH_EXPR} AS caller_sees_ground_truth,
               pk.awareness_level, pk.confidence, pk.willing_to_share,
               NULL::uuid AS discovery_world_time_id,
               pk.last_event_id AS source_event_id,
               NULL::uuid AS source_interaction_id,
               ki.subject_entity_id,
               NULL::bigint AS time_sort
        FROM campaign.party_knowledge pk
        JOIN knowledge.knowledge_items ki ON ki.knowledge_item_id = pk.knowledge_item_id
        JOIN core.entities e ON e.entity_id = ki.knowledge_item_id
        JOIN knowledge.knowledge_types kt ON kt.knowledge_type_id = ki.knowledge_type_id
        JOIN knowledge.truth_statuses ts ON ts.truth_status_id = ki.truth_status_id
        WHERE pk.timeline_id = :timeline_id
          AND pk.party_id = :party_id
          AND e.world_id = :world_id
          {type_clause}
          {_statement_filters().replace(":__statement_expr__", statement_expr)}
          AND {_cursor_predicate(statement_expr, "ki.knowledge_item_id")}
        ORDER BY {sort_key}, ki.knowledge_item_id
        LIMIT :limit_plus_one
    """
    rows = connection.execute(text(sql), params).mappings()
    return tuple(_row_to_item(r, scope="party") for r in rows)


def _list_character_private(
    connection: Connection, params: dict[str, object]
) -> tuple[KnowledgeListItem, ...]:
    statement_expr = "COALESCE(ek.interpretation, ki.canonical_statement)"
    sort_key = _sort_key_expr(statement_expr)
    sql = f"""
        SELECT ki.knowledge_item_id,
               ek.entity_knowledge_id AS record_id,
               kt.code AS knowledge_type_code,
               {statement_expr} AS statement,
               {sort_key} AS statement_sort,
               ts.code AS truth_status_code, ki.sensitivity,
               {_GROUND_TRUTH_EXPR} AS caller_sees_ground_truth,
               ek.awareness_level, ek.confidence, ek.willing_to_share,
               wt.world_time_id AS discovery_world_time_id,
               ek.learned_via_event_id AS source_event_id,
               ek.learned_via_interaction_id AS source_interaction_id,
               ki.subject_entity_id,
               NULL::bigint AS time_sort
        FROM knowledge.entity_knowledge ek
        JOIN knowledge.knowledge_items ki ON ki.knowledge_item_id = ek.knowledge_item_id
        JOIN core.entities e ON e.entity_id = ki.knowledge_item_id
        JOIN knowledge.knowledge_types kt ON kt.knowledge_type_id = ki.knowledge_type_id
        JOIN knowledge.truth_statuses ts ON ts.truth_status_id = ki.truth_status_id
        LEFT JOIN core.world_times wt ON wt.world_time_id = ek.learned_at_world_time_id
        WHERE ek.timeline_id = :timeline_id
          AND ek.knower_entity_id = :knower_id
          AND e.world_id = :world_id
          {_statement_filters().replace(":__statement_expr__", statement_expr)}
          AND {_cursor_predicate(statement_expr, "ek.entity_knowledge_id")}
        ORDER BY {sort_key}, ek.entity_knowledge_id
        LIMIT :limit_plus_one
    """
    rows = connection.execute(text(sql), params).mappings()
    return tuple(_row_to_item(r, scope="character") for r in rows)


def _list_canonical(
    connection: Connection, params: dict[str, object], *, view: str
) -> tuple[KnowledgeListItem, ...]:
    if view == "known":
        type_clause = "AND NOT (kt.code = ANY(CAST(:rumor_codes AS text[])))"
    elif view == "rumors":
        type_clause = "AND kt.code = ANY(CAST(:rumor_codes AS text[]))"
    else:
        type_clause = ""
    statement_expr = "ki.canonical_statement"
    sort_key = _sort_key_expr(statement_expr)
    sql = f"""
        SELECT ki.knowledge_item_id,
               ki.knowledge_item_id AS record_id,
               kt.code AS knowledge_type_code,
               {statement_expr} AS statement,
               {sort_key} AS statement_sort,
               ts.code AS truth_status_code, ki.sensitivity,
               {_GROUND_TRUTH_EXPR} AS caller_sees_ground_truth,
               NULL::text AS awareness_level, NULL::smallint AS confidence,
               NULL::boolean AS willing_to_share,
               NULL::uuid AS discovery_world_time_id,
               NULL::uuid AS source_event_id, NULL::uuid AS source_interaction_id,
               ki.subject_entity_id,
               NULL::bigint AS time_sort
        FROM knowledge.knowledge_items ki
        JOIN core.entities e ON e.entity_id = ki.knowledge_item_id
        JOIN knowledge.knowledge_types kt ON kt.knowledge_type_id = ki.knowledge_type_id
        JOIN knowledge.truth_statuses ts ON ts.truth_status_id = ki.truth_status_id
        WHERE e.world_id = :world_id
          {type_clause}
          -- The canonical view returns *only* items this caller may see
          -- ground truth for: a targeted `canon.edit` deny drops the item
          -- from here (it may still surface through a belief view), and a
          -- non-GM's targeted `canon.edit` allow reveals exactly its own
          -- item and no other.
          AND {_GROUND_TRUTH_EXPR}
          {_statement_filters().replace(":__statement_expr__", statement_expr)}
          AND {_cursor_predicate(statement_expr, "ki.knowledge_item_id")}
        ORDER BY {sort_key}, ki.knowledge_item_id
        LIMIT :limit_plus_one
    """
    rows = connection.execute(text(sql), params).mappings()
    return tuple(_row_to_item(r, scope="canonical") for r in rows)


def _list_public(
    connection: Connection, params: dict[str, object]
) -> tuple[KnowledgeListItem, ...]:
    statement_expr = "ki.canonical_statement"
    sort_key = _sort_key_expr(statement_expr)
    sql = f"""
        SELECT ki.knowledge_item_id,
               pub.public_knowledge_id AS record_id,
               kt.code AS knowledge_type_code,
               {statement_expr} AS statement,
               {sort_key} AS statement_sort,
               ts.code AS truth_status_code, ki.sensitivity,
               {_GROUND_TRUTH_EXPR} AS caller_sees_ground_truth,
               pub.awareness_level, NULL::smallint AS confidence,
               NULL::boolean AS willing_to_share,
               pub.known_since_world_time_id AS discovery_world_time_id,
               NULL::uuid AS source_event_id, NULL::uuid AS source_interaction_id,
               ki.subject_entity_id,
               NULL::bigint AS time_sort
        FROM knowledge.public_knowledge pub
        JOIN knowledge.knowledge_items ki ON ki.knowledge_item_id = pub.knowledge_item_id
        JOIN core.entities e ON e.entity_id = ki.knowledge_item_id
        JOIN knowledge.knowledge_types kt ON kt.knowledge_type_id = ki.knowledge_type_id
        JOIN knowledge.truth_statuses ts ON ts.truth_status_id = ki.truth_status_id
        WHERE pub.timeline_id = :timeline_id
          AND e.world_id = :world_id
          {_statement_filters().replace(":__statement_expr__", statement_expr)}
          AND {_cursor_predicate(statement_expr, "pub.public_knowledge_id")}
        ORDER BY {sort_key}, pub.public_knowledge_id
        LIMIT :limit_plus_one
    """
    rows = connection.execute(text(sql), params).mappings()
    return tuple(_row_to_item(r, scope="public") for r in rows)


def _owned_belief(party_col: str, character_col: str, *, canonical: bool = False) -> str:
    """A SQL `CASE` that reads `party_col` for a party-owned discovery
    (`pd.party_id IS NOT NULL`) and `character_col` for a character-owned
    one — the single split every `_list_recent` non-GM column uses so a
    card's statement, scope, and belief metadata all come from the same
    belief and stay consistent. With `canonical=True` each branch falls
    back to `ki.canonical_statement` when that belief records no value
    (a statement column); without it a `NULL` from the owning belief is
    preserved as `NULL` (a metadata column)."""
    party = f"COALESCE({party_col}, ki.canonical_statement)" if canonical else party_col
    character = f"COALESCE({character_col}, ki.canonical_statement)" if canonical else character_col
    return f"CASE WHEN pd.party_id IS NOT NULL THEN {party} ELSE {character} END"


def _list_recent(
    connection: Connection, params: dict[str, object]
) -> tuple[KnowledgeListItem, ...]:
    """`knowledge.party_discoveries` newest-first by discovery world time.

    **Audience** (which discoveries are in scope): a caller with baseline
    `canon.edit` and *no* perspective sees every discovery on the timeline;
    everyone else — including a GM who selected a perspective, and a non-GM
    with a targeted `canon.edit` allow — sees only the discoveries their
    authorized party (`pd.party_id = :party_id`) or character
    (`pd.knower_entity_id = :knower_id`) made. A targeted `canon.edit`
    allow grants ground truth *for an item*, never a wider view of who
    discovered what.

    **Projection** (per row, `_GROUND_TRUTH_EXPR`): where this caller may
    see the item's ground truth, the row shows the canonical statement
    (`scope` `canonical`, no belief metadata) with `truth_status`/
    `sensitivity` — identical to `_list_canonical`. Where they may not
    (no `canon.edit` standing for it, or a targeted `canon.edit` deny),
    *every* viewer-facing column — `statement`, `scope`, `awareness_level`,
    `confidence`, `willing_to_share` — is resolved through the **discovery
    owner's own** belief (`_owned_belief`), falling back to
    `ki.canonical_statement` only when that belief records no
    interpretation of its own, and the row is shown only if that belief
    row exists at all (so `recent` never discloses a canonical statement a
    `canon.edit` deny or a missing belief should have replaced, and never
    lists an item the matching detail route would 404 on). The `q`
    substring match runs against that same effective statement expression.
    `NULL` discovery time sorts last; `pd.party_discovery_id` is the stable
    tie-breaker.
    """
    gm_baseline = params["gm"] is True
    no_perspective = params["party_id"] is None and params["knower_id"] is None
    audience_clause = (
        "TRUE"
        if (gm_baseline and no_perspective)
        else "(pd.party_id = :party_id OR pd.knower_entity_id = :knower_id)"
    )

    gt = _GROUND_TRUTH_EXPR
    owner_statement = _owned_belief("pk.interpretation", "ek.interpretation", canonical=True)
    statement_expr = f"CASE WHEN {gt} THEN ki.canonical_statement ELSE {owner_statement} END"
    scope_expr = (
        f"CASE WHEN {gt} THEN 'canonical' "
        "WHEN pd.party_id IS NOT NULL THEN 'party' ELSE 'character' END"
    )
    awareness_expr = (
        f"CASE WHEN {gt} THEN NULL::text "
        f"ELSE {_owned_belief('pk.awareness_level', 'ek.awareness_level')} END"
    )
    confidence_expr = (
        f"CASE WHEN {gt} THEN NULL::smallint "
        f"ELSE {_owned_belief('pk.confidence', 'ek.confidence')} END"
    )
    share_expr = (
        f"CASE WHEN {gt} THEN NULL::boolean "
        f"ELSE {_owned_belief('pk.willing_to_share', 'ek.willing_to_share')} END"
    )
    # A row is kept when the caller may see the item's ground truth, or when
    # the discovery owner's own belief row exists. A `canon.edit` deny flips
    # a row from the first case to needing the second — so a denied item
    # with no belief simply drops out (non-disclosing), exactly as it would
    # from `_list_canonical`.
    belief_clause = (
        f"AND ({gt} "
        "OR (pd.party_id IS NOT NULL AND pk.party_knowledge_id IS NOT NULL) "
        "OR (pd.knower_entity_id IS NOT NULL AND ek.entity_knowledge_id IS NOT NULL))"
    )

    sql = f"""
        SELECT ki.knowledge_item_id,
               pd.party_discovery_id AS record_id,
               kt.code AS knowledge_type_code,
               {statement_expr} AS statement,
               ts.code AS truth_status_code, ki.sensitivity,
               {gt} AS caller_sees_ground_truth,
               {awareness_expr} AS awareness_level,
               {confidence_expr} AS confidence,
               {share_expr} AS willing_to_share,
               {scope_expr} AS scope,
               pd.discovered_at_world_time_id AS discovery_world_time_id,
               pd.discovered_via_event_id AS source_event_id,
               pd.discovered_via_interaction_id AS source_interaction_id,
               ki.subject_entity_id,
               wt.sort_key AS time_sort
        FROM knowledge.party_discoveries pd
        JOIN knowledge.knowledge_items ki ON ki.knowledge_item_id = pd.knowledge_item_id
        JOIN core.entities e ON e.entity_id = ki.knowledge_item_id
        JOIN knowledge.knowledge_types kt ON kt.knowledge_type_id = ki.knowledge_type_id
        JOIN knowledge.truth_statuses ts ON ts.truth_status_id = ki.truth_status_id
        LEFT JOIN core.world_times wt ON wt.world_time_id = pd.discovered_at_world_time_id
        LEFT JOIN campaign.party_knowledge pk
               ON pk.timeline_id = pd.timeline_id
              AND pk.knowledge_item_id = pd.knowledge_item_id
              AND pk.party_id = :party_id
        LEFT JOIN knowledge.entity_knowledge ek
               ON ek.timeline_id = pd.timeline_id
              AND ek.knowledge_item_id = pd.knowledge_item_id
              AND ek.knower_entity_id = :knower_id
        WHERE pd.timeline_id = :timeline_id
          AND e.world_id = :world_id
          AND {audience_clause}
          {belief_clause}
          AND (CAST(:type_code AS text) IS NULL OR kt.code = CAST(:type_code AS text))
          AND NOT (ki.knowledge_item_id = ANY(CAST(:denied AS uuid[])))
          AND (
                CAST(:like_pattern AS text) IS NULL
                OR ({statement_expr}) ILIKE CAST(:like_pattern AS text) ESCAPE '\\'
              )
          AND (
            NOT CAST(:has_cursor AS boolean)
            OR (
              (CAST(:after_time_sort AS bigint) IS NOT NULL AND (
                 wt.sort_key < CAST(:after_time_sort AS bigint)
                 OR wt.sort_key IS NULL
                 OR (wt.sort_key = CAST(:after_time_sort AS bigint)
                     AND pd.party_discovery_id > CAST(:after_record_id AS uuid))
              ))
              OR (CAST(:after_time_sort AS bigint) IS NULL
                  AND wt.sort_key IS NULL
                  AND pd.party_discovery_id > CAST(:after_record_id AS uuid))
            )
          )
        ORDER BY wt.sort_key DESC NULLS LAST, pd.party_discovery_id
        LIMIT :limit_plus_one
    """
    rows = connection.execute(text(sql), params).mappings()
    return tuple(_row_to_item(r, scope=str(r["scope"])) for r in rows)
