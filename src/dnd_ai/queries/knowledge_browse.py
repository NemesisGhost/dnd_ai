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

## GM vs perspective

A caller holding baseline `canon.edit` (a GM) with **no** perspective sees
*canonical* data — for `known`/`rumors` the world's own
`knowledge.knowledge_items` (with `truth_status`/`sensitivity`), for
`recent` every discovery on the timeline, for `public` the public-lore
rows — honoring any `knowledge_item_id`-targeted `canon.edit` deny.
`party_shared`/`character_private` still require the GM to supply an
authorized party/character perspective (a GM inspecting one party's or
character's beliefs), and return an empty page without one. A non-GM
caller always sees only their authorized party's / character's own belief
state, never the ground-truth `truth_status`/`sensitivity` metadata — the
identical split `get_knowledge_view` already applies.

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


@dataclass(frozen=True)
class KnowledgeListItem:
    knowledge_item_id: uuid.UUID
    knowledge_type_code: str
    statement: str
    """The viewer-safe claim: the party's / character's own recorded
    `interpretation` when one exists, else the canonical statement; the
    canonical statement for a GM canonical view."""
    truth_status_code: str | None
    """GM-only ground truth — `None` for a non-GM caller."""
    sensitivity: str | None
    """GM-only — `None` for a non-GM caller."""
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
    """The entity this knowledge is about, when it has one and the caller
    can see the knowledge at all — the related-resource link for the
    Knowledge screen. Independently re-filtered by the caller before it is
    followed."""
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
    limit: int,
    after_statement: str | None,
    after_time_sort: int | None,
    after_record_id: uuid.UUID | None,
) -> tuple[KnowledgeListItem, ...]:
    """Up to `limit + 1` visible knowledge records for `view`. Returns an
    empty tuple (never an error) when the view needs a perspective the
    caller does not have — an empty page is not an existence hint."""
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
    if include_ground_truth and authorized_party_id is None:
        return _list_canonical(connection, common, view=view)
    if authorized_party_id is None:
        return ()
    return _list_party(connection, common, view=view)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_STATEMENT_CURSOR_PREDICATE = """
    (
      NOT CAST(:has_cursor AS boolean)
      OR (lower(:__statement_expr__), :__id_expr__)
         > (lower(CAST(:after_statement AS text)), CAST(:after_record_id AS uuid))
    )
"""


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


def _row_to_item(r: object, *, scope: str, gm: bool) -> KnowledgeListItem:
    # `r` is a SQLAlchemy RowMapping; every _list_* query selects the full
    # column set (padding unused ones with typed NULLs), so a plain
    # subscript is always safe.
    row: dict[str, object] = dict(r)  # type: ignore[call-overload]
    statement = str(row["statement"])
    return KnowledgeListItem(
        knowledge_item_id=row["knowledge_item_id"],  # type: ignore[arg-type]
        knowledge_type_code=str(row["knowledge_type_code"]),
        statement=statement,
        truth_status_code=(str(row["truth_status_code"]) if gm else None),
        sensitivity=(str(row["sensitivity"]) if gm else None),
        awareness_level=_opt_str(row["awareness_level"]),
        confidence=_opt_int(row["confidence"]),
        willing_to_share=_opt_bool(row["willing_to_share"]),
        scope=scope,
        discovery_world_time_id=_opt_uuid(row["discovery_world_time_id"]),
        source_event_id=_opt_uuid(row["source_event_id"]),
        source_interaction_id=_opt_uuid(row["source_interaction_id"]),
        subject_entity_id=_opt_uuid(row["subject_entity_id"]),
        statement_sort=statement.lower(),
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
    sql = f"""
        SELECT ki.knowledge_item_id,
               ki.knowledge_item_id AS record_id,
               kt.code AS knowledge_type_code,
               {statement_expr} AS statement,
               ts.code AS truth_status_code, ki.sensitivity,
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
          AND {
        _STATEMENT_CURSOR_PREDICATE.replace(":__statement_expr__", statement_expr).replace(
            ":__id_expr__", "ki.knowledge_item_id"
        )
    }
        ORDER BY lower({statement_expr}), ki.knowledge_item_id
        LIMIT :limit_plus_one
    """
    rows = connection.execute(text(sql), params).mappings()
    return tuple(_row_to_item(r, scope="party", gm=False) for r in rows)


def _list_character_private(
    connection: Connection, params: dict[str, object]
) -> tuple[KnowledgeListItem, ...]:
    statement_expr = "COALESCE(ek.interpretation, ki.canonical_statement)"
    sql = f"""
        SELECT ki.knowledge_item_id,
               ek.entity_knowledge_id AS record_id,
               kt.code AS knowledge_type_code,
               {statement_expr} AS statement,
               ts.code AS truth_status_code, ki.sensitivity,
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
          AND {
        _STATEMENT_CURSOR_PREDICATE.replace(":__statement_expr__", statement_expr).replace(
            ":__id_expr__", "ek.entity_knowledge_id"
        )
    }
        ORDER BY lower({statement_expr}), ek.entity_knowledge_id
        LIMIT :limit_plus_one
    """
    rows = connection.execute(text(sql), params).mappings()
    return tuple(_row_to_item(r, scope="character", gm=False) for r in rows)


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
    sql = f"""
        SELECT ki.knowledge_item_id,
               ki.knowledge_item_id AS record_id,
               kt.code AS knowledge_type_code,
               {statement_expr} AS statement,
               ts.code AS truth_status_code, ki.sensitivity,
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
          {_statement_filters().replace(":__statement_expr__", statement_expr)}
          AND {
        _STATEMENT_CURSOR_PREDICATE.replace(":__statement_expr__", statement_expr).replace(
            ":__id_expr__", "ki.knowledge_item_id"
        )
    }
        ORDER BY lower({statement_expr}), ki.knowledge_item_id
        LIMIT :limit_plus_one
    """
    rows = connection.execute(text(sql), params).mappings()
    return tuple(_row_to_item(r, scope="canonical", gm=True) for r in rows)


def _list_public(
    connection: Connection, params: dict[str, object]
) -> tuple[KnowledgeListItem, ...]:
    statement_expr = "ki.canonical_statement"
    sql = f"""
        SELECT ki.knowledge_item_id,
               pub.public_knowledge_id AS record_id,
               kt.code AS knowledge_type_code,
               {statement_expr} AS statement,
               ts.code AS truth_status_code, ki.sensitivity,
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
          AND {
        _STATEMENT_CURSOR_PREDICATE.replace(":__statement_expr__", statement_expr).replace(
            ":__id_expr__", "pub.public_knowledge_id"
        )
    }
        ORDER BY lower({statement_expr}), pub.public_knowledge_id
        LIMIT :limit_plus_one
    """
    rows = connection.execute(text(sql), params).mappings()
    return tuple(_row_to_item(r, scope="public", gm=params["gm"] is True) for r in rows)


def _list_recent(
    connection: Connection, params: dict[str, object]
) -> tuple[KnowledgeListItem, ...]:
    """`knowledge.party_discoveries` newest-first by discovery world time.

    Audience: a GM (`gm` True) with no perspective sees every discovery on
    the timeline; otherwise the authorized party's discoveries
    (`party_id = :party_id`) and/or the authorized character's own
    (`knower_entity_id = :knower_id`). `NULL` discovery time sorts last.
    """
    gm = params["gm"] is True
    audience_clause = (
        "TRUE"
        if gm and params["party_id"] is None and params["knower_id"] is None
        else "(pd.party_id = :party_id OR pd.knower_entity_id = :knower_id)"
    )
    statement_expr = (
        "COALESCE(pk.interpretation, ki.canonical_statement)"
        if not gm
        else ("ki.canonical_statement")
    )
    sql = f"""
        SELECT ki.knowledge_item_id,
               pd.party_discovery_id AS record_id,
               kt.code AS knowledge_type_code,
               {statement_expr} AS statement,
               ts.code AS truth_status_code, ki.sensitivity,
               pk.awareness_level, pk.confidence, pk.willing_to_share,
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
        WHERE pd.timeline_id = :timeline_id
          AND e.world_id = :world_id
          AND {audience_clause}
          AND (CAST(:type_code AS text) IS NULL OR kt.code = CAST(:type_code AS text))
          AND NOT (ki.knowledge_item_id = ANY(CAST(:denied AS uuid[])))
          AND (
                CAST(:like_pattern AS text) IS NULL
                OR {statement_expr} ILIKE CAST(:like_pattern AS text) ESCAPE '\\'
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
    return tuple(_row_to_item(r, scope="canonical" if gm else "party", gm=gm) for r in rows)
