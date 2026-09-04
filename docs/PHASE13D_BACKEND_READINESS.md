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
| Quests | `GET /campaigns/{id}/quests` (new), `GET /campaigns/{id}/quests/{id}` | `dnd_ai.queries.quest.list_campaign_quests` (new), `.get_quest_view` | Yes, after this workstream. Detail already existed; the list was the missing piece — see §4. |
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
already correctly audience-filtered, but nothing could produce the
`quest_id` to call it with — the portal's Home dashboard ("active quests")
and a Quests screen both need a list.

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

## 5. Files changed

- `src/dnd_ai/queries/session.py` (new)
- `src/dnd_ai/api/sessions.py` (list/detail routes added; docstring updated)
- `src/dnd_ai/queries/quest.py` (`list_campaign_quests` added, then
  corrected per §4.2: `include_all_parties`/`denied_quest_ids`)
- `src/dnd_ai/api/quests.py` (list route added; detail route hardened with
  a quest-scoped `campaign.view` check; docstrings updated)
- `tests/database/test_api_sessions_query.py` (new)
- `tests/database/test_api_quests_list.py` (new, then extended per §4.2)
- `tests/database/test_api_quests_query.py` (extended per §4.2: the
  detail-route `campaign.view` deny regression)
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

1. **World explorer backend (§3)** — needs a pagination/list convention
   decided once, then list+search endpoints for locations, characters/
   NPCs, organizations, items, and events. Recommend scoping as its own
   phase rather than folding into 13D readiness.
2. **Knowledge screen's six views (§3)** — needs the per-view
   audience/filter semantics decided (what "recently discovered" means,
   whether "sources" is a distinct query or a field on existing knowledge
   items) before any list endpoint can be built correctly.
3. **Item/artifact detail-by-id** — no route exists for a loose world item
   not currently held by any character. Small in isolation, but only
   useful once World explorer's list/search exists to link into it.
4. **Session detail's participants/locations-visited/encounter and
   character-state-change sections (§3)** — deferred; each needs its own
   join/audience-filtering design against `narrative.event_participants`/
   `.event_locations` and the `campaign.character_state`/`_conditions`/
   `_resources` history.
