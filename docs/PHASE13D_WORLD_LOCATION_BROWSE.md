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
  full visibility rule (§3) over every matching row regardless of page
  size, which is itself the exact kind of "how many hidden things exist"
  signal `docs/PLAN.md`'s "cannot be inferred through counts" rule
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

## 3. Authorization behavior (and a pre-merge correction)

Reuses the existing unified boundary throughout — no second
implementation:

- **Authentication:** `dnd_ai.api.auth.get_authenticated_user_id`
  (browser-session cookie or bearer token), the same dependency every
  other route in this codebase resolves through.
- **Campaign access:** `dnd_ai.api.access.require_campaign_capability
  ("campaign.view")`, re-resolved fresh (`dnd_ai.domain.access.
  resolve_access_context`) on every request — a non-member gets a fixed,
  non-disclosing 404; a member without the capability gets 403.
- **Per-row visibility rule — baseline `campaign.view` plus one explicit
  override**, evaluated inside the SQL `WHERE` clause (never post-filtered
  after fetching, and always before `LIMIT` — see §2's
  "inaccessible records excluded before pagination" test): every caller
  reaching this endpoint already holds `campaign.view` for the whole
  campaign (the gate above), and a row is excluded only by an explicit
  per-location `campaign.view` resource-grant deny
  (`AccessContext.resource_grant_targets("campaign.view",
  field_name="entity_id")`). `entity_id` is a valid `security.
  resource_grants` target column, and a location's own `location_id` *is*
  its `entity_id` (class-table inheritance) — the same
  `resource_grant_targets`-per-list pattern `dnd_ai.api.sessions`/`.quests`
  already established for `session_id`/`quest_id`. There is no second
  (`canon.edit`) override layer and no perspective/discovery parameter —
  see the correction below for why.
- **Correction (pre-merge review, this document's own prior draft):** an
  earlier version of this endpoint additionally accepted `character_id`/
  `party_id` query parameters, authorized a viewing perspective through
  `dnd_ai.api.access.resolve_party_perspective`, and treated a location as
  *discovery-gated* — hidden from anyone but a `canon.edit` holder unless
  the caller's authorized party had discovered a `knowledge.
  knowledge_items` row naming that location via `subject_entity_id`. That
  rule was unsound and has been removed before merge, not merely tuned: a
  knowledge item is a claim *about* its subject, not a flag on the
  subject itself — public lore, recorded history, an unconfirmed rumor,
  and a genuine secret are all represented identically as rows in that
  table, and a party's discovery of one such claim proves only that the
  claim was learned, never that the *location* itself was ever hidden.
  Under the removed rule, attaching ordinary, undiscovered lore to an
  already-public location would have silently hidden that location from
  every non-GM caller once such lore existed at all, while a genuinely
  secret location with no knowledge item pointed at it yet (or one whose
  single associated claim happened to already be discovered) would have
  been fully exposed — backwards in both directions. `world.locations`/
  `world.dungeon_areas` carry no `is_hidden` (or any other authoritative
  discoverability) column of their own (unlike a dungeon area's own
  structural children — features/hazards/interactables/connections —
  which do have one, per docs/architecture/DATABASE_MODEL.md §9.3), and
  CLAUDE.md's own domain rules already forbid the shape the removed rule
  needed anyway ("Knowledge is per-knower, never a global boolean... no
  `is_player_known`/`is_discovered` flags on the object itself").
  `dnd_ai.queries.location`'s own docstring carries the full account.
  Because the only thing a viewing perspective would have filtered was
  this now-removed discovery gate, `character_id`/`party_id` were dropped
  from the endpoint entirely rather than kept as accepted-but-inert
  parameters — see §9 for the tracked follow-up if a real,
  schema-backed location discoverability mechanism is designed later.
- **Parent/breadcrumb non-disclosure:** a location's `parent_location_id`/
  `parent_name` are populated only when the parent *independently* passes
  the identical per-row deny check. An inaccessible parent's id/name are
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

`tests/database/test_api_locations_list.py` (16 tests), following the
existing per-endpoint fixture/cleanup convention (`tests/database/
test_api_dungeon.py`, `test_api_quests_list.py`) rather than a new shared
fixture or harness. Rewritten as part of the pre-merge correction in §3 —
every test that exercised the removed discovery-gating rule was replaced
with one proving the corrected rule instead, per the review's own
required regression list:

- Access control: non-member 404, capless-member 403.
- Basic listing (a plain `campaign.view` member sees ordinary locations)
  and a legitimate empty search (`items: []`, `next_cursor: null`, `200`).
- **A `canon.edit` holder and a plain `campaign.view` member see identical
  results** for a shared type — direct regression proof that the removed
  `canon.edit`/discovery escape hatch is gone, not merely inactive.
- Type filtering: `entity_type=dungeon_area` returns only the one
  dungeon-area fixture row.
- Text search: case-insensitive match over both `canonical_name` and
  `summary`.
- Deterministic keyset pagination across two identically-named locations
  (`limit=1` twice): no gap, no duplicate, and the UUID tie-break produces
  the smaller id first.
- Inaccessible-record exclusion *before* pagination: three same-type
  locations, the alphabetically-middle one denied for one member's own
  membership via a `campaign.view` resource grant, `limit=2` returns
  exactly the two accessible ones with no further page — proving the
  denied row never consumes a page slot (the only exclusion mechanism
  left after §3's correction).
- A per-location `campaign.view` resource-grant deny hiding a location for
  the targeted member only (a different member still sees it).
- **Undiscovered lore does not hide a location:** an otherwise-visible
  location with an undiscovered `knowledge.knowledge_items` row naming it
  still appears for a plain member with no perspective at all.
- **An unrelated party's discovery has no effect:** a location whose one
  associated claim *has* been discovered by a party with no relationship
  to the requesting user appears identically to one whose claim has not
  been discovered — proving visibility here no longer depends on
  knowledge/discovery state in either direction.
- Parent/breadcrumb non-disclosure: a member sees a visible parent's
  id/name; a resource-grant deny on the parent blanks both fields for the
  targeted member only, while a different member still sees the real
  parent id/name for the identical child.
- Malformed cursor (not valid base64, and valid base64 but not the
  expected JSON payload) both rejected with `400 validation_failed`.

Deliberately not duplicated: dungeon-area structural-child discovery
filtering (features/hazards/interactables/connections, a real,
schema-backed `is_hidden` mechanism genuinely unrelated to this
correction) and party-perspective authorization edge cases (foreign
party, guessed UUID, resource-grant deny/allow via access group) are
already exhaustively covered by `tests/database/test_api_dungeon.py`;
this file proves only the list endpoint's own behavior. No new shared
fixture/harness code was added; `tests/factories.py` was not modified —
every helper needed (`make_location`, `make_dungeon`, `make_dungeon_area`,
`make_knowledge_item(subject_entity_id=...)`, `make_party_discovery`,
`make_resource_grant(entity_id=...)`) already existed.

## 8. Verification

Run against a local PostgreSQL 18 server (`DATABASE_URL` set per
`docs/DEVELOPMENT.md` §3), via `scripts/verify.sh full`:

```
PASS: ruff format --check (0s)
PASS: ruff check (0s)
PASS: mypy src (1s)
PASS: node --test foundry-module (1s)
PASS: pytest tests/unit (36s)
PASS: pytest tests/database (401s)
PASS: pytest tests/scenario (14s)
PASS: alembic check (schema diff) (3s)
All requested stages passed.
```

`pytest tests/database` includes the 16 tests above, plus the full
pre-existing `test_api_dungeon.py` suite, all passing — proving no
regression to the existing dungeon-area detail route or its own
discovery-filtering behavior (a real, schema-backed mechanism, genuinely
unrelated to and unaffected by this correction). `alembic check` confirms
no schema drift — consistent with §5's "no migration needed."

## 9. Remaining blockers

All of §4's deferred domains remain open, plus one specific follow-up this
branch's own design surfaced directly: a general location detail route
(anything other than `dungeon_area`) does not exist yet, so this list
endpoint's compact cards are, for now, only fully "browse then view
details" for dungeon areas — settlements/buildings/regions/etc. can be
listed and searched but not yet opened. That item requires no product
decision to resolve (unlike Knowledge browsing's six-view semantics,
flagged in `docs/PHASE13D_BACKEND_READINESS.md`); it is direct,
appropriately-scoped follow-up implementation work.

A second item **does** require a product/design decision before any
implementation work: whether *locations themselves* (as opposed to a
dungeon area's structural children, which already have a real
`is_hidden` column) should ever be discovery-gated at all, and if so,
through what authoritative schema field. §3's correction removed a draft
rule that answered this by overloading `knowledge.knowledge_items.
subject_entity_id` as a stand-in "is this hidden" flag — an unsound
inference (a knowledge item is a claim about its subject, not a flag on
the subject) that this document's own prior revision incorrectly
presented as already established by the dungeon-area precedent. No
replacement mechanism was introduced in its place: every location this
endpoint returns is visible to any `campaign.view` holder in the campaign
except one specifically denied by a `campaign.view` resource grant. If
product requirements later call for location-level discoverability, that
needs an explicit convention-change proposal (docs/DATABASE_CONVENTIONS.md
§37) introducing a real column or table for it — through the normal
schema/design/migration/test process — not a second attempt at
reinterpreting an existing column.
