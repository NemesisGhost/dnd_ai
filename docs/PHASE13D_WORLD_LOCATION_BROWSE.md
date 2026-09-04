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

## 3. Authorization behavior (and two pre-merge corrections)

Reuses the existing unified boundary throughout — no second
implementation:

- **Authentication:** `dnd_ai.api.auth.get_authenticated_user_id`
  (browser-session cookie or bearer token), the same dependency every
  other route in this codebase resolves through.
- **Campaign access:** `dnd_ai.api.access.require_campaign_capability
  ("campaign.view")`, re-resolved fresh (`dnd_ai.domain.access.
  resolve_access_context`) on every request — a non-member gets a fixed,
  non-disclosing 404; a member without the capability gets 403. This is
  authorization to view the *campaign* — it has never, on its own, meant
  every definition in the campaign's world is visible; see the
  publication/lifecycle correction below for the defect that conflated
  the two.
- **Per-row visibility rule — three parts**, evaluated inside the SQL
  `WHERE` clause (never post-filtered after fetching, and always before
  `LIMIT` — see §2's "inaccessible records excluded before pagination"
  tests):
  1. A per-location `campaign.view` resource-grant deny
     (`AccessContext.resource_grant_targets("campaign.view",
     field_name="entity_id")`) excludes that location outright, even for
     an otherwise campaign-view-authorized caller — the same
     `resource_grant_targets`-per-list pattern `dnd_ai.api.sessions`/
     `.quests` already established for `session_id`/`quest_id`.
  2. **Publication/usability status** (docs/ENTITY_LIFECYCLE.md
     §2.1/§2.2): `core.entities.lifecycle_status_id` must resolve to
     `active` and `archived_at` must be `NULL`, unconditionally — a
     `pending`, `inactive`, `archived`, or `deleted` location is excluded
     from this ordinary browse route for *everyone*, `canon.edit` holder
     included. Archived/deleted records remain available to
     historical/audit/event-reference queries (that document's §12); this
     endpoint is deliberately not one of them.
  3. **Authoritativeness**: a plain `campaign.view` caller sees only
     `canon_status_id = 'canon'` (published world truth). A caller
     canonical-truth-authorized for a specific location — baseline
     `canon.edit` not specifically denied it via a `canon.edit` resource
     grant, or one specifically granted `canon.edit` for it — additionally
     sees any other canon status (`draft`, `proposed`, `approved`,
     `rejected`, `superseded`, `deprecated`) that already passed check 2,
     i.e. a GM sees their own in-progress definitions, never an
     archived/deleted one. Resolved per row via the same deny/allow id
     sets `dnd_ai.queries.dungeon.get_dungeon_area_view`'s own
     `include_hidden` argument already uses for a single resource.
- **Correction 1 (this task): canon/lifecycle-status disclosure.** The
  version of this endpoint first proposed for merge selected every
  `world.locations` row in the campaign's world with no regard for
  `canon_status_id`, `lifecycle_status_id`, or `archived_at` at all —
  meaning a plain `campaign.view` player could enumerate unpublished
  drafts. This went unnoticed because `tests.factories.make_entity()`
  defaults every entity to `canon_status='draft'`, so the endpoint's own
  tests were unintentionally proving the hole rather than catching it —
  every location the shared test fixture created was a draft, and a plain
  member's ability to list it looked like ordinary "a member can browse"
  coverage. Fixed by the three-part rule above (checks 2 and 3); every
  test in `tests/database/test_api_locations_list.py` now sets an
  explicit `canon_status_code`/`lifecycle_status_code` rather than relying
  on that default. **This endpoint does not implement archival/history
  browsing** — that is a deliberately separate, not-yet-built route (see
  §9); a `canon.edit` holder is a GM authoring or reviewing world content,
  not an archive/audit viewer, so canon.edit's override never reaches
  archived or deleted records.
- **Correction 2 (prior task): the removed knowledge/discovery
  inference.** A still-earlier version separately treated the mere
  *existence* of a `knowledge.knowledge_items` row naming a location via
  `subject_entity_id` as proof that the location itself was hidden,
  gating it behind `knowledge.party_discoveries` unless the caller held
  `canon.edit`. That rule was unsound and remains removed — it is not
  reintroduced by correction 1's `canon.edit` split, which is keyed on
  the real `canon_status_id` column, never on knowledge-item existence or
  discovery state. A knowledge item is a claim *about* its subject, not a
  flag on the subject itself — public lore, recorded history, an
  unconfirmed rumor, and a genuine secret are all represented identically
  as rows in that table, and a party's discovery of one such claim proves
  only that the claim was learned, never that the *location* itself was
  ever hidden. `world.locations`/`world.dungeon_areas` carry no
  `is_hidden` (or any other authoritative discoverability) column of
  their own (unlike a dungeon area's own structural children —
  features/hazards/interactables/connections — which do have one, per
  docs/architecture/DATABASE_MODEL.md §9.3), and CLAUDE.md's own domain
  rules already forbid the shape the removed rule needed anyway
  ("Knowledge is per-knower, never a global boolean... no
  `is_player_known`/`is_discovered` flags on the object itself").
  `dnd_ai.queries.location`'s own docstring carries the full account of
  both corrections. `character_id`/`party_id` remain absent from this
  endpoint — there is still no viewing perspective for them to authorize
  — see §9 for the tracked follow-up if a real, schema-backed location
  discoverability mechanism is designed later.
- **Parent/breadcrumb non-disclosure:** a location's `parent_location_id`/
  `parent_name` are populated only when the parent *independently* passes
  the identical three-part rule (deny, publication/lifecycle, and
  canon-status alike). An inaccessible, unpublished, or archived parent's
  id/name are never revealed through an otherwise-visible child's
  breadcrumb fields — both come back `null` together, indistinguishable
  from "no parent." Only one level of parent is resolved (no ancestor
  chain, no graph-expansion API) — a client wanting to walk further up
  requests the parent's own row once it is confirmed visible.
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
- `tests/database/test_api_locations_list.py` (new, then rewritten twice
  for the two corrections in §3).
- `tests/factories.py` — `make_entity`/`make_location`/`make_dungeon`/
  `make_dungeon_area` gained optional `canon_status_code`/`lifecycle_
  status_code`/`archived_at` keyword arguments (Correction 1 only; not
  needed for Correction 2).
- `docs/PHASE13D_WORLD_LOCATION_BROWSE.md` (this file).
- `docs/PLAN.md` — Phase 13 status paragraph, one added clause noting this
  endpoint and the still-deferred World Explorer domains (§6).

No migration was needed and none was added — every field this endpoint
returns, and every column its corrected visibility rule checks
(`canon_status_id`, `lifecycle_status_id`, `archived_at` included),
already existed on `core.entities`/`world.locations`/`knowledge.
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

`tests/database/test_api_locations_list.py` (28 tests — 6 of them one
`@pytest.mark.parametrize` over canon statuses, 4 another over lifecycle
statuses), following the existing per-endpoint fixture/cleanup convention
(`tests/database/test_api_dungeon.py`, `test_api_quests_list.py`) rather
than a new shared fixture or harness. Every location this file creates
now passes an explicit `canon_status_code`/`lifecycle_status_code`
(`tests.factories.make_location`/`make_dungeon`/`make_dungeon_area`,
extended with those keyword arguments plus `archived_at` for this task)
instead of relying on `make_entity()`'s `'draft'` default — see §3's
"Correction 1" for why relying on that default is exactly how the
canon/lifecycle disclosure defect went undetected the first time.

- Access control: non-member 404, capless-member 403.
- Basic listing (a plain member sees an active, published location) and a
  legitimate empty search (`items: []`, `next_cursor: null`, `200`).
- **Canon-status disclosure** (parametrized over `draft`, `proposed`,
  `approved`, `rejected`, `superseded`, `deprecated`): a plain member
  cannot list *or search* a location at any of these statuses; a
  `canon.edit` holder — the documented GM behavior — sees it in both,
  since it is still active and non-archived.
- **Lifecycle/archival disclosure** (parametrized over `pending`,
  `inactive`, `archived` with `archived_at` set, and `deleted`): *nobody*
  — plain member or `canon.edit` holder alike — can list or search a
  location at any of these statuses, proving `canon.edit`'s override
  never reaches archival/pending/inactive exclusion.
- Type filtering: `entity_type=dungeon_area` returns only the one
  dungeon-area fixture row.
- Text search: case-insensitive match over both `canonical_name` and
  `summary`.
- Deterministic keyset pagination across two identically-named locations
  (`limit=1` twice): no gap, no duplicate, and the UUID tie-break produces
  the smaller id first.
- Inaccessible/hidden-record exclusion *before* pagination, two
  independent mechanisms: three same-type locations with the
  alphabetically-middle one denied via a `campaign.view` resource grant
  (`limit=2`), and a second three-location trio with the middle one a
  draft (`limit=2`) — both return exactly the two accessible items with
  no further page, proving neither exclusion mechanism ever consumes a
  page slot.
- A per-location `campaign.view` resource-grant deny hiding a location for
  the targeted member only (a different member still sees it).
- **Undiscovered lore does not hide a location:** a published,
  otherwise-visible location with an undiscovered `knowledge.
  knowledge_items` row naming it still appears for a plain member with no
  perspective at all.
- **An unrelated party's discovery has no effect:** a published location
  whose one associated claim *has* been discovered by a party with no
  relationship to the requesting user appears identically to one whose
  claim has not been discovered.
- Parent/breadcrumb non-disclosure, three independent mechanisms: a
  resource-grant deny on the parent blanks both fields for the targeted
  member only (a different member still sees the real id/name); an
  unpublished (draft) parent blanks both fields for a plain member but
  shows the real id/name to a `canon.edit` holder; an archived parent
  blanks both fields for *everyone*, `canon.edit` holder included.
- Malformed cursor (not valid base64, and valid base64 but not the
  expected JSON payload) both rejected with `400 validation_failed`.

Deliberately not duplicated: dungeon-area structural-child discovery
filtering (features/hazards/interactables/connections, a real,
schema-backed `is_hidden` mechanism genuinely unrelated to either
correction) and party-perspective authorization edge cases (foreign
party, guessed UUID, resource-grant deny/allow via access group) are
already exhaustively covered by `tests/database/test_api_dungeon.py`;
this file proves only the list endpoint's own behavior. No new shared
fixture/harness code was added; `tests/factories.py` gained three new
keyword-only parameters (`canon_status_code`, `lifecycle_status_code`,
`archived_at`, all defaulting to the prior behavior) on `make_entity`,
`make_location`, `make_dungeon`, and `make_dungeon_area` — additive,
backward-compatible, and used by every other caller of those helpers
exactly as before.

## 8. Verification

Run against a local PostgreSQL 18 server (`DATABASE_URL` set per
`docs/DEVELOPMENT.md` §3), via `scripts/verify.sh full`:

```
PASS: ruff format --check (0s)
PASS: ruff check (0s)
PASS: mypy src (1s)
PASS: node --test foundry-module (1s)
PASS: pytest tests/unit (36s)
PASS: pytest tests/database (406s)
PASS: pytest tests/scenario (14s)
PASS: alembic check (schema diff) (3s)
All requested stages passed.
```

`pytest tests/database` includes the 28 tests above, plus the full
pre-existing `test_api_dungeon.py` suite, all passing — proving no
regression to the existing dungeon-area detail route or its own
discovery-filtering behavior (a real, schema-backed mechanism, genuinely
unrelated to and unaffected by either correction), and no regression to
any other caller of the three extended `tests/factories.py` helpers.
`alembic check` confirms no schema drift — consistent with §5's "no
migration needed."

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
through what authoritative schema field. Correction 2 in §3 removed a
draft rule that answered this by overloading `knowledge.knowledge_items.
subject_entity_id` as a stand-in "is this hidden" flag — an unsound
inference (a knowledge item is a claim about its subject, not a flag on
the subject) that an earlier revision of this document incorrectly
presented as already established by the dungeon-area precedent. No
replacement mechanism was introduced in its place: as of Correction 1, a
location this endpoint returns is visible to a plain `campaign.view`
caller only once it is published (`canon`, active, non-archived) and not
specifically denied by a `campaign.view` resource grant; a `canon.edit`
holder additionally sees other active, non-archived canon statuses. If
product requirements later call for location-level *discoverability*
(belief/knowledge-based hiding, as opposed to the publication-status
gating this task added), that needs an explicit convention-change
proposal (docs/DATABASE_CONVENTIONS.md §37) introducing a real column or
table for it — through the normal schema/design/migration/test process —
not a second attempt at reinterpreting an existing column.

A third item is a deliberate design boundary, not a gap: this endpoint is
the *ordinary* World Explorer browse route, and will never surface
archived, deleted, pending, or inactive locations regardless of caller
capability (§3, Correction 1). Archival/history browsing
(docs/ENTITY_LIFECYCLE.md §12: "Archived entities remain available to:
historical queries, event references, audit records, timeline
reconstruction, knowledge and relationship history") is out of this
task's scope and remains a separate, not-yet-built surface — most likely
its own route or an explicit `include_archived`-style opt-in on a
GM-only/administrative endpoint, not a parameter on this one.
