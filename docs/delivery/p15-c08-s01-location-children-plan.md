# D/P15-C08-S01 implementation plan: bounded child navigation and search

Owner register rows: [P15-C08](work-register.md#p15-c08), [P15-C08-S01](work-register.md#p15-c08-s01), [P15-C08-S01-T01](work-register.md#p15-c08-s01-t01). Source finding: [R16 — Location hierarchy](work-register.md#r16--location-hierarchy). Sibling plans: [S02 portal navigation](p15-c08-s02-child-navigation-plan.md), [S03 area scalars](p15-c08-s03-area-scalars-plan.md). This plan also holds the C08 checkpoint coordination (§12).

Prepared by Opus, 2026-11-24. **Plan only; T01 not started.**

- Starting SHA: `680629b0e9d8193112c1e6378e74fcd41323cac6`, clean worktree. It is the owner's merge of `origin/main` (the C07 merge `48068a812e66f05530de53cff6b3fb20d267204b`, PR #76) into `phase15/completion`; its tree equals `48068a8`'s, so no fast-forward was needed and no history was rewritten.
- Planning baseline: `680629b0`. Every file, test and reproduction below was inspected or run there.
- C07 bookkeeping is a separate documentation commit before this plan. The implementation baseline for T01 is the commit that adds the three C08 plans (reported in the handoff).
- CI: no run exists for C08.

## 1. Entry readiness

- C08 ("Browse places and author dungeon areas") is admitted with no checkpoint prerequisite ("—"). Its criteria send browser keyboard, narrow layout and authorized navigation to [browser](work-register.md#browser).
- C08 has three slices with one task each:
  - **S01-T01** (this plan): authorized child reads with stable cursors, hidden-chain truncation and cross-world tests. Backend.
  - **S02-T01**: portal child search and containment return with permission-loss tests. Its register prerequisite is "S01 independently reviewed".
  - **S03-T01**: dungeon-area summary, size and environment on the add-area form. No slice prerequisite.
- S01 and S03 need only the checkpoint entry criteria, which hold. Table order is not used as a dependency.
- The crosswalk row "P15-C08 · Session preparation links" is a **previous unadopted proposal ID** that maps to [prep-links](work-register.md#prep-links) ("Proposal only"). It is not this checkpoint and nothing here admits it.
- Current C08 derives from the previous register's P15-C07-S02-T01 (R16, location hierarchy browsing) and P15-C05-S04-T03 (R09 dungeon-area scalar fields).
- The open reliability investigations on the C04, C06 and C07 rows are separate obligations before `p15-integration`. They are not C08 prerequisites, and nothing here depends on their causes.
- No owner decision blocks S01.

## 2. Verified current behavior

### 2.1 How places are read today

- **Detail.** `GET /campaigns/{campaign_id}/world/locations/{location_id}` (`api/world_explorer.py`, `get_location_endpoint`, backed by `queries/world_explorer.py`, `get_location_view`) requires `campaign.view`. It returns one place, its subtype fields, its timeline state and `breadcrumbs`, the ancestors from the root to the immediate parent.
  - The ancestor walk stops at the first ancestor in the caller's denied set. That denied set is the grant denies plus `lifecycle_hidden_entity_ids(mode="reference")`.
  - `parent_location_id` is `null` when the parent is denied. This is the existing **hidden-chain truncation**.
- **Errors.** A nonexistent place, a place in another world and a denied place all raise `WorldResourceNotFoundError`. That gives the same 404 `not_found` answer for all three.
- **Search.** `GET …/world/search` lists visible entities in keyset pages ordered by `(lower(left(canonical_name, 200)), entity_id)`. Visibility uses grant denies plus `lifecycle_hidden_entity_ids(mode="browse")`. `include_noncanon` and `include_archived` are honored only for a `canon.edit` holder that also holds `world.canon.read_private`. Search has **no parent filter**.
- **Children.** Nothing returns a place's children. The portal has no way to move down the containment tree except World search over the whole world.
- **Containment guards (unchanged by S01).**
  - `tr_locations_enforce_parent_world` keeps a parent in the same world.
  - `tr_locations_enforce_no_cycle` and the commands' cycle check under the containment lock (`commands/locations.py`) prevent cycles.
  - `_lock_parent` accepts only the authorable non-dungeon categories as parents. Dungeon areas sit only under their dungeon (dungeon commands and triggers).
- **Index.** `ix_locations_parent_location_id` exists.
- **Pagination.** `api/pagination.py` provides `decode_typed_cursor`, `build_page` and keyset-bound cursors. `DEFAULT_PAGE_SIZE` is 25 and `MAX_PAGE_SIZE` is 100.

### 2.2 Plan-entry reproduction results

A temporary pytest module reused the `test_api_world_explorer.py` fixture at `680629b0`, ran once and was deleted. It covered a region "Amber Reach" with a settlement child "Brasshollow", plus an unrelated region "Forbidden March" with a building child.

| Case | Kind | Observation |
|---|---|---|
| R1 | defect | `GET …/world/locations/{region}/children` returns 404 `not_found` for both the GM and the player: no child read exists. |
| R2 | defect | `GET …/world/search?category=location&parent_location_id={region}` returns 200 with all four places (`Amber Reach`, `Brasshollow`, `Cindergate Watchtower`, `Forbidden March`), so the unknown parameter is ignored. Only `Brasshollow` is a child. |
| R3 | defect | The location detail body has no children field. Its keys are `alarm_level, authoring, breadcrumbs, building_use, canon_status, condition_notes, danger_level, is_destroyed, is_searched, lifecycle_status, location_id, location_type_code, name, parent_location_id, population, summary, superseded_by`. |

### 2.3 Deviations S01 repairs

- **DV-1:** no authorized, bounded read of a place's children exists.
- **DV-2:** no search is limited to the places reachable below a place.

### 2.4 Source-inspected risks (not reproduced; covered by cases below)

- **Hidden-chain leak.** A naive recursive search would return C under a hidden B when searching from A, and that would reveal that a hidden link exists (A1–A5).
- **Hidden rows counted before paging.** Filtering after `LIMIT` would make short pages and leak counts (A8).
- **Reference versus browse visibility.** Treating the parent with browse rules would refuse an archived parent that its own detail route still shows (A4).

### 2.5 Behavior that must not regress (baseline-passing guards)

- `test_api_world_explorer.py`, all 48 tests, in particular `test_an_inaccessible_parent_is_omitted_from_breadcrumbs`, `test_nonexistent_and_cross_world_details_return_identical_safe_errors` and the search paging and cursor tests.
- `test_world_explorer_canon_visibility.py`.
- The containment and reparent tests in `test_api_location_authoring.py` (parent assignment, self parent, two- and three-hop cycles, unusable parents, parent options) and `test_locations.py`.
- The reparent and archive races in `test_content_authoring_concurrency.py`.
- `test_api_dungeon.py` and `test_api_dungeon_authoring.py`.

None of these files changes in S01.

## 3. Outcome, scope and exclusions

### 3.1 User outcome

Anyone who can see a place can ask for the places directly inside it, a page at a time. They can also search the places below it by name or summary. Only places the caller is entitled to see appear, and the answer gives no name, ID or count of anything hidden.

### 3.2 In scope (T01)

New read: **`GET /campaigns/{campaign_id}/world/locations/{location_id}/children`**, requiring `campaign.view`.

- **Query parameters.**
  - `q`: optional, at most 200 characters, the same bound as search.
  - `limit`: 1 to 100, default 25.
  - `cursor`: optional.
  - `include_noncanon` and `include_archived`: default false. Honored exactly as in `/world/search`: only for `canon.edit` plus `world.canon.read_private`, and otherwise silently ignored.
- **Parent check.** The parent must pass the detail route's own test: it must be in the caller's timeline world and not in the reference-mode denied set (`_campaign_view_denied_entity_ids`). Otherwise raise `WorldResourceNotFoundError`, which gives the same 404 as the detail route.
- **Visibility of listed places.** A place is visible when it is in the caller's world and not in the browse denied set: grant denies plus `lifecycle_hidden_entity_ids(mode="browse", include_noncanon, include_archived)`, the same set `/world/search` uses.
- **Without `q` (or with an empty `q`).** Return the visible direct children of the parent.
- **With `q`.** Return the visible places reachable from the parent through visible places only (hidden-chain truncation) whose name or summary contains `q`, case-insensitively, with LIKE metacharacters escaped as search does.
  - Traversal never enters a hidden place, so nothing below it is reached through it.
  - A defensive depth bound of 64 levels applies (`_MAX_CHILD_DEPTH`). Cycles are already impossible under the triggers.
- **Order and cursor.** Order by `(lower(left(canonical_name, 200)), location_id)`, the same total order as search. The keyset is `world_location_children`, with fields `("str", "uuid")`.
  - All filtering happens in SQL before `LIMIT limit + 1`.
  - `build_page` produces `next_cursor`.
- **Response.** `{ items, next_cursor }`. Each item has these fields:
  - `location_id`, `name`, `location_type_code`, `summary`, `canon_status`, `lifecycle_status`;
  - `path`: the visible intermediate places between the parent (excluded) and the item (excluded), from top to bottom. Each entry is `{location_id, name, location_type_code}`. It is empty for direct children.

  There are no totals and no child counts or "has children" flags.
- **Implementation locations.**
  - The new query function `list_location_children` goes in `queries/world_explorer.py`, as one recursive CTE that is limited to depth 1 when `q` is absent.
  - The page's path names come from one bounded follow-up query.
  - The route and response models go in `api/world_explorer.py`.
- **Documentation.**
  - The endpoint row and a short rule note in `docs/api/READ_API.md`, in the endpoint matrix and in the locations bullet that names `/world/locations/{id}`.
  - The operation row in `docs/api/world-and-authoring.md`. `scripts/check_documentation.py` requires exactly one catalog row per route.

### 3.3 Exclusions

- No change to the existing search, counts or detail routes, `lifecycle_hidden_entity_ids`, or the location and dungeon commands and triggers.
- No schema, migration, capability or authorization-plan change.
- No portal change; S02 owns it. No dungeon-area structural children: features, hazards, interactables and connections stay on `/dungeon-areas/{id}`.
- No totals, child counts or "has children" indicators. Aliases (`core.entity_names`) are not searched, as in search.
- No reparenting UI or change. R16's "reuse existing reparent commands" is satisfied by leaving them untouched.
- No caching or materialized hierarchy.

## 4. Affected files and interfaces

| File | Change |
|---|---|
| `src/dnd_ai/queries/world_explorer.py` | `LOCATION_CHILDREN_KEYSET`, `_MAX_CHILD_DEPTH`, dataclasses `LocationChildCard` and `LocationPathCrumb` (or reuse `LocationCrumb`), and `list_location_children(...)` |
| `src/dnd_ai/api/world_explorer.py` | The route, `LocationChildResponse` and `LocationChildrenResponse`. Visibility comes from the existing helpers (`_campaign_view_denied_entity_ids`, `_grant_denied_entity_ids`, `lifecycle_hidden_entity_ids`). |
| `tests/database/test_api_location_children.py` | New: A1–A16 |
| `docs/api/READ_API.md` | Endpoint matrix row and rule note |
| `docs/api/world-and-authoring.md` | Catalog row `GET /campaigns/{campaign_id}/world/locations/{location_id}/children` → 200 LocationChildrenResponse, campaign.view |

The portal-facing contract that S02 consumes is §3.2's response shape. A change to it after S01's review is a reason to revalidate S02 (§12.3).

## 5. Task commit

One commit: `P15-C08-S01-T01: add authorized location child reads with stable cursors and hidden-chain truncation`. A records commit follows (docs only).

## 6. Acceptance cases

All cases are database API tests in the new file, built on their own fixture: a world, a second world, a campaign with a GM role (`campaign.view` and `canon.edit`, plus world authoring for read-private), a player role (`campaign.view`), a capless member and an outsider.

Every case that expects a refusal also asserts a **positive control in the same test**: a visible parent returns 200 with its expected items. This matters because at baseline the missing route already answers 404 `not_found`, so a refusal-only test would pass for the wrong reason. A test whose only assertion is a 404 is not acceptable.

| Case | Behavior | Baseline |
|---|---|---|
| A1 | Direct children only: a region with three settlements and one grandchild lists the three settlements, not the grandchild, in `(name prefix, id)` order. The same holds for the GM and the player. | fails |
| A2 | A targeted `campaign.view` deny on one child hides it from that player only. Its ID and name appear nowhere in the player's body, while the GM still sees it. | fails |
| A3 | Lifecycle, in four parts:<br>(a) a draft child is hidden from the player;<br>(b) the GM with read-private sees it only with `include_noncanon=true`;<br>(c) a GM of another campaign on the same world, without read-private, does not see it even with the flag;<br>(d) an archived child is hidden by default and shown to the GM with `include_archived=true`. | fails |
| A4 | Parent refusals:<br>- a nonexistent parent, a parent in the other world and a parent denied to the player all give 404 with a byte-identical body apart from `correlation_id`, matching the detail route's answer for the same IDs;<br>- an archived parent that the detail route still shows to the player (reference mode) returns 200 for children;<br>- positive control included. | fails |
| A5 | Hidden-chain truncation, using A → B → C, where B is denied to the player and C's name matches `q`:<br>- the player's search from A returns neither B nor C;<br>- the GM's search returns C with `path == [B]`;<br>- the player's children of C (opened directly) still work;<br>- the existing breadcrumb truncation for C is unchanged. | fails |
| A6 | Deep path: a six-level chain, searched from the top with a `q` matching only the leaf, returns the leaf with its four intermediates in top-to-bottom order. | fails |
| A7 | Deterministic paging:<br>- seven children, including two with equal names, walked with `limit=2`, return each child exactly once in order;<br>- repeating the same request returns the same page;<br>- a cursor of another keyset (`world_entities`), a malformed cursor, `limit=0`, `limit=101` and a `q` of 201 characters each return 422. | fails |
| A8 | Filter before paging: with hidden children interleaved by name, every page except the last has exactly `limit` items, no page contains a hidden ID, and the page count equals ceil(visible / limit). | fails |
| A9 | Personas and authority loss:<br>- a non-member gets 404 and a capless member gets the detail route's answer (403);<br>- a player whose membership is removed between pages gets the non-member answer (404) when reusing the earlier cursor, with nothing listed;<br>- positive control first. | fails |
| A10 | Cross-world: a `q` matching only the other world's places returns nothing, and none of their IDs appear. | fails |
| A11 | Search text: `q` with `%` and `_` matches them literally, and case is ignored. | fails |
| A12 | Shape:<br>- the response keys are exactly `items` and `next_cursor`;<br>- the item keys are exactly §3.2's;<br>- no count field exists. | fails |
| A13 | Dungeon: a dungeon's children are its areas under the same rules (a draft area is hidden from the player, a published one listed), and an area's structural children never appear. | fails |
| A14 | Navigation and search agree: for the player and the GM, every item a search from A returns is reachable by successive direct-children listings from A. | fails |
| A15 | Concurrent change between pages: a child not yet listed is reparented elsewhere before page 2, so page 2 omits it and repeats nothing already returned. | fails |
| A16 | Regression guards: §2.5 files unchanged and passing. | guard |

"Fails" means the case fails at the baseline because the route does not exist; record each failure (test name and assertion). A16 is not expected to fail first.

### 6.1 Mutation probes (Sonnet runs; the reviewer re-runs)

| Probe | Mutation | Must fail |
|---|---|---|
| M1 | Remove the visibility predicate from the recursive step | A5, A14 |
| M2 | Remove the visibility predicate from the base step | A2, A3, A8 |
| M3 | Skip the parent's world check | A4, A10 |
| M4 | Order by the name prefix only, dropping the ID | A7 |
| M5 | Use `>=` instead of `>` in the keyset comparison | A7 |
| M6 | Honor `include_noncanon` without the read-private gate | A3 |
| M7 | Check the parent against the browse set instead of the reference set | A4 |
| M8 | Return an empty `path` for every item | A5, A6 |

Revert each probe and restore exact bytes. Compare hashes, because `git restore` rewrites LF working files as CRLF under `core.autocrlf=true`.

## 7. Verification

### 7.1 Per-commit checks (Sonnet; repeated by the reviewer)

Against the local PostgreSQL 18 server with `.env`:

1. Focused run: `uv run pytest tests/database/test_api_location_children.py tests/database/test_api_world_explorer.py tests/database/test_world_explorer_canon_visibility.py tests/database/test_api_location_authoring.py tests/database/test_locations.py tests/database/test_content_authoring_concurrency.py tests/database/test_api_dungeon.py tests/database/test_api_dungeon_authoring.py`.
2. `uv run ruff format --check`, `uv run ruff check`, `uv run mypy src`, `uv lock --check`, `uv run alembic check` (no migration is expected).
3. Full backend suite: `uv run python scripts/run_sharded_tests.py`.
   - Record the first run and any rerun separately, naming each failing test.
   - A failure matching an open investigation (C04, C06 or C07 rows) is recorded as such, without claiming its cause.
4. From the repository root: `uv run python scripts/check_documentation.py` and `git diff --check`.

A portal run is not required for S01, because no portal file changes.

### 7.2 C08 checkpoint merge requirements

See §12.4. S01's verdict alone does not satisfy them.

## 8. Authorization, disclosure, concurrency and isolation

- **Server-authoritative.** Every request re-resolves the caller's access. Nothing is cached between pages, and a cursor grants nothing: it only positions within the already-filtered set.
- **Disclosure.** Hidden places are removed in SQL before ordering and `LIMIT`.
  - No totals or child indicators exist.
  - A path contains only places the traversal entered, which are visible by construction.
  - An unauthorized parent gives the detail route's indistinguishable 404.
- **Account and resource isolation.**
  - The world comes from the caller's campaign timeline (`timeline_world_id`), never from the request.
  - Places of another world are never traversed. A parent there is 404.
  - Campaign grants of another campaign do not apply. `AccessContext` is per campaign.
- **Late responses.** The server returns the answer for the access in force at that request. A cursor reused after access changes is evaluated under the new access (A9). Ownership of late answers on the client belongs to S02.
- **Concurrency.** This is a read under the request transaction. The keyset's strict total order never repeats a row, and a place moved during paging is simply present or absent on later pages (A15). Reparent safety stays with the existing locks and triggers (A16).
- **Outcomes.** Reads only: no idempotency key, no audit row, no pending or unknown write outcome, and no retry identity. A failed read is repeated as a read.

## 9. Intermediate states

T01 adds an API with no portal consumer until S02. That is acceptable as an intermediate commit on `phase15/completion`, because nothing renders it. C08 merges as one checkpoint PR (§12.4). No slice is merged alone.

## 10. Decisions

**No owner decision is required.** Routine choices made here:

- **R-1 (one route, two modes).** Without `q`: direct children. With `q`: visible descendants. R16 asks for both "child navigation/search" and "deep paths". One contract keeps their visibility identical (A14).
- **R-2 (descendant search follows only visible places).** This is the plan's reading of R16's "preserve hidden-chain truncation": search reaches exactly what successive navigation could reach.
- **R-3 (browse visibility for listed places, reference visibility for the parent).** Listing matches `/world/search`, so an archived child is hidden unless an editor asks. Opening the parent matches its detail route.
- **R-4 (search's order, `q` bound and preview flags).** No new ordering or flag semantics.
- **R-5 (no counts or "has children").** The criteria exclude hidden counts. An authorized count would need its own review, and paging does not need it.
- **R-6 (a cursor is not bound to the parent or `q`).** As with search, a cursor only positions within the current filtered set and discloses nothing when reused elsewhere.
- **R-7 (depth bound 64).** This is defensive only. A place deeper than 64 levels below the searched place is not returned by search, but is still reachable by navigation. This limit is documented in READ_API.
- **R-8 (a dungeon's areas are its children).** Areas are places already visible through search under the same rules, so including them adds no disclosure.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Confirm the baseline is HEAD and `origin/phase15/completion`, with a clean worktree. The baseline is the commit that adds this plan, given in the handoff prompt.
2. Read §2 to §10.
3. Write A1–A15 first and run them on the baseline. Record each failure (test name and assertion). Run A16's files and record that they pass.
4. Implement §3.2 in the files of §4 only.
5. Run §7.1. Run M1–M8, record each probe's failing cases, and revert each probe with exact bytes restored.
6. **Stop and report instead of continuing if:**
   - a schema, migration, command, trigger, capability or authorization-plan change seems necessary;
   - an existing search, counts or detail route, `lifecycle_hidden_entity_ids` or the pagination helpers would need to change;
   - any §2.5 test would need a changed expectation;
   - hidden places cannot be excluded in SQL before `LIMIT`, or the read would need to load a world's places into Python;
   - a refusal case cannot be given a positive control that fails at baseline;
   - the documentation check rejects the catalog row.
7. Commit with the §5 subject and push. Record the following in §11.3 and the register's S01-T01 row, then commit and push the records:
   - the SHA;
   - the test-first failures and guard results;
   - the focused run;
   - the full shard run (first run and reruns separately);
   - the other checks;
   - the probes;
   - the CI position: "pending checkpoint PR".
8. Do not open, mark ready or merge a PR. Do not start S02, run browser or AX checks, start consumers, or record any acceptance.

### 11.2 Independent review boundary

- **T01 = combined S01:** from the plan commit to the T01 implementation commit, plus its docs-only records commit.
- Review against §2.5, §3, §6 and §8, and re-run §7.1 (a focused run is required; repeat the shard run if the implementer's was not clean) and M1–M8.
- Confirm the contract in §3.2 exactly, because S02 depends on it.
- A pass is a slice verdict only; §12.4 remains. A pass makes S02 eligible.

### 11.3 Implementation record

Sonnet, 2026-11-24. Baseline `12cc87d626f5e74f4cb9f0ef26b06d765ee8f0c5` (confirmed as HEAD and `origin/phase15/completion`, clean worktree). Implementation commit `1f0164481a32fce50f48375752f7d29eb2cee53f`: `P15-C08-S01-T01: add authorized location child reads with stable cursors and hidden-chain truncation`. Review range: `12cc87d626f5e74f4cb9f0ef26b06d765ee8f0c5..1f0164481a32fce50f48375752f7d29eb2cee53f`, plus this records commit.

**Change.** `queries/world_explorer.py`: `LOCATION_CHILDREN_KEYSET`, `_MAX_CHILD_DEPTH` (64), `LocationChildCard` (reusing `LocationCrumb`) and `list_location_children`: the parent check (reference-mode denied set and the caller's world, otherwise `WorldResourceNotFoundError`), then one recursive CTE that is depth 1 without `q`, filters hidden places in both the base and the recursive step, then applies the text filter, the keyset condition, the order `(lower(left(name, 200)), location_id)` and `LIMIT limit + 1`; one bounded follow-up query names the path entries. `api/world_explorer.py`: the route, `LocationChildResponse` and `LocationChildrenResponse` (the parent test uses `_campaign_view_denied_entity_ids`; listed places use the grant denies plus `lifecycle_hidden_entity_ids(mode="browse", ...)`, as `/world/search` does). `docs/api/READ_API.md` (matrix row, rule note, category-coverage row) and `docs/api/world-and-authoring.md` (catalog row). No schema, migration, command, trigger, capability, existing route, `lifecycle_hidden_entity_ids` or pagination-helper change.

**Deviation from §4's file list (disclosed).** `tests/scenario/test_phase15_acceptance_guards.py` pins the number of member-read routes (`EXPECTED_MEMBER_READS`, "adding or removing a route ... forces a conscious update"); the new route is a member read, so the pin went from 34 to 35 (a one-line change with a comment, as P15-C02-S03 did for its read). Shard run 1 found this (below). It is not one of the §2.5 files and no expectation was weakened.

**Test-first (baseline `12cc87d626f5e74f4cb9f0ef26b06d765ee8f0c5`, route absent).** All 15 new tests (A1-A15, one test per case in `tests/database/test_api_location_children.py`) failed: each at its first call to the missing route: `404 not_found` where 200 was expected (`assert 404 == 200` or the helper's status assertion), `KeyError: 'items'` on the 404 body, or, for A12, `assert {'error'} == {'items', 'next_cursor'}`. Fixture setup completed in every case, so no failure is a fixture error. A16 guards (`test_api_world_explorer.py`, `test_world_explorer_canon_visibility.py`, `test_api_location_authoring.py`, `test_locations.py`, `test_content_authoring_concurrency.py`, `test_api_dungeon.py`, `test_api_dungeon_authoring.py`): 200 passed on the baseline.

**After the change.** Focused §7.1 set (8 files): 215 passed (15 new + 200 guards), taken before the later test edits below; after them the new file alone passes (15) and the acceptance guard file passes (30 with it).

**Full shard runs (reported separately).**
1. First run (before the pin and test edits): 11,354 passed, 6 skipped, **2 failed**, both in `tests/scenario/test_phase15_acceptance_guards.py` (`test_the_manifest_covers_every_phase15_family_and_its_size_is_pinned`, `test_player_safe_reads_are_not_refused_to_a_player_and_not_found_by_an_outsider`), each `assert 35 == 34` on the member-read pin. Neither matches an open investigation. After the pin edit, that file passed (with the new tests, 30 passed).
2. Second run, on the final code: **11,356 passed, 6 skipped, 0 failed** (11,362 collected and executed; shards 3,018 + 2,188 + 2,781 + 3,369 passed). Between the runs the pin changed, and two test-only edits were made (below).

**Test edits after run 1, from the probes.** A7 now uses six equal names (11 children, pages 2/2/2/2/2/1) so the id tie-break is observable (with two equal names, insertion order matched id order half the time); A5 gained a hidden place below a visible one (Gate, Hidden Stair, Cellar), because M1 failed only A14 on its first run (the plan names A5 and A14), since the original A5 chain hid its place at depth 1.

**Other checks.** `ruff format --check`, `ruff check`, `mypy src`, `uv lock --check` and `alembic -c database/alembic.ini check` ("No new upgrade operations detected"; the plain `alembic check` has no `script_location`) pass, as do `scripts/check_documentation.py` and `git diff --check`.

**Probes (each restored byte-for-byte; SHA-256 compared equal after every probe).**

| Probe | Failed cases |
|---|---|
| M1 | A5, A14 (first run, before the A5 addition: A14 only) |
| M2 | A2, A3, A5, A8, A13, A14 |
| M3 | A4, A10 |
| M4 | A7 |
| M5 | A7, A8, A14, A15 |
| M6 | A3 |
| M7 | A4 |
| M8 | A5, A6, A12 |

The first M4 mutation did not apply (a line-ending mismatch in the probe script: `queries/world_explorer.py` is CRLF in the working copy); the script was corrected and M4 redone.

**CI position.** Pending checkpoint PR; none opened. Not run: browser/AX, human review, owner acceptance, S02, S03, consumers. A portal run was not required (no portal file changed).

## 12. C08 checkpoint coordination

### 12.1 Slices, tasks and how they fit

| Task | Layer | Outcome | Plan |
|---|---|---|---|
| S01-T01 | API + database tests | Authorized child read and search (this plan) | here |
| S02-T01 | Portal | Places-within panel with search and paging; containment path links; permission loss and late answers | [S02 plan](p15-c08-s02-child-navigation-plan.md) |
| S03-T01 | Portal + backend guard tests | Summary, size and environment on the add-area form | [S03 plan](p15-c08-s03-area-scalars-plan.md) |

S02 is the only consumer of S01. S03 is independent of both: it uses the existing area commands and touches no file S01 touches.

### 12.2 Shared files

| File | S01 | S02 | S03 |
|---|---|---|---|
| `portal/src/components/world/WorldRecordWorkspace.test.tsx` | — | optional default children handler | new and adapted add-area cases |
| `docs/reference/portal-behavior.md` | — | place reader and workspace rows | dungeon authoring row |
| `docs/delivery/work-register.md` | records | records | records |

No production source file is shared.

### 12.3 Implementation order and baselines

1. **S01-T01** from the plan commit.
2. **S03-T01** after S01-T01's records commit. Revalidate that S03's §2 facts still hold at that recorded head before writing tests. S03 does not wait for S01's review.
3. **S01 independent review.** It may run in parallel with step 2. It must reach a pass, with any correction confirmed.
4. **S02-T01** only after both:
   - S01 has an independent pass recorded in this plan and the register;
   - S03-T01's records commit exists.

   S02's implementer revalidates S01's reviewed contract and S03's test-file state at the then-current head before writing tests (S02 plan §11.1).

No future SHA is named here. Each task records its own head.

### 12.4 C08 checkpoint merge requirements

The C08 PR merges only when all of these hold:

1. S01, S02 and S03 have each passed independent review, with every correction confirmed.
2. S01's A1–A16, S02's N1–N19 and S03's D1–D13 pass on the integration head.
3. On the integration head's executable code:
   - one full portal run (`npm test`), plus lint, `tsc -b` and build;
   - one full backend shard run, plus `ruff format --check`, `ruff check`, `mypy src`, `uv lock --check` and `alembic check`;
   - the documentation and diff checks.

   A run may be reused when no executable or test file changed after it.
4. CI passes on the exact integration head.

Merge, browser verification and owner acceptance are separate events with separate evidence (register sequencing rules).

### 12.5 Separate events (after the merge; not merge gates)

- [browser](work-register.md#browser), per C08's criteria: keyboard reach of the panel, search, links and Show more; narrow layout at 320 CSS px; authorized navigation down and back up with player and GM personas.
- [ax](work-register.md#ax): screen-reader output of the status messages, actual 200% and 400% zoom, and the add-area form's layout.
- Human review, [p15-integration](work-register.md#p15-integration) and `p15-owner`. Nothing in these plans grants them.
