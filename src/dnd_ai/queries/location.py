"""Audience-filtered, keyset-paginated, searchable list of authorized
locations and dungeon areas — the backend for the portal's World Explorer
"browse authorized locations and dungeons" MVP slice (docs/UI_DESIGN.md
§5.4, docs/PHASE13D_WORLD_LOCATION_BROWSE.md).

Scope: `world.locations` is the class-table-inheritance root for every
spatial entity (docs/architecture/DATABASE_MODEL.md §9.1) — a settlement,
building, dungeon, dungeon area, or one of the bare-lookup leaf kinds
(plane, continent, nation, region, district, geographic_feature) are all
rows here, distinguished only by `core.entities.entity_type_id`. This
module lists that whole family in one query rather than one per subtype,
since every field this compact "card" view needs (name, type, summary,
parent) is already on `core.entities`/`world.locations` regardless of
subtype — the same reasoning that keeps `dnd_ai.queries.dungeon.
get_dungeon_area_view` a single query despite `world.dungeon_areas` being
only one of several location subtypes.

Audience filtering has three parts, all evaluated per row:

1. A per-location `campaign.view` resource-grant deny
   (`AccessContext.resource_grant_targets("campaign.view",
   field_name="entity_id")`, resolved by the caller) excludes that
   location outright, even for an otherwise campaign-view-authorized
   caller — the same `resource_grant_targets`-per-list pattern
   `dnd_ai.queries.session`/`.quest` already established for
   `session_id`/`quest_id`.
2. Publication/usability status (docs/ENTITY_LIFECYCLE.md §2.1/§2.2):
   `core.entities.lifecycle_status_id` must resolve to `active` and
   `archived_at` must be `NULL` — a `pending`, `inactive`, `archived`, or
   `deleted` record is excluded from this ordinary browse route
   regardless of who is asking. Archived/deleted records remain available
   to historical/audit/event-reference queries (§12 of that document);
   this endpoint is deliberately not one of them, per the task's own
   "archival/history browsing should remain separate from this ordinary
   World Explorer route." `lifecycle_status_id` and `archived_at` are two
   independent columns with no database `CHECK` tying them together
   (`database/migrations/versions/004_worlds_and_entities.py`), so both
   are checked rather than trusting either alone to imply the other.
3. Authoritativeness (docs/ENTITY_LIFECYCLE.md §2.1): a plain
   `campaign.view` caller sees only `canon_status_id = 'canon'` (published
   world truth). A caller canonical-truth-authorized for that specific
   location — baseline `canon.edit` not specifically denied it via a
   `canon.edit` resource grant, or one specifically granted `canon.edit`
   for it despite no baseline role — additionally sees any other canon
   status (`draft`, `proposed`, `approved`, `rejected`, `superseded`,
   `deprecated`) that already passed check 2 above, i.e. a GM authoring or
   reviewing world content sees their own in-progress definitions, never
   an archived/deleted one. This is a real, schema-backed authorization
   split — `core.entities.canon_status_id`/`canon.edit`, not the removed
   inference described below — resolved per row via the same deny/allow
   id sets `dnd_ai.queries.dungeon.get_dungeon_area_view`'s own
   `include_hidden` argument already uses for a single resource, mirrored
   here across a list via `resource_grant_targets`.

Corrected design note (this module has had two defects here, both fixed
before merge):

- An earlier version selected every `world.locations` row in the
  campaign's world with no regard for `canon_status_id`, `lifecycle_
  status_id`, or `archived_at` at all — meaning a plain `campaign.view`
  player could enumerate unpublished drafts (in fact, every location
  `tests.factories.make_entity()` creates defaults to `canon_status=
  'draft'`, so the endpoint's own tests were unintentionally proving this
  hole). Fixed by checks 2 and 3 above. `campaign.view` alone has never
  meant "every definition in this world is visible" — it is authorization
  to view the *campaign*, not proof that a given definition has been
  reviewed or published, and this endpoint must not conflate the two.
- A still-earlier version additionally treated the mere *existence* of a
  `knowledge.knowledge_items` row naming a location via `subject_entity_id`
  as proof that the location itself was hidden, gating it behind
  `knowledge.party_discoveries` unless the caller held `canon.edit`. That
  inference was unsound and has been removed, and is not reintroduced by
  the fix above: check 3's `canon.edit` split is keyed on the real
  `canon_status_id` column, never on knowledge-item existence or
  discovery state. A knowledge item is a claim *about* its subject —
  public lore, recorded history, an unconfirmed rumor, and a genuine
  secret are all represented identically as rows in that table — and a
  party's `knowledge.party_discoveries` row for one such claim proves only
  that the claim was learned, never that the subject location itself was
  ever hidden. `world.locations`/`world.dungeon_areas` carry no
  `is_hidden` (or any other authoritative discoverability) column of
  their own today (docs/architecture/DATABASE_MODEL.md §9.3 only
  documents `is_hidden` on a dungeon area's own structural children —
  features/hazards/interactables/connections — never on a location
  itself), so this endpoint does not attempt to reconstruct a substitute
  for one from an unrelated table. CLAUDE.md's own domain rules already
  forbid the shape that shortcut would have needed anyway ("Knowledge is
  per-knower, never a global boolean. No `is_player_known`/`is_discovered`
  flags on the object itself — discovery and belief live in the knowledge
  domain, scoped to who knows it") — `subject_entity_id` is a
  knowledge-claim-subject reference, not a per-object visibility flag.
  If product requirements come to need discovery-gated *locations*
  themselves (as opposed to a dungeon area's structural children, which
  already have a real, dedicated column for this), that is an explicit
  schema/design decision — a real visibility/discoverability column or
  table introduced through this repository's convention-change,
  documentation, migration, and test process (docs/DATABASE_CONVENTIONS.md
  §37) — not an ad hoc reuse of a column that already means something
  else. See docs/PHASE13D_WORLD_LOCATION_BROWSE.md §3/§9 for the tracked
  follow-up; this module and its endpoint do not implement one.

Parent disclosure: a location's `parent_location_id`/parent name are
included only when the *parent* independently passes the identical
per-row rule (deny, lifecycle/archival, and canon-status checks alike) —
an inaccessible, unpublished, or archived parent is never revealed
through this endpoint's own breadcrumb field, even for an
otherwise-visible child. Only one level of parent is resolved (no
ancestor chain, no graph-expansion API); the portal can request the
parent's own row directly (by `parent_location_id`, once visible) if it
wants to walk further up.

This module is framework-free and performs no authorization decisions of
its own: `denied_view_entity_ids`, `baseline_canon_edit`, and the two
`canon.edit`-targeted id sets must already be resolved/authorized
decisions by the time they reach here, exactly like every other query
module in this package.
"""

import base64
import binascii
import json
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

# Conservative defaults consistent with this codebase's existing fixed
# list-size precedent (dnd_ai.queries.summary._RECENT_EVENTS_LIMIT = 20,
# the one other list this package returns).
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class LocationListItemView:
    location_id: uuid.UUID
    name: str
    entity_type_code: str
    summary: str | None
    parent_location_id: uuid.UUID | None
    parent_name: str | None


@dataclass(frozen=True)
class LocationListPage:
    items: tuple[LocationListItemView, ...]
    next_cursor: str | None


def _escape_ilike_term(term: str) -> str:
    """Neutralizes `%`/`_`/`\\` in a caller-supplied search term so it is
    matched literally, not as an ILIKE wildcard — paired with `ESCAPE '\\'`
    in the query itself. This is about correctness (a search for a literal
    "%" or "_" behaving as the user expects), not injection safety, which
    bound parameters already provide regardless."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def encode_location_cursor(*, name_key: str, location_id: uuid.UUID) -> str:
    """An opaque keyset cursor over `(lower(canonical_name), location_id)` —
    this endpoint's own stable ordering (normalized display name, then UUID
    as a tie-breaker for identically-named locations). Callers must treat
    the returned string as opaque; only `decode_location_cursor` below
    parses it."""
    payload = json.dumps({"n": name_key, "id": str(location_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_location_cursor(cursor: str) -> tuple[str, uuid.UUID]:
    """The inverse of `encode_location_cursor`. Raises `ValueError` for any
    malformed cursor — a tampered, truncated, or hand-written string — which
    `dnd_ai.api.errors`' existing generic `ValueError` handler already maps
    to a fixed 400 `validation_failed` response, the same contract every
    other unclassified input-parsing failure in this codebase uses. Never
    raises anything more specific: a cursor is opaque by contract, so there
    is nothing safe to say about *why* it failed to parse."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw)
        name_key = payload["n"]
        location_id = uuid.UUID(payload["id"])
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError("malformed pagination cursor") from exc
    if not isinstance(name_key, str):
        raise ValueError("malformed pagination cursor")
    return name_key, location_id


# Shared by the main row's own visibility and its parent's — see this
# module's docstring for the full three-part rule. {entity_id_expr} is
# always an internal SQL literal supplied by list_campaign_locations below,
# never user-controlled. The publication/canon-status check is a
# correlated EXISTS against core.entities/core.lifecycle_statuses/core.
# canon_statuses rather than a direct join against an already-aliased row,
# so the identical template applies unchanged to both the main row
# (e.entity_id) and the parent row (pe.entity_id).
_VISIBLE_PREDICATE = """
    (
        NOT ({entity_id_expr} = ANY(CAST(:denied_view AS uuid[])))
        AND EXISTS (
            SELECT 1
            FROM core.entities pub
            JOIN core.lifecycle_statuses pub_ls
              ON pub_ls.lifecycle_status_id = pub.lifecycle_status_id
            JOIN core.canon_statuses pub_cs
              ON pub_cs.canon_status_id = pub.canon_status_id
            WHERE pub.entity_id = {entity_id_expr}
              AND pub_ls.code = 'active'
              AND pub.archived_at IS NULL
              AND (
                    pub_cs.code = 'canon'
                    OR (
                        (:baseline_canon_edit
                         AND NOT ({entity_id_expr} = ANY(CAST(:denied_canon_edit AS uuid[]))))
                        OR {entity_id_expr} = ANY(CAST(:allowed_canon_edit AS uuid[]))
                    )
              )
        )
    )
"""

_VALID_CODE = re.compile(r"^[a-z][a-z0-9_]*$")


def list_campaign_locations(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    denied_view_entity_ids: frozenset[uuid.UUID],
    baseline_canon_edit: bool,
    denied_canon_edit_entity_ids: frozenset[uuid.UUID],
    allowed_canon_edit_entity_ids: frozenset[uuid.UUID],
    entity_type_code: str | None,
    search_text: str | None,
    after: tuple[str, uuid.UUID] | None,
    limit: int,
) -> LocationListPage:
    """Every `world.locations` row in `world_id` visible to the caller (see
    this module's docstring for the full three-part rule — resource-grant
    deny, publication/lifecycle status, and canon-status), optionally
    filtered by `entity_type_code` and/or a case-insensitive `search_text`
    substring match against `canonical_name`/`summary`, ordered by
    `(lower(canonical_name), location_id)` ascending and keyset-paginated
    from `after` (the `(name_key, location_id)` pair decoded from a prior
    page's cursor, or `None` for the first page).

    `entity_type_code` is matched against `core.entity_types.code` exactly
    — an unrecognized code is not an error (entity-type codes are a fixed,
    non-sensitive vocabulary shared across the whole schema, not per-
    campaign data), it simply matches nothing. A code failing this
    module's own format check is rejected the same way, for the same
    reason: it cannot match any real `core.entity_types.code` value either,
    so there is no behavioral difference, only a cheaper query for an
    obviously-invalid filter.

    Returns up to `limit` items plus `next_cursor` (`None` once no further
    authorized rows remain) — never a total count, which computing at all
    would itself require examining rows this caller may not be authorized
    to know exist (docs/PHASE13D_WORLD_LOCATION_BROWSE.md's own
    non-disclosure rule).

    This function is framework-free and performs no authorization of its
    own — see this module's docstring for what every keyword argument here
    must already be by the time it reaches this function."""
    conditions = ["e.world_id = :world"]
    params: dict[str, object] = {
        "world": world_id,
        "denied_view": list(denied_view_entity_ids),
        "baseline_canon_edit": baseline_canon_edit,
        "denied_canon_edit": list(denied_canon_edit_entity_ids),
        "allowed_canon_edit": list(allowed_canon_edit_entity_ids),
    }

    if entity_type_code is not None and _VALID_CODE.match(entity_type_code):
        conditions.append("et.code = :type_code")
        params["type_code"] = entity_type_code
    elif entity_type_code is not None:
        # An invalid code can never match a real core.entity_types.code —
        # short-circuit to the same "matches nothing" outcome without
        # touching et.code in the query at all.
        conditions.append("FALSE")

    if search_text:
        conditions.append(
            "(e.canonical_name ILIKE :search ESCAPE '\\' OR e.summary ILIKE :search ESCAPE '\\')"
        )
        params["search"] = f"%{_escape_ilike_term(search_text)}%"

    conditions.append(_VISIBLE_PREDICATE.format(entity_id_expr="e.entity_id"))

    if after is not None:
        after_name_key, after_location_id = after
        conditions.append("(lower(e.canonical_name), e.entity_id) > (:after_name, :after_id)")
        params["after_name"] = after_name_key
        params["after_id"] = after_location_id

    where_clause = " AND ".join(conditions)
    # limit + 1: the standard keyset-pagination probe for "is there a next
    # page" without a separate COUNT query (which this endpoint must never
    # run anyway — see this module's own docstring on total counts).
    params["fetch_limit"] = limit + 1

    rows = (
        connection.execute(
            text(f"""
            SELECT e.entity_id AS location_id, e.canonical_name AS name, e.summary,
                   et.code AS entity_type_code,
                   wl.parent_location_id,
                   CASE WHEN pe.entity_id IS NOT NULL
                             AND {_VISIBLE_PREDICATE.format(entity_id_expr="pe.entity_id")}
                        THEN wl.parent_location_id END AS visible_parent_location_id,
                   CASE WHEN pe.entity_id IS NOT NULL
                             AND {_VISIBLE_PREDICATE.format(entity_id_expr="pe.entity_id")}
                        THEN pe.canonical_name END AS visible_parent_name
            FROM world.locations wl
            JOIN core.entities e ON e.entity_id = wl.location_id
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            LEFT JOIN core.entities pe ON pe.entity_id = wl.parent_location_id
            WHERE {where_clause}
            ORDER BY lower(e.canonical_name), e.entity_id
            LIMIT :fetch_limit
        """),
            params,
        )
        .mappings()
        .all()
    )

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items = tuple(
        LocationListItemView(
            location_id=row["location_id"],
            name=row["name"],
            entity_type_code=row["entity_type_code"],
            summary=row["summary"],
            parent_location_id=(
                row["parent_location_id"] if row["visible_parent_location_id"] is not None else None
            ),
            parent_name=row["visible_parent_name"],
        )
        for row in page_rows
    )

    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_location_cursor(
            name_key=last["name"].lower(), location_id=last["location_id"]
        )

    return LocationListPage(items=items, next_cursor=next_cursor)
