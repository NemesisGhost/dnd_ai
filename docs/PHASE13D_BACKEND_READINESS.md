# Phase 13D backend readiness

Audit and backend-only remediation for Phase 13D (the read-only portal:
Home, World, Characters, Quests, Sessions, Knowledge — [PLAN.md
§13](PLAN.md#phase-13-web-portal-mvp-and-same-origin-packaging), [UI_DESIGN.md
§5.3–5.8](UI_DESIGN.md#5-core-screens)). Scope is backend-only, per the
owner's instructions for this workstream: `portal/` was not opened or
modified. React implementation of these screens remains owner work on
another machine, tracked separately.

The audit method was: for each screen, find the FastAPI route(s) and
query/domain service(s) that should supply its data, then check the eight
contract properties the owner specified (cookie-session auth through the
unified boundary; per-request campaign/capability/perspective
reauthorization; perspective-as-context-not-grant; non-disclosure of
inaccessible resources; a stable response model; correct empty-result
handling; existing pagination/correlation conventions; reuse of existing
audience-filtered query services). Implementation was limited to gaps that
concretely blocked a screen from working at all — not a rebuild of every
UI_DESIGN.md bullet for every screen.

## 1. Screen-to-endpoint mapping and sufficiency

| Screen | Backing route(s) | Query/service | Sufficient for MVP? |
|---|---|---|---|
| Home | `GET /auth/session` (bootstrap), `GET /campaigns/{id}/summary`, `GET /campaigns/{id}/quests` (new), `GET /campaigns/{id}/knowledge/{id}` | `dnd_ai.queries.bootstrap.get_session_bootstrap`, `.summary.get_campaign_summary_view`, `.quest.list_campaign_quests` | Yes, for the recap/current-session/quest sections. "Recent discoveries" (knowledge) has no list endpoint yet — see §3. |
| World | `GET /campaigns/{id}/dungeon-areas/{id}`, `/characters/{id}`, `/organizations/{id}`, `/relationships/{id}` (all detail-by-id) | `dnd_ai.queries.dungeon`, `.character`, `.organization`, `.relationship` | No. Every one of these is a detail-by-id read; nothing lists or searches locations, NPCs, organizations, or items. See §3 (primary blocker). |
| Characters | `GET /auth/session` (character_perspectives), `GET /campaigns/{id}/characters/{id}`, `.../inventory` | `dnd_ai.queries.bootstrap`, `.character`, `.inventory` | Yes. The character selector is the bootstrap response's own `character_perspectives`; detail/inventory already exist and are already audience-filtered. |
| Quests | `GET /campaigns/{id}/quests` (new), `GET /campaigns/{id}/quests/{id}` | `dnd_ai.queries.quest.list_campaign_quests` (new), `.get_quest_view` | Yes, after this workstream. The list was the missing piece; the detail route's cross-campaign scoping was corrected during Phase 13D live verification — see §4.2. |
| Sessions | `GET /campaigns/{id}/sessions` (new), `GET /campaigns/{id}/sessions/{id}` (new) | `dnd_ai.queries.session` (new module) | Yes, for recap/status/timing/linked-events. Participants, locations visited, and per-session character/relationship/inventory changes are deferred — see §4. |
| Knowledge | `GET /campaigns/{id}/knowledge/{id}` (detail-by-id only) | `dnd_ai.queries.knowledge.get_knowledge_view` | No. The six portal views (known/rumors/recent/private/party-shared/public/sources) have no list endpoint. See §3. |

## 2. Contracts that were already sufficient

These held for every screen's existing routes, verified by reading
`dnd_ai.api.access`, `dnd_ai.domain.access`, and each route module, and were
not modified:

1. **Cookie-session auth through the unified boundary.** `dnd_ai.api.auth.
   get_authenticated_user_id` already resolves the `__Host-dnd_ai_session`
   browser cookie (via `dnd_ai.api.cookies.session_cookie_name`) ahead of
   the OIDC bearer-token path, and every query route in this audit depends
   on it (directly or through `require_campaign_capability`) — there is no
   separate, portal-specific auth path to drift out of sync.
2. **Per-request reauthorization.** `require_campaign_capability` calls
   `dnd_ai.domain.access.resolve_access_context` fresh on every request,
   with no caching; a revoked role, relationship, or grant takes effect on
   the very next call. Every route in this audit uses it.
3. **Perspective as context, not a grant.** `dnd_ai.api.access.
   resolve_party_perspective` requires the caller to independently hold
   `character.view_knowledge` for the named character *and* proves that
   character currently belongs to the named party, before trusting a
   caller-supplied `party_id` for anything — a campaign member cannot
   read through an arbitrary party's eyes merely by supplying its UUID.
   `resolve_character_view_tier` applies the identical discipline for
   character detail.
4. **Non-disclosure.** Every existing detail route (dungeon area,
   character, organization, relationship, quest, knowledge item) raises an
   identical, fixed 404 for "doesn't exist," "belongs to a different
   world/campaign," and "you have no relationship to it" — a caller can
   never distinguish the three. `resource_grant_targets`/`has_capability`
   with a resource-target keyword apply the same deny-overrides-allow-
   overrides-baseline precedence per resource everywhere it's used.
   (Exception found later: the quest **detail** route enforced only the
   *world*, not the campaign timeline — a same-world quest from another
   campaign's timeline leaked through. Corrected in the Phase 13D
   live-verification pass; see §4.2.)
5. **Stable response models.** Every route already returns a typed
   Pydantic model; nothing here is a loosely-typed passthrough of internal
   query dataclasses.
6. **Empty results.** Existing detail queries return `None`/empty
   collections for legitimately-empty sub-resources (e.g. a character with
   no conditions) without raising — confirmed by reading the query modules;
   no change was needed.
7. **Correlation.** `dnd_ai.api.correlation.CorrelationIdMiddleware` applies
   uniformly to every route already; nothing screen-specific was needed.
8. **Reuse of audience-filtered query services.** No screen's existing
   route reimplements authorization or visibility logic — each delegates
   to `dnd_ai.domain.access`/`dnd_ai.api.access` and its own query module.

## 3. Gaps found but not implemented (require a product/scope decision)

**World explorer and the Knowledge screen's multi-view browsing are the
primary remaining blockers**, and they were deliberately left
unimplemented rather than built ad hoc:

- **No list/search capability exists anywhere in this codebase for
  locations, organizations, items, or narrative events.** Every route this
  audit found is a single-resource "get by id" endpoint — a shape that
  made sense for their original callers (an NPC-conversation AI request
  about one specific quest, a Foundry adapter syncing one specific area),
  none of which ever needed to *enumerate*. UI_DESIGN.md §5.4 explicitly
  requires "type-filtered lists" and "text search over authorized records"
  for World explorer's MVP — neither exists, for any of the six entity
  types that screen covers.
- **Items/artifacts have no detail route at all**, even by id — only
  `GET .../characters/{id}/inventory` exposes item data, and only for
  items a character currently holds. A loose world item (in a location,
  not carried by anyone) is not reachable through any endpoint.
- **The Knowledge screen's six distinct views** (known facts / rumors and
  beliefs / recently discovered / character-private / party-shared /
  public lore / sources) have no backing list query. `campaign.
  party_knowledge` (current effective belief) and `knowledge.
  party_discoveries` (discovery log) are plausible starting tables, but
  each view implies its own audience/filter semantics that
  `docs/architecture/DATABASE_MODEL.md` §15 does not fully specify (e.g.
  whether "recently discovered" is time-windowed, campaign-wide, or
  per-character), which is a product decision, not a readiness fix.
- **No pagination convention exists to build against.**
  `docs/DATABASE_CONVENTIONS.md` §30.4 only says "use keyset pagination for
  large tables where practical" — there is no existing keyset/cursor
  implementation anywhere in `src/dnd_ai/api` or `src/dnd_ai/queries` to
  follow. Sessions and quests (§4) were small/naturally-bounded-per-
  campaign enough to ship as unpaginated lists without inventing a
  convention; locations/organizations/items/events are not, so building
  their list endpoints first would mean designing that convention from
  scratch — explicitly out of scope per this workstream's "do not create a
  new query framework" instruction.

This was judged too large and too design-dependent for a readiness
patch — it is a full workstream in its own right (list+search+pagination
across six entity types, one new knowledge-visibility design), not a
concrete gap closeable by wiring an existing service to a route.
**Recommendation:** scope a follow-up phase (e.g. "13D-2: World/Knowledge
browse backend") that first settles the pagination convention and the
Knowledge view semantics as an explicit design step, then builds the list
endpoints against it.

A smaller, self-contained deferral: **session detail does not yet surface
participants, locations visited, or per-session character/relationship/
inventory changes** (UI_DESIGN.md §5.8's fuller section list). The
session's own linked `narrative.events` (recap/status/source events) are
covered; the rest would each need their own join/audience-filtering design
(e.g. is event-participant visibility gated the same way event visibility
itself is?) and was deferred rather than guessed at.

## 4. Gaps found and fixed

Two concrete, bounded gaps blocked their screens outright and were fixed,
each by adding one query module/function following the exact shape
existing single-resource queries already use (`get_dungeon_area_view`,
`get_quest_view`, `get_organization_view`, ...), not a new abstraction:

### 4.1 Sessions had zero read capability

`dnd_ai.api.sessions` previously exposed only `POST .../sessions/{id}/end`
(a GM write). There was no way for the portal's Session detail screen to
read anything at all. Notably, `dnd_ai.domain.access._TARGET_COLUMNS`
already named `session_id` as a resource-grant target column — the
authorization machinery for a per-session grant existed and was already
tested at the domain layer, but no route had ever exercised it.

Added:

- `src/dnd_ai/queries/session.py` — `list_campaign_sessions` and
  `get_session_view`. Session fields carry no GM/player split in this
  schema (same conclusion `dnd_ai.queries.summary`'s own docstring already
  reached); the one split is a per-session `campaign.view` resource-grant
  deny/allow. Session detail additionally returns the session's own linked
  `narrative.events` rows, reusing the *exact* draft/voided visibility
  query `dnd_ai.queries.summary.get_campaign_summary_view` already uses,
  scoped by `session_id` instead of "most recent for the campaign."
- `GET /campaigns/{campaign_id}/sessions` and `GET /campaigns/
  {campaign_id}/sessions/{session_id}` in `dnd_ai.api.sessions`.

### 4.2 Quests had no way to enumerate a campaign's tracked quests

`GET /campaigns/{id}/quests/{quest_id}` (detail) already existed and was
audience-filtered at the objective level, but nothing could produce the
`quest_id` to call it with — the portal's Home dashboard ("active quests")
and a Quests screen both need a list. (The detail route's *top-level*
campaign scoping had a defect corrected during live verification — see the
**Phase 13D live-verification correction** at the end of this section.)

Added:

- `list_campaign_quests` in `src/dnd_ai/queries/quest.py` — every quest
  with a `campaign.quest_state` row on the caller's timeline. `quest_id`/
  `name`/`status_code` only — the same three fields `get_quest_endpoint`
  already returns unconditionally at the top level of its own response
  (only per-objective `visibility_policy` is audience-split there), so the
  list discloses nothing the existing detail route didn't already.
- `GET /campaigns/{campaign_id}/quests` in `dnd_ai.api.quests`. A caller
  holding baseline `canon.edit` (a GM) never resolves a party perspective
  for this list — the same "GM sees canonical truth, not one party's
  subjective view" rule `get_quest_endpoint`'s own `include_hidden` branch
  already applies, kept consistent here so a GM isn't required to hold a
  `character.view_knowledge` relationship just to view the list.

**Post-implementation review correction.** The initial cut had two
defects, both fixed before merge:

1. **The list never resolved per-quest `campaign.view` resource-grant
   denies.** An incorrect module comment claimed "no per-quest
   resource-grant target exists here" — `quest_id` is, in fact, a valid
   `security.resource_grants`/`AccessContext.has_capability()`/
   `.resource_grant_targets()` target column, exactly like `session_id`
   already is for sessions. `list_quests_endpoint` now resolves
   `access.resource_grant_targets("campaign.view", field_name="quest_id")`
   and passes the denied set into `list_campaign_quests`, which excludes
   those quests in SQL before the response is built — the same pattern
   `dnd_ai.api.sessions` already uses for `denied_session_ids`. The
   **detail** route (`get_quest_endpoint`) had the identical gap from the
   opposite direction: it only ever checked a quest-scoped `canon.edit`
   grant (which correctly gates `include_hidden` — whether every objective
   is returned regardless of `visibility_policy`) but never checked a
   quest-scoped `campaign.view` grant, so a targeted `campaign.view` deny
   had no effect on the route at all. It now checks
   `access.has_capability("campaign.view", quest_id=quest_id)` first and
   returns the standard non-disclosing 404 if denied, kept explicitly
   separate from the `include_hidden` check that follows it.
2. **A quest tracked only through one party's independent
   `campaign.quest_state` row (no campaign-wide row) was silently excluded
   from a GM's own list.** `docs/architecture/DATABASE_MODEL.md` §14:
   campaign-wide (`party_id IS NULL`) and per-party tracking are
   independent — neither implies the other — so a GM (who sees canonical
   truth across every party) needs to see quests tracked exclusively
   through any single party too. `list_campaign_quests` gained an explicit
   `include_all_parties` parameter: `True` for a caller holding baseline
   `canon.edit` (every `campaign.quest_state` row on the timeline counts,
   campaign-wide or any party's own), `False` otherwise (only
   campaign-wide rows plus the caller's own authorized party's rows count —
   preserving cross-party privacy: one party's private tracking is not
   disclosed to a different party's own member). The contract is now
   **"every quest with a `campaign.quest_state` row visible to this
   caller's own perspective (canonical for a GM, own-party-or-campaign-wide
   otherwise)"**, not merely "every quest with a campaign-wide row."

**Phase 13D live-verification correction.** Live verification found that
`get_quest_view` (the detail query) established campaign exposure only from
the quest's *world* — `quest_id` exists and `world_id == expected_world_id`
— and then, when no `campaign.quest_state` row matched the requested
timeline, returned the world-scoped quest definition with a null status
instead of treating it as unavailable. Quest *definitions* are world canon
with no `campaign_id` (`docs/architecture/DATABASE_MODEL.md` §14), and one
world hosts many campaign timelines, so "same world" is **not** "exposed
to this campaign": `GET /campaigns/{campaign_a}/quests/{campaign_b_quest}`
returned Campaign B's quest name, stages, and objectives while inside
Campaign A, even though the same quest never appeared in Campaign A's list
(the list is timeline/audience scoped). List and detail authorization
disagreed.

Fix: campaign exposure is now established the same way for both routes — a
qualifying `campaign.quest_state` row on the campaign's **exact
`timeline_id`**, under the one shared audience predicate
`dnd_ai.queries.quest._QUEST_STATE_MATCHES_AUDIENCE` (campaign-wide row,
the caller's own authorized `party_id`'s row, or — for a GM, baseline
`canon.edit` with no quest target — any party's row on that timeline).
`get_quest_endpoint` passes `get_quest_view(...,
require_campaign_tracking=True, include_all_parties=access.has_capability(
"canon.edit"))`; the AI context/proposal callers
(`dnd_ai.domain.context_assembly`, `dnd_ai.commands.ai_proposals`)
deliberately do not opt in, since they draw quests from
`narrative.quest_participants`, not campaign tracking. A same-world quest
tracked only on another campaign's timeline, only for an unauthorized
party, or not tracked at all now raises the same fixed non-disclosing 404
as a nonexistent or cross-world quest — no response-body difference
reveals which condition occurred. `scripts/setup_phase13c_dev_data.py`'s
read-only production-query verification now actually performs the
cross-campaign lookup (previously it printed the expected URL and the
then-current leaking behavior).

**Quest-targeted `canon.edit` semantics (follow-up correction).** A review
of the fix above found one residual list/detail disagreement: a non-GM
holding only a quest-*targeted* `canon.edit` allow got `include_hidden=True`,
which the detail route used to also skip `resolve_party_perspective` — but
`include_all_parties` stayed `False` (it is derived from *baseline*
`canon.edit`). For a quest tracked only through that caller's own
authorized party, `get_quest_view` then received `party_id=None` and 404'd,
while `list_quests_endpoint` (which resolves the perspective) listed it.

Resolved by fixing the intended semantics explicitly: **a quest-targeted
`canon.edit` grant affects objective visibility (`include_hidden`) only —
it never widens tracking exposure.** `include_all_parties` stays tied to
baseline `canon.edit` (campaign-wide GM standing) for both list and detail.
`get_quest_endpoint` now skips the party perspective only for a baseline GM
*in good standing for the quest* (`is_gm and include_hidden` — i.e. no
quest-targeted `canon.edit` deny); a targeted-allow non-GM, and a baseline
GM specifically denied `canon.edit` for the quest, both resolve an
authorized party perspective. `canon.edit` target precedence is intact: a
targeted deny still strips `include_hidden` from a baseline GM. Another
party's privately-tracked quest remains a non-disclosing 404 for a
targeted-allow holder — the chosen semantics do not permit reaching it.

## 5. Files changed

- `src/dnd_ai/queries/session.py` (new)
- `src/dnd_ai/api/sessions.py` (list/detail routes added; docstring updated)
- `src/dnd_ai/queries/quest.py` (`list_campaign_quests` added, then
  corrected per §4.2: `include_all_parties`/`denied_quest_ids`; then the
  live-verification correction: shared `_QUEST_STATE_MATCHES_AUDIENCE`
  predicate, `get_quest_view` `require_campaign_tracking`/
  `include_all_parties`)
- `src/dnd_ai/api/quests.py` (list route added; detail route hardened with
  a quest-scoped `campaign.view` check; then `require_campaign_tracking`
  wired into `get_quest_endpoint`; then the quest-targeted `canon.edit`
  semantics correction — party perspective resolved for a targeted-allow
  non-GM; docstrings updated)
- `tests/database/test_api_sessions_query.py` (new)
- `tests/database/test_api_quests_list.py` (new, then extended per §4.2)
- `tests/database/test_api_quests_query.py` (extended per §4.2: the
  detail-route `campaign.view` deny regression)
- `tests/database/test_api_quests_campaign_scope.py` (new — the
  live-verification cross-campaign disclosure regression, query + API)
- `tests/database/test_setup_phase13c_dev_data.py` (cross-campaign quest
  test updated to assert the now-non-disclosing behavior)
- `scripts/setup_phase13c_dev_data.py` (verification block + prose: the
  cross-campaign lookup is now really exercised)
- `docs/PHASE13D_BACKEND_READINESS.md` (this file)
- `docs/PLAN.md` (Phase 13 status paragraph — one sentence noting the
  session/quest read-side addition; see §7)

`portal/` was not opened.

## 6. Focused tests added

Both new test files follow the existing per-endpoint fixture/cleanup
convention (`tests/database/test_api_organizations_query.py`,
`test_api_quests_query.py`) rather than a new shared fixture or harness.

- **`tests/database/test_api_sessions_query.py`** (13 tests): access
  control (non-member 404, capless-member 403) for both routes; list
  ordering (most-recent-first); detail field shape; the draft/voided event
  split (player never sees a draft, GM sees draft but never voided); a
  targeted `campaign.view` deny on `session_id` hiding the session from
  both the list and direct detail access — **a previously untested
  security-sensitive contract**, since no route existed to exercise
  `security.resource_grants.session_id` before this workstream; the same
  deny not affecting a different member; and cross-campaign/nonexistent-
  session rejection.
- **`tests/database/test_api_quests_list.py`** (10 tests): access control;
  that only tracked quests appear (an untracked-but-defined quest is
  proven absent, now alongside a party-only-tracked one that *is* proven
  present); the campaign-wide-status default; the
  party-preferred-over-campaign-wide status fallback with an authorized
  character/party perspective; a party-only-tracked quest visible to a GM
  (`status_code=None`, no campaign-wide row to resolve) and to its owning
  party's own authorized perspective; and — the §4.2 correction's own
  regression coverage — a targeted `campaign.view` deny hiding a quest
  from the list without removing other visible quests, that same deny
  returning 404 on direct detail access, and the deny not affecting a
  different campaign member.
- **`tests/database/test_api_quests_query.py`** (+3 tests): the detail
  route's own targeted `campaign.view` deny returning 404, the deny not
  affecting a different member, and an unrelated quest's deny not hiding
  the quest under test — deliberately kept separate from this file's
  existing targeted-`canon.edit` tests (§4.2: two independent checks, easy
  to conflate).
- **`tests/database/test_api_quests_campaign_scope.py`** (23 tests — the
  live-verification correction): one world / two timelines / one campaign
  per timeline, Campaign B's quest state only on Timeline B. Both the real
  FastAPI route and the real `get_quest_view`/`list_campaign_quests`
  queries are exercised (no mocked repository results). Covers: a tracked
  quest returns normally; Campaign B's quest is unavailable through
  Campaign A (same world, different timeline) and still normal under
  Campaign B; cross-world, untracked, and party-scoped-for-another-party
  quests unavailable; a campaign-wide row makes a quest visible; a GM sees
  a party-tracked quest across parties; a quest-specific `campaign.view`
  deny stays unavailable; objective-level `visibility_policy` filtering is
  unchanged after the top-level check; every rejection path returns the
  identical fixed `(code, message)` with no quest/stage/objective detail;
  and list/detail agree (a quest excluded from an audience's list is not
  directly fetchable by that audience). The quest-targeted `canon.edit`
  semantics correction adds 5 more: a non-GM holding only a quest-targeted
  `canon.edit` allow can fetch a quest tracked only through their own
  authorized party (detail and list agree for the same
  `character_id`/`party_id`); the same allow reveals every objective on a
  campaign-wide quest (`include_hidden`); and another party's
  privately-tracked quest stays a non-disclosing 404 even with that allow.

Deliberately not duplicated: `visibility_policy` filtering,
resource-grant overrides for quest-detail `include_hidden`, and
party-perspective authorization edge cases are already exhaustively
covered by `tests/database/test_api_quests_query.py` and
`test_api_dungeon.py`; this workstream's tests prove only the new list/
session behavior and the §4.2 `campaign.view`-deny regression, not those
paths again.

## 7. docs/PLAN.md update

Phase 13's status paragraph now notes, in one added clause, that the
Phase 13D backend-readiness pass delivered the session and quest
list/detail read endpoints described above — it does not change Phase
13's overall "Partially implemented" status (the portal itself, and the
World/Knowledge browsing backend, remain outstanding) and no other
wording in that paragraph was rewritten.

## 8. Verification

Run against a local PostgreSQL 18 server (`DATABASE_URL` set per
`docs/DEVELOPMENT.md` §3):

```
uv run ruff format --check   # PASS
uv run ruff check            # PASS
uv run mypy src              # PASS
uv run pytest tests/unit           # PASS
uv run pytest tests/database       # PASS (includes the 26 new/added tests above)
uv run pytest tests/scenario       # PASS
uv run alembic -c database/alembic.ini upgrade head && \
  uv run alembic check        # PASS — no schema diff (no migration needed;
                               #        no new tables/columns)
```

Full battery run via `scripts/verify.sh full`:

```
PASS: ruff format --check (0s)
PASS: ruff check (0s)
PASS: mypy src (1s)
PASS: node --test foundry-module (1s)
PASS: pytest tests/unit (36s)
PASS: pytest tests/database (394s)
PASS: pytest tests/scenario (13s)
PASS: alembic check (schema diff) (3s)
All requested stages passed.
```

No migration was needed — both new endpoints read existing tables/columns
only (`campaign.sessions`, `narrative.events.session_id`, `campaign.
quest_state`, `security.resource_grants.session_id`), all already present.

## 9. Remaining blockers requiring a product/UI decision

1. **World explorer backend (§3)** — **RESOLVED**, see §10. The
   pagination convention, `GET .../world/search`, and the typed detail
   routes are delivered on the `phase13d/world-knowledge-read-api` branch.
2. **Knowledge screen's six views (§3)** — **RESOLVED**, see §10.5. The
   per-view semantics, the "recently discovered" ordering, and the
   "Sources is a facet not a view" decision are documented and delivered.
3. **Item/artifact detail-by-id** — **RESOLVED**, see §10.2
   (`GET .../world/items/{item_instance_id}`); ownership/inventory on that
   detail remains deferred (§10.8 item 4).
4. **Session detail's participants/locations-visited/encounter and
   character-state-change sections (§3)** — deferred; each needs its own
   join/audience-filtering design against `narrative.event_participants`/
   `.event_locations` and the `campaign.character_state`/`_conditions`/
   `_resources` history.

---

## 10. World Explorer + Knowledge browse backend (delivered)

Blockers §9.1–§9.3 above are **closed** by the
`phase13d/world-knowledge-read-api` workstream. This section is the
delivered contract; §9's recommendation to scope it as its own phase was
followed (it is a single branch/PR, not folded into the readiness patch).

### 10.1 Owner decision — World Explorer visibility

The schema has **no entity-level discovery/knowledge gating** for world
locations, organizations, items, historical events, relationships, or
religions. Discovery state exists only for dungeon structural children
(`world.*.is_hidden` + `knowledge.party_discoveries`) and
`knowledge.knowledge_items` (the Knowledge screen's own domain). The owner
directed (2026-09-09) that World Explorer visibility **mirror what the
existing single-resource detail endpoints already disclose** rather than
invent a speculative discovery mechanism (this workstream's spec: "derive
nothing speculatively"):

- **Baseline** for every category is `campaign.view` (already required to
  reach any of these routes).
- **Per-resource `campaign.view` deny** (`security.resource_grants`,
  `entity_id`/`event_id`/`knowledge_item_id` target) removes a specific
  record from *both* the list and its own detail route — resolved by the
  caller via `AccessContext.resource_grant_targets(...)` and applied in
  SQL before pagination. No `allow` counterpart (baseline is already
  `True` for every `campaign.view` holder — the same reasoning
  `list_campaign_quests`/`list_campaign_sessions` document).
- **GM-only *fields*** (`world.organizations.internal_description`,
  `campaign.relationship_state` subjective rows, knowledge
  `truth_status`/`sensitivity`) stay gated by `canon.edit` in the reused
  detail queries — unchanged.
- **Characters** are the one category with a stricter existing gate: a
  character appears only when the caller holds one of
  `character.discover`/`.view_summary`/`.view_full`/`canon.edit` for it
  (campaign-wide role capability, per-character
  `security.membership_character_relationships` row, or a
  `security.resource_grants` allow), minus any per-character deny —
  `dnd_ai.api.world_explorer.resolve_world_character_visibility`. A caller
  holding **only** `character.discover` for a character sees the search
  card but a `GET .../characters/{id}` detail 404s — that is the
  documented meaning of "discover" (UI_DESIGN.md §5.5: "Character may
  appear in search or links"), not a list/detail disagreement.
- **Events** additionally honor `narrative.events` timeline scope and the
  `draft`/`voided` split `dnd_ai.queries.summary` established: a `voided`
  event is never listed for anyone; a `draft` event only for a
  `canon.edit` caller (or one holding a `canon.edit` allow targeting that
  `event_id`).

Every rejection path (nonexistent, cross-world, cross-timeline for events,
denied) returns the identical fixed non-disclosing 404 — a caller can
never distinguish which applied. List and detail eligibility agree because
the same SQL predicates are reused; **the pre-existing organization-detail,
dungeon-area-detail, and character-detail (+`/inventory`) routes were
hardened** with the entity-targeted `campaign.view` deny check to preserve
that agreement (the same fix the quest-detail route received — §4.2). For
characters this deny is a coarser gate applied *ahead of* the
`character.discover`/`.view_summary`/`.view_full` tier: it removes the
record entirely (404), where the tier only downgrades or withholds
detail; the tier decisions themselves are unchanged.

### 10.2 Endpoint matrix

| Method + path | Purpose | Backing query |
|---|---|---|
| `GET /auth/session` | +`campaigns[].world_id`/`world_name`; +`campaigns[].character_perspectives[].authorized_parties[]` (`party_id`,`party_name`) — additive, all prior fields/behavior preserved | `dnd_ai.queries.bootstrap.get_session_bootstrap` |
| `GET /campaigns/{campaign_id}/world/search` | Unified type-filtered text search / browse across `location`, `character`, `organization`, `religion`, `item`, `event` | `dnd_ai.queries.world_explorer.search_world_entities` |
| `GET /campaigns/{campaign_id}/world/relationships` | Relationship list | `.list_world_relationships` |
| `GET /campaigns/{campaign_id}/world/locations/{location_id}` | Location detail (any `world.locations` row) + containment breadcrumbs | `.get_location_view` |
| `GET /campaigns/{campaign_id}/world/religions/{religion_id}` | Religion detail | `.get_religion_view` |
| `GET /campaigns/{campaign_id}/world/items/{item_instance_id}` | Item-instance detail | `.get_item_view` |
| `GET /campaigns/{campaign_id}/world/events/{event_id}` | Historical-event detail | `.get_event_view` |
| `GET /campaigns/{campaign_id}/knowledge` | Audience-filtered Knowledge-screen list, `?view=` | `dnd_ai.queries.knowledge_browse.list_knowledge` |
| `GET /campaigns/{campaign_id}/knowledge/{knowledge_item_id}` | Existing single-item read — extended (backward-compatibly) for a character-private lookup and a public-lore fallback | `dnd_ai.queries.knowledge.get_knowledge_view` |

Existing detail routes **reused** for their categories:
`GET /campaigns/{id}/characters/{id}` (+`/inventory`) (deny-hardened),
`GET /campaigns/{id}/organizations/{id}` (deny-hardened),
`GET /campaigns/{id}/relationships/{id}`,
`GET /campaigns/{id}/dungeon-areas/{id}` (deny-hardened). "Deny-hardened" =
gained the entity-targeted `campaign.view` deny check so list and detail
cannot disagree on which resources an audience may see; no other behavior
of these routes changed.

All routes: `campaign.view` required; cookie-session or bearer auth
through the unified boundary; per-request reauthorization; no CSRF header,
no idempotency key, no `audit.change_log` row, no mutation; same-origin
`/api/*`.

### 10.3 Response DTOs

- **`WorldEntityCard`** (search item): `entity_id`, `category`
  (`location`|`character`|`organization`|`religion`|`item`|`event`),
  `entity_type_code`, `name`, `summary`. Uniform and non-sensitive by
  construction — denied records are filtered out entirely, not
  down-projected. `WorldEntitySearchResponse` = `{items[], next_cursor}`.
- **`RelationshipCard`**: `relationship_id`, `relationship_type_code`,
  `description`, `participant_entity_ids[]`. `RelationshipListResponse` =
  `{items[], next_cursor}`.
- **`LocationDetailResponse`**: `location_id`, `name`, `summary`,
  `location_type_code`, `parent_location_id` (null when the parent is
  denied to the caller), `breadcrumbs[]` (`{location_id, name,
  location_type_code}` root → parent, truncated at the first denied
  ancestor), `population`/`building_use`/`danger_level` (subtype fields,
  null when N/A), current `campaign.location_state` (`is_searched`,
  `is_destroyed`, `alarm_level`, `condition_notes` — null when no row).
- **`ReligionDetailResponse`**: `religion_id`, `name`, `summary`,
  `pantheon_structure`, `serving_organization_ids[]` (authorized only).
- **`ItemDetailResponse`**: `item_instance_id`, `name`, `summary`,
  `item_definition_id`, `origin_notes`, current `campaign.item_state`
  (`quantity`, `condition_percentage`, `charges_current`,
  `charges_maximum`, `is_equipped`, `is_destroyed` — null when no row).
- **`EventDetailResponse`**: `event_id`, `name`, `summary`,
  `event_type_code`, `event_status_code`, `world_time_id`, `details`,
  `session_id`, `participants[]` (`{entity_id, role_code}` — each
  independently filtered), `locations[]` (`{location_id, role}` —
  filtered).
- **`KnowledgeListItemResponse`**: `knowledge_item_id`,
  `knowledge_type_code`, `statement` (viewer-safe: the party's/character's
  own `interpretation` when recorded, else canonical; canonical for a GM
  canonical view), `truth_status_code`/`sensitivity` (GM-only — null
  otherwise), `awareness_level`, `confidence`, `willing_to_share` (the
  same belief the `statement` and `scope` came from — never mixed across
  perspectives, nulls preserved; all null for a GM canonical view),
  `scope` (`party`|`character`|`public`|`canonical`),
  `discovery_world_time_id`,
  `source_event_id`, `source_interaction_id`, `subject_entity_id`
  (related-resource link). `KnowledgeListResponse` = `{items[],
  next_cursor}`.

Every response is a typed Pydantic model — no loosely-typed DB rows, no
generic entity DTO for detail.

### 10.4 Search / filter / pagination behavior

- **`/world/search`** query params: `category` (repeatable; omitted = all
  six), `q` (≤200 chars, case-insensitive substring over
  `core.entities.canonical_name` + `summary` — never `core.entity_names`
  aliases, some of which are themselves a disclosure), `limit` (1–100,
  default 25), `cursor`.
- **`/world/relationships`** params: `q` (over `description`), `type`
  (`world.relationship_types.code`), `related_entity_id`, `limit`,
  `cursor`.
- **`/knowledge`** params: `view` (default `known`), `character_id`,
  `party_id`, `q` (over the viewer-safe statement), `type`
  (`knowledge.knowledge_types.code`), `limit`, `cursor`.
- **Ordering** — deterministic and stable: entity search
  `(lower(left(canonical_name, 200)), entity_id)`; relationships
  `(relationship_id)`; statement-ordered knowledge views
  `(lower(left(statement, 200)), knowledge_item_id)`; `recent`
  `(world_time.sort_key DESC NULLS LAST, party_discovery_id)`. The 200
  **code-point** name/statement prefix is the actual sort key (computed in
  SQL, carried verbatim in the cursor): `(prefix, unique_id)` is still a
  strict total order, so keyset paging over it never skips or repeats a
  row. Records sharing a 200-code-point prefix are ordered by their stable
  id.
- **Cursor** (`dnd_ai.api.pagination`) — an **opaque, strictly-validated**
  base64url(JSON) token: `[version, keyset_name, [sort values]]`. Not
  signed (this app has no signing secret and does not need one): every
  decoded value is bound as a SQL parameter, never interpolated, and the
  keyset predicate only ever *narrows* an already-authorized,
  already-filtered result set. The embedded `keyset_name` binds a cursor
  to the endpoint family that issued it. The JSON is serialized
  `ensure_ascii=False`, so a non-ASCII sort-key code point costs its ≤4
  UTF-8 bytes (or 6 for a JSON-escaped control char) rather than a 12-byte
  `\uXXXX\uXXXX` surrogate pair; a 200-code-point prefix therefore encodes
  to ≲1.7 KB in the worst case, well under the decoder's 2 KB bound, for
  any script — **every server-issued `next_cursor` round-trips**, and
  `encode_cursor` raises rather than emit one that would not. A malformed
  / tampered / wrong-keyset / wrong-arity / over-long cursor → fixed
  **422 `invalid_cursor`**, non-disclosing (never echoes the value).
- **No total count** on any browse response (UI_DESIGN.md §9). A page
  reports only whether `next_cursor` is non-null (over-fetch `limit + 1`,
  presence of the extra row is the "has next page" signal).
- **Empty result** → `{items: [], next_cursor: null}` — identical for
  "authorized but nothing matches" and "no authorized perspective", never
  an existence hint.
- **Invalid filter value** (bad `category`, `view`, out-of-range `limit`)
  → FastAPI request validation, **422 `invalid_request`**.

### 10.5 Knowledge view semantics

| `view` | Source | Audience |
|---|---|---|
| `known` | `campaign.party_knowledge` (authorized party), `knowledge_type` **not** in the rumor set | the party's settled knowledge |
| `rumors` | `campaign.party_knowledge` (authorized party), `knowledge_type` **in** rumor/belief/misconception/theory/prophecy | the party's unsettled beliefs |
| `party_shared` | `campaign.party_knowledge` (authorized party), every row | the party's collective knowledge (union of the two above) |
| `character_private` | `knowledge.entity_knowledge` where `knower_entity_id` = the authorized character | that character's individual beliefs |
| `recent` | `knowledge.party_discoveries` for the authorized party and/or character, newest discovery-world-time first; every viewer-facing column (statement, scope, awareness/confidence/sharing) resolved through *that discovery owner's own* belief | the audience's discovery stream |
| `public` | `knowledge.public_knowledge` on the timeline | any `campaign.view` caller — **no perspective needed** |

The `known`/`rumors` split is grounded in the seeded
`knowledge.knowledge_types` vocabulary, not an invented flag.

**"Sources" is not a `view`.** The domain model has no standalone
provenance table — `learned_via_*`/`discovered_via_*` live on
`entity_knowledge`/`party_discoveries` themselves. Every list item carries
`source_event_id`/`source_interaction_id`/`discovery_world_time_id` where
authorized; the portal's "Sources" tab is a client-side presentation over
any view (most naturally `recent`).

**"Recently discovered" (`recent`)** is an ordered stream, not a
wall-clock window: newest visible discovery first, ordered by
`core.world_times.sort_key` of `discovered_at_world_time_id`, **NULLS
LAST**, with the immutable `party_discovery_id` as the tie-breaker.
Discoveries with no recorded world time sort after every dated one.

For a **non-GM** caller *every* viewer-facing column of a `recent` row —
`statement`, `scope`, `awareness_level`, `confidence`,
`willing_to_share` — is resolved through the **discovery owner's own**
belief: `campaign.party_knowledge` for a party-owned discovery,
`knowledge.entity_knowledge` for a character-owned one (`scope` `party` /
`character` accordingly). The statement falls back to the canonical text
only when that belief records no interpretation of its own (the identical
rule `character_private`/`party_shared`/the detail route apply); a `NULL`
in the owning belief's metadata is preserved, never borrowed from the
other perspective, so a card can never mix one belief's statement with
another's confidence, and it is stable whether or not the request also
carries the unrelated (authorized) perspective. The `q` substring match
runs against that same viewer-safe statement expression, so a
canonical-only search term cannot surface a distorted belief. A discovery
whose matching belief row does not exist at all is **omitted** — `recent`
never falls back to a bare canonical statement and never lists an item the
matching detail route would 404 on.

**GM (baseline `canon.edit`)** sees the canonical statement (`scope`
`canonical`) with **no** party/character belief metadata
(`awareness_level`/`confidence`/`willing_to_share` are `null`) — identical
to `known`/`rumors` canonical, which also carry `truth_status`/
`sensitivity`. A GM who wants one perspective's belief metadata queries
`party_shared`/`character_private` with that perspective. With no
perspective every discovery on the timeline is in scope; with one, only
that party's/character's. For `known`/`rumors` a GM with no perspective
sees `knowledge.knowledge_items` in the world; `party_shared`/
`character_private` still require the GM to supply an authorized
party/character perspective and return an empty page without one. A non-GM
never receives `truth_status`/`sensitivity`.

### 10.6 Perspective resolution (Phase 13D §4)

- A caller-supplied `character_id`/`party_id` **never** grants access.
  `dnd_ai.api.access.resolve_party_perspective` (unchanged) re-proves, per
  request: the caller holds `character.view_knowledge` for `character_id`,
  `party_id` is associated with the campaign, and `character_id` is a
  **current** `campaign.party_memberships` member of `party_id` on the
  campaign's own timeline. Any failure → fixed non-disclosing 404 (not a
  silent downgrade).
- **Ambiguous multi-party membership** is handled deterministically by
  requiring the portal to name the `party_id` explicitly — it is never
  guessed from `character_id`. `/auth/session` now hands the portal the
  exact set it may choose from:
  `campaigns[].character_perspectives[].authorized_parties[]` — the
  parties each authorized character is a current member of, campaign-
  associated, recomputed every bootstrap. Parties/characters the user
  cannot select never appear.
- `character_private` needs only `character_id` (with
  `character.view_knowledge` held for it). `recent` accepts either or
  both. `public` needs neither.
- The existing `GET .../knowledge/{id}` detail route is unchanged for its
  GM and `(character_id, party_id)` callers, and additionally: a non-GM
  who supplies **only** `character_id` and holds `character.view_knowledge`
  for it gets that character's own `entity_knowledge` belief
  (`knower_entity_id`); any caller gets the public-lore fallback
  (`allow_public`) for an item published in `knowledge.public_knowledge` —
  so `character_private` and `public` lists agree with detail.
- `GET /campaigns/{id}/characters/{id}` and `.../inventory` now reject an
  entity-targeted `campaign.view` deny for that `character_id` with the
  same fixed non-disclosing 404 the World Explorer search applies (§10.1),
  so a character hidden from `/world/search?category=character` can no
  longer be reopened by its retained URL. The per-character
  `character.view_*` tier is a separate, finer decision and is unchanged.

### 10.7 World Explorer category coverage

| UI_DESIGN.md §5.4 category | Covered by |
|---|---|
| locations and dungeons | `/world/search?category=location` (all `world.locations` kinds incl. dungeon/dungeon_area) + `/world/locations/{id}`; dungeon-area *structural children* stay on `/dungeon-areas/{id}` |
| NPCs and player characters | `/world/search?category=character` (bare `character`, `npc`, `player_character`) + existing `/characters/{id}` (+`/inventory`), now honoring the entity-targeted `campaign.view` deny so list and detail agree |
| organizations, factions, governments, religions, cultures | `category=organization` (business/government/religious_organization/military_unit/political_faction) + `category=religion`; existing `/organizations/{id}` + `/world/religions/{id}`. ("cultures" — `world.cultures` was never built; no schema exists, so no endpoint — see §10.8.) |
| items and artifacts | `category=item` + `/world/items/{id}` |
| historical events | `category=event` + `/world/events/{id}` |
| relationships | `/world/relationships` + existing `/relationships/{id}` |
| approved lore and knowledge | the `/campaigns/{id}/knowledge` list (`view=public` for lore) + `/knowledge/{id}` |

### 10.8 Known intentional limitations

1. **Relationship edges are not hidden by node visibility.** The
   `/world/relationships` list mirrors the *existing* relationship-detail
   contract — `dnd_ai.queries.relationship`'s own model treats
   participants as a structural fact visible to any `campaign.view`
   caller; only per-participant *subjective* state is GM-gated. A card's
   `participant_entity_ids` therefore may include an entity the caller
   cannot open in `/characters/{id}` (exactly as the existing
   `/relationships/{id}` route already discloses). Hiding an edge whose
   node a caller cannot discover would be a change to the existing
   relationship contract, not just this list — deferred as a deliberate
   product decision, not built speculatively.
2. **No `cultures` endpoint.** UI_DESIGN.md §5.4 lists "cultures" but no
   `world.cultures` table (or any culture concept) exists in the schema.
   Not built — deriving one would be new domain vocabulary ahead of the
   phase that needs it.
3. **Archived entities are not filtered** from World Explorer lists —
   consistent with "mirror existing detail endpoints" (the reused detail
   queries do not filter `core.entities.archived_at` either). If the
   product wants archived records hidden from browse, that is a
   cross-cutting change to every world read, tracked separately.
4. **Item detail carries state only, not ownership/inventory** (who
   currently holds it). That needs its own audience design (§9.3) and no
   §5.4 bullet requires it for the MVP.
5. **`recent` requires a recorded belief row.** A discovery is listed only
   when the discovery owner (party or character) has a matching
   `campaign.party_knowledge` / `knowledge.entity_knowledge` row; the
   statement shown is that belief's interpretation (or the canonical text
   it points at when the belief records no distortion). A discovery with
   no belief row is omitted rather than shown with a bare canonical
   fallback — this keeps `recent` in agreement with the detail route but
   means a discovery event that was never followed by a belief update does
   not appear in the stream. (Earlier revisions of this workstream leaked
   the canonical statement here for a character-only perspective — fixed.)
6. **`/world/search` `q`** matches `canonical_name` + `summary` only, not
   `core.entity_names` aliases (secret/mistaken alias types would be a
   disclosure risk).
7. **Session detail's participants/locations/state-change sections**
   (§9.4) remain deferred — untouched by this workstream.

### 10.9 Migrations

**None.** Every endpoint reads existing tables/columns only. No index was
added: the delivered `q`/keyset queries were judged acceptable for the
MVP's data scale against the existing FK indexes (`ix_*` on
`core.entities.world_id`, `entity_type_id`; `knowledge.*` and
`campaign.party_knowledge` timeline/party/item indexes from migrations
041/073/074); adding a `pg_trgm` GIN index for `ILIKE` or a covering
keyset index is a measured-first follow-up (DATABASE_CONVENTIONS.md
§33.1), not a speculative addition here.

### 10.10 Files changed

- `src/dnd_ai/api/pagination.py` (new) + `src/dnd_ai/api/errors.py`
  (`InvalidCursorError`)
- `src/dnd_ai/queries/world_explorer.py`, `src/dnd_ai/api/world_explorer.py` (new)
- `src/dnd_ai/queries/knowledge_browse.py` (new),
  `src/dnd_ai/api/knowledge.py` (list endpoint + detail hardening/extension)
- `src/dnd_ai/queries/knowledge.py` (`knower_entity_id`/`allow_public`)
- `src/dnd_ai/queries/bootstrap.py`, `src/dnd_ai/api/local_auth.py`
  (`world_id`/`world_name`, `authorized_parties`)
- `src/dnd_ai/api/relationships.py`, `src/dnd_ai/api/dungeon.py`,
  `src/dnd_ai/api/characters.py` (entity-targeted `campaign.view` deny
  check on the existing detail routes — `characters.py` also covers
  `.../inventory`)
- `src/dnd_ai/api/app.py` (register `world_explorer` router)
- `tests/database/test_api_world_explorer.py`,
  `tests/database/test_api_knowledge_browse.py` (new),
  `tests/database/test_query_bootstrap.py` (world/party-perspective tests),
  `tests/unit/test_api_pagination.py` (new),
  `tests/unit/test_api_app.py` (`InvalidCursorError` contract)
- `tests/factories.py` (`make_entity_knowledge`, `make_public_knowledge`,
  `make_world(name=)`, `make_party_discovery(discovered_at_world_time_id=)`)
- `docs/PHASE13D_BACKEND_READINESS.md` (this section), `docs/PLAN.md`

`portal/`, `foundry-module/`, development seed data, and Phase 12 AI
behavior were not modified.
