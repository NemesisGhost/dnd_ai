# Phase 13D World Explorer: location/dungeon browse

Backend-only implementation of the first bounded World Explorer read slice
(docs/UI_DESIGN.md §5.4 "Browse authorized: locations and dungeons..."):
an authenticated, authorized, type-filtered, searchable, keyset-paginated
list of locations and dungeon areas, sized to let the portal display and
search compact result cards and navigate to the existing dungeon-area
detail route. `portal/` was not opened or modified — this is entirely a
`src/dnd_ai` change, continuing the audit/remediation practice
`docs/PHASE13D_BACKEND_READINESS.md` established for the Sessions/Quests
read side.

## 1. Route and response contract

`GET /campaigns/{campaign_id}/locations`

Query parameters (all optional):

| Parameter | Type | Meaning |
|---|---|---|
| `entity_type` | `str` | `core.entity_types.code` to filter to (`settlement`, `building`, `dungeon`, `dungeon_area`, `plane`, `continent`, `nation`, `region`, `district`, `geographic_feature`). An unrecognized code matches nothing — not an error, since entity-type codes are a fixed, non-sensitive vocabulary. |
| `q` | `str` | Case-insensitive substring match against `canonical_name` and `summary` (PostgreSQL `ILIKE`, with `%`/`_`/`\` escaped so a literal search term behaves as the user expects). |
| `character_id`, `party_id` | `UUID` | The requested viewing perspective — see §3. |
| `cursor` | `str` | Opaque keyset-pagination cursor from a previous page's `next_cursor`. |
| `limit` | `int` | Page size, `1`–`100`, default `20`. |

Response (`LocationListResponse`):

```jsonc
{
  "items": [
    {
      "location_id": "uuid",
      "name": "Rivertown",
      "entity_type_code": "settlement",
      "summary": "A bustling market town." ,  // or null
      "parent_location_id": "uuid or null",
      "parent_name": "string or null"
    }
  ],
  "next_cursor": "opaque string or null"
}
```

No total-result-count field exists anywhere in the contract — see §2.

Backing modules: `dnd_ai.queries.location` (new; `list_campaign_locations`,
`encode_location_cursor`/`decode_location_cursor`) and `dnd_ai.api.
locations` (new; `list_locations_endpoint`), registered in `dnd_ai.api.
app`. The existing single-item dungeon-area detail route (`dnd_ai.api.
dungeon`, `GET /campaigns/{campaign_id}/dungeon-areas/{dungeon_area_id}`)
is unchanged and is the route the portal calls next for a `dungeon_area`-
typed result — see §6 for why no equivalent detail route exists yet for
other location subtypes.

## 2. Pagination and cursor semantics

- **Ordering:** `(lower(canonical_name), location_id)` ascending — a
  normalized (lowercased) display name, with the UUID itself as a
  deterministic tie-breaker for identically-named locations. This is a
  total order (no two rows can tie on both fields), so keyset pagination
  over it never skips or repeats a row regardless of how many locations
  share a name.
- **Cursor:** base64url-encoded JSON (`{"n": <lower_name>, "id": <uuid>}`)
  of the last row's own ordering key — opaque by contract; the client
  never constructs or inspects one, only round-trips the value the
  previous response returned. The next page's query adds `(lower(name),
  location_id) > (cursor.n, cursor.id)` via a PostgreSQL row-constructor
  comparison.
- **Page size:** default `20`, maximum `100` — the same order of magnitude
  as this codebase's one other fixed list size (`dnd_ai.queries.summary.
  _RECENT_EVENTS_LIMIT = 20`). Out-of-range `limit` is a plain domain
  `ValueError`.
- **`next_cursor`:** computed by fetching `limit + 1` authorized rows and
  trimming the last one back off if present — never a second `COUNT(*)`
  query. `None` once no further authorized rows exist.
- **No total count, ever.** Computing one would require evaluating the
  full three-layer visibility rule (§3) over every matching row regardless
  of page size, which is itself the exact kind of "how many hidden things
  exist" signal `docs/PLAN.md`'s "cannot be inferred through counts" rule
  forbids. `LocationListResponse` has no count field, and
  `list_campaign_locations` never runs a counting query internally either.
- **Malformed cursor:** `decode_location_cursor` raises a bare `ValueError`
  for anything that fails to base64-decode, JSON-parse, or produce a valid
  UUID — left to propagate to the existing generic `ValueError` handler
  (`dnd_ai.api.errors`), which maps it to a fixed `400 validation_failed`
  response. No new error type or handler was added.
- **No generalized pagination framework.** The cursor encode/decode
  functions and the keyset `WHERE`/`ORDER BY` shape live entirely in
  `dnd_ai.queries.location`, specific to this one endpoint's `(name, id)`
  ordering — nothing here is reusable scaffolding for a future paginated
  endpoint to inherit from, matching the task's explicit "do not create a
  generalized pagination framework for the repository" instruction.

## 3. Authorization and discovery behavior

Reuses the existing unified boundary throughout — no second
implementation:

- **Authentication:** `dnd_ai.api.auth.get_authenticated_user_id`
  (browser-session cookie or bearer token), the same dependency every
  other route in this codebase resolves through.
- **Campaign access:** `dnd_ai.api.access.require_campaign_capability
  ("campaign.view")`, re-resolved fresh (`dnd_ai.domain.access.
  resolve_access_context`) on every request — a non-member gets a fixed,
  non-disclosing 404; a member without the capability gets 403.
- **Perspective is context, not a grant:** `character_id`/`party_id` are
  authorized through the existing `dnd_ai.api.access.
  resolve_party_perspective` — a caller-supplied `party_id` is trusted
  only after proving the caller holds `character.view_knowledge` for the
  named `character_id` *and* that character currently belongs to that
  exact party. A caller holding baseline `canon.edit` (a GM) never
  resolves a perspective at all — the same "GM sees canonical truth, not
  one party's subjective view" rule `dnd_ai.api.quests`/`.dungeon` already
  apply, kept consistent here so a GM is never required to hold a
  `character.view_knowledge` relationship just to browse.
- **Three-layer per-row visibility**, evaluated inside the SQL `WHERE`
  clause (never post-filtered after fetching, and always before `LIMIT` —
  see §2's "inaccessible records excluded before pagination" test):
  1. A per-location `campaign.view` resource-grant deny
     (`AccessContext.resource_grant_targets("campaign.view",
     field_name="entity_id")`) excludes that location outright, even for
     an otherwise-authorized caller. `entity_id` is a valid `security.
     resource_grants` target column, and a location's own `location_id`
     *is* its `entity_id` (class-table inheritance) — the same
     `resource_grant_targets`-per-list pattern `dnd_ai.api.sessions`/
     `.quests` already established for `session_id`/`quest_id`.
  2. A caller canonical-truth-authorized for that location — baseline
     `canon.edit` (not specifically denied it) or a targeted `canon.edit`
     allow for it specifically — sees it regardless of discovery.
     Mirrors `dnd_ai.queries.dungeon.get_dungeon_area_view`'s
     `include_hidden` exactly, resolved per row via the same deny/allow
     id sets rather than one `has_capability()` call per resource.
  3. Otherwise, a location is *discovery-gated* only if a `knowledge.
     knowledge_items` row names it via `subject_entity_id` — the general
     entity-subject column (already used for NPC context assembly), since
     `world.locations`/`world.dungeon_areas` carry no `is_hidden` column
     of their own (unlike a dungeon area's own structural children, which
     do). An ungated location is always visible; a gated one is visible
     only once the requesting party has discovered some knowledge item
     naming it (`knowledge.party_discoveries`), identical in shape to
     `get_dungeon_area_view`'s own discovery check.
- **`party_id=None`** (no perspective authorized, or none requested) is a
  safe default, not an error — every gated location is simply excluded,
  matching `dnd_ai.queries.dungeon`'s own documented contract for the same
  case.
- **Parent/breadcrumb non-disclosure:** a location's `parent_location_id`/
  `parent_name` are populated only when the parent *independently* passes
  the identical three-layer test. An inaccessible parent's id/name are
  never revealed through an otherwise-visible child's breadcrumb fields —
  both come back `null` together, indistinguishable from "no parent."
  Only one level of parent is resolved (no ancestor chain, no
  graph-expansion API) — a client wanting to walk further up requests the
  parent's own row once it is confirmed visible.
- **No subtype/type-based disclosure beyond what's already returned:**
  `entity_type_code` is only ever populated for an already-visible row; an
  excluded row's type is never observable through the response, counts,
  or `next_cursor` behavior.

## 4. Deliberately deferred World Explorer domains

Per the task's explicit scope boundary, none of the following were
touched in this branch — each remains exactly as documented in
`docs/PHASE13D_BACKEND_READINESS.md` §3's own "primary remaining blocker":

- Organizations, characters/NPCs, items/artifacts, historical events, and
  relationships — no list/search endpoint exists for any of these yet;
  only single-resource detail routes (where they exist at all).
- Knowledge browsing (the six portal views: known/rumors/recent/private/
  party-shared/public/sources).
- A general (non-`dungeon_area`) location **detail** route. Only
  `dungeon_area`-typed locations have a working `GET .../dungeon-areas/
  {id}` detail endpoint today (`dnd_ai.queries.dungeon.
  get_dungeon_area_view` requires a `world.dungeon_areas` row to join
  against). A settlement, building, region, nation, continent, plane,
  district, or geographic_feature returned by this list endpoint has no
  detail route to navigate to yet — the list still returns enough fields
  (name, type, summary, one level of parent) for a compact card, but
  "detail pages" for those subtypes is unbuilt, out of this task's
  explicit scope ("reuse existing... detail routes... where practical" —
  it is not yet practical for anything but `dungeon_area`). Recommended
  follow-up, sized similarly to this one: a general `GET /campaigns/
  {campaign_id}/locations/{location_id}` detail route over `core.
  entities`/`world.locations` (plus each subtype's own extra columns —
  `world.settlements.population`, `world.buildings.building_use`, ...),
  reusing this same three-layer visibility rule.
- Type-filtered browsing across any domain other than locations/dungeons.
- A generalized graph-expansion/relationship-traversal API — deliberately
  out of scope per the task itself; this endpoint's own parent field is
  bounded to one level for exactly this reason.

## 5. Files changed

- `src/dnd_ai/queries/location.py` (new) — `list_campaign_locations`,
  `LocationListItemView`/`LocationListPage`, cursor encode/decode,
  `DEFAULT_PAGE_SIZE`/`MAX_PAGE_SIZE`.
- `src/dnd_ai/api/locations.py` (new) — `GET /campaigns/{campaign_id}/
  locations`, `LocationListItemResponse`/`LocationListResponse`.
- `src/dnd_ai/api/app.py` — registers the new router (import + one
  `include_router` call, alongside every other query router).
- `tests/database/test_api_locations_list.py` (new).
- `docs/PHASE13D_WORLD_LOCATION_BROWSE.md` (this file).
- `docs/PLAN.md` — Phase 13 status paragraph, one added clause noting this
  endpoint and the still-deferred World Explorer domains (§6).

No migration was needed and none was added — every field this endpoint
returns already existed on `core.entities`/`world.locations`/`knowledge.
knowledge_items`/`knowledge.party_discoveries`/`security.resource_grants`.

## 6. docs/PLAN.md update

Phase 13's status paragraph gained one added clause (immediately after the
existing Phase 13D backend-readiness sentence from the prior workstream)
noting that this branch delivered the location/dungeon-area list endpoint
and that World Explorer's other domains (organizations, characters/NPCs,
items, events, relationships, Knowledge browsing) and a general
non-dungeon-area location detail route remain outstanding, per §4 above.
No other wording in that paragraph was rewritten, and Phase 13's overall
"Partially implemented" status is unchanged.

## 7. Focused tests added

`tests/database/test_api_locations_list.py` (17 tests), following the
existing per-endpoint fixture/cleanup convention (`tests/database/
test_api_dungeon.py`, `test_api_quests_list.py`) rather than a new shared
fixture or harness:

- Access control: non-member 404, capless-member 403.
- Basic listing (a GM sees ungated locations) and a legitimate empty
  search (`items: []`, `next_cursor: null`, `200`).
- Type filtering: `entity_type=dungeon_area` returns only the one
  dungeon-area fixture row.
- Text search: case-insensitive match over both `canonical_name` and
  `summary`.
- Deterministic keyset pagination across two identically-named locations
  (`limit=1` twice): no gap, no duplicate, and the UUID tie-break produces
  the smaller id first.
- Inaccessible-record exclusion *before* pagination: three same-type
  locations, the alphabetically-middle one discovery-gated and
  undiscovered, `limit=2` returns exactly the two accessible ones with no
  further page — proving the gated row never consumes a page slot.
- A per-location `campaign.view` resource-grant deny hiding a location for
  the targeted member only (a different member, the GM, still sees it).
- Non-GM discovery/perspective filtering: absent without an authorized
  party perspective, present once the caller's authorized party has
  discovered it (a same-type, ungated sibling location stays visible
  throughout, isolating the assertion to the gated row specifically).
- GM canonical visibility: a GM sees the gated location with no discovery
  recorded at all.
- Parent/breadcrumb non-disclosure: a GM sees a visible parent's id/name;
  a non-GM caller sees `null`/`null` for the identical child when its
  parent is itself gated and undiscovered; the same GM sees the real
  parent id/name once it independently qualifies as canonically
  authorized.
- Malformed cursor (not valid base64, and valid base64 but not the
  expected JSON payload) both rejected with `400 validation_failed`.

Deliberately not duplicated: dungeon-area structural-child discovery
filtering (features/hazards/interactables/connections) and party-
perspective authorization edge cases (foreign party, guessed UUID,
resource-grant deny/allow via access group) are already exhaustively
covered by `tests/database/test_api_dungeon.py`; this file proves only
the list endpoint's own new behavior — type filtering, search, keyset
pagination, and the location-level generalization of the existing
discovery rule — not those paths again. No new shared fixture/harness
code was added; `tests/factories.py` was not modified (every helper
needed — `make_location`, `make_dungeon`, `make_dungeon_area`,
`make_knowledge_item(subject_entity_id=...)`, `make_party_discovery`,
`make_resource_grant(entity_id=...)` — already existed).

## 8. Verification

Run against a local PostgreSQL 18 server (`DATABASE_URL` set per
`docs/DEVELOPMENT.md` §3), via `scripts/verify.sh full`:

```
PASS: ruff format --check (0s)
PASS: ruff check (0s)
PASS: mypy src (1s)
PASS: node --test foundry-module (1s)
PASS: pytest tests/unit (36s)
PASS: pytest tests/database (400s)
PASS: pytest tests/scenario (14s)
PASS: alembic check (schema diff) (2s)
All requested stages passed.
```

`pytest tests/database` includes the 17 new tests above, plus the full
pre-existing `test_api_dungeon.py` suite (34 tests combined, all passing)
proving no regression to the existing dungeon-area detail route or its
own discovery-filtering behavior. `alembic check` confirms no schema drift
— consistent with §5's "no migration needed."

## 9. Remaining blockers

All of §4's deferred domains remain open, plus one specific follow-up this
branch's own design surfaced directly: a general location detail route
(anything other than `dungeon_area`) does not exist yet, so this list
endpoint's compact cards are, for now, only fully "browse then view
details" for dungeon areas — settlements/buildings/regions/etc. can be
listed and searched but not yet opened. None of these require a product
decision to resolve (unlike Knowledge browsing's six-view semantics,
flagged in `docs/PHASE13D_BACKEND_READINESS.md`); they are direct,
appropriately-scoped follow-up implementation work.
