# D/P15-C11-S01 implementation plan: store and resolve control assignments

Owner register rows: [P15-C11](work-register.md#p15-c11), [P15-C11-S01](work-register.md#p15-c11-s01), [P15-C11-S01-T01](work-register.md#p15-c11-s01-t01), [P15-C11-S01-T02](work-register.md#p15-c11-s01-t02). Governing contract: [ADR 0021](../adr/0021-shared-actor-identity-control-and-authoring-responsibility.md) §2.1–§2.6, §2.9–§2.10 (owner-accepted, [adr21](work-register.md#adr21)); decisions OD-2 and OD-14; tests T2, T3, T5 (resolution part) and T25 (index replacement, clock boundaries, no branch inheritance) in [rules foundations §8](rules-foundations.md). The companion slice is [S02](p15-c11-s02-control-changes-plan.md). Checkpoint coordination for both slices is in [section 12](#12-c11-checkpoint-coordination).

Prepared by Opus, 2026-11-25. **Planned; not implemented.**

- Starting SHA: `dabd7d1ab92a1575eb3769e539074ccbab34de8e`, the reviewed C10 PR head, with a clean worktree.
- Plan-entry head: `ebe6c7241a581cff1e2fac265a3af9230c656fa1`, the C10 merge (PR #79), reached by fast-forward. Its tree equals `dabd7d1`'s; no history was rewritten.
- C10 merge bookkeeping is a separate documentation commit, `b0d314210d3dc216a8cdfa3ba57727f79485cb7a`, before this plan.
- The S01-T01 baseline is the commit that adds this plan (reported in the handoff). T02's baseline is T01's records commit.
- CI: no run exists for C11.

## 1. Entry readiness and scope

**Checkpoint entry.** C11's prerequisites are [adr21](work-register.md#adr21) approved contract (owner accepted 2ca4648, 2026-11-06) and [r01](work-register.md#r01) owner accepted (f21fb23). Both hold. S01 has no slice-specific gate. S02's prerequisite, "S01 independently reviewed", is a real prerequisite, not a scheduling preference (section 12.1).

**Scope.** This is the storage and resolution half of P03-B control (register criteria: "Preserve legacy relationship rights. Both controllers receive the accepted bounded rights. Exclude assignment rows from the legacy resolver before exposing a writer.").

- **T01:** the assignment columns, derived and denormalized values, invariants and the replaced and new unique indexes on `security.membership_character_relationships`, with retained-data migration tests.
- **T02:** the closed `CONTROL_ASSIGNMENT_CAPABILITIES` matrix, an in-effect rule driven by the effective campaign clock inside the single authority statement, and every production reader of the table made to exclude assignment rows from the legacy path or to treat them by the assignment rule.

**Outside S01 and C11.**
- Writers: assign, replace and revoke are S02-T01; the OD-4a delegation is S02-T02. No route, command or seed in S01 creates an assignment row; only tests do.
- Player-profile reading and editing through control: [P15-C12](work-register.md#p15-c12) and [profile-authority](work-register.md#profile-authority).
- Controller operations, `lock_controller_operation_scope` and named intents: [P15-C20](work-register.md#p15-c20), after [g4-live](work-register.md#g4-live).
- Legacy-row retirement and the P03-C manifest: [P15-C13](work-register.md#p15-c13) and [character-manifest](work-register.md#character-manifest).
- Portal and other consumers: they use B's accepted scope ([actor-b](work-register.md#actor-b)).

## 2. Current behavior (at `ebe6c72`)

### 2.1 Source facts

| Concern | Today (source) |
|---|---|
| Table | `security.membership_character_relationships` (`persistence/tables/security.py:515`; migration `080_security_identity_and_access.py:~830-1018`). No `is_control_assignment`, `campaign_id`, `is_primary`, `assignment_period_kind`, `revoked_by_membership_id` or `revocation_reason` column. Alembic head `149_reservation_fk_deferrable`. |
| Scope trigger | `security.enforce_membership_character_relationship_scope()` (080:906), `BEFORE INSERT OR UPDATE` (080:1016): same-world character and timeline, same-campaign `granted_by_membership_id`, and `effective_period := NULL` when no start, else `[from, to)` over world-time `sort_key`s. |
| Uniqueness | `ux_membership_character_relationships_active_type` on `(campaign_membership_id, character_id, character_relationship_type_id) WHERE revoked_at IS NULL` (080:898). Nothing limits primaries per campaign. R01 plans name this index in `UniqueWait` declarations (`access_grant_plans.py:340,355`; `membership_end_plans.py:469`). |
| Legacy resolver | `rels` CTE in `_ACCESS_CTES` (`domain/access.py:~1105-1135`): unrevoked, unexpired, `effective_to_world_time_id IS NULL`, timeline unset or the campaign's, type active, character active and canon. `_access_context_from_row` (`access.py:1626`) keeps a row's capability only if `BUILTIN_RELATIONSHIP_CAPABILITIES` (`access.py:169`) permits it. The whole decision is one statement (`read_authority_snapshot`, `access.py:1513`). |
| In-statement clock | `_PERSPECTIVE_CTES` (`access.py:1363`) already resolves the effective clock in SQL exactly as `queries/campaign_clock.resolve_effective_clock` does (own clock row, else the parent's bounded at the branch point, recursively). It is opt-in (`with_perspective`). |
| Capability consumers | `has_capability(..., character_id=)` adds `character_capabilities[character_id]` to the baseline (`access.py:~420`). `api/world_explorer.py:116` discovers characters from `set(access.character_capabilities)`. `queries/bootstrap.py:377` offers a perspective only for `character.view_knowledge`. No route checks `character.control`, `character.edit_mechanical_state`, `character.view_player_profile` or `character.edit_player_profile`; the last two codes do not exist. |
| Other readers of the table | `api/parties.py:176` (D4-C party roster: legacy `owner`/`primary_controller`/`co_controller`; its comment and [shared-characters §10.13](shared-characters.md) say an in-effect assignment qualifies after P03-B); `queries/access_overview.py:350` (Sharing panel member relationships, with change and revoke actions in the portal); `queries/effective_access.py:152` (explanations; "the panel must not show a source the resolver would not honour"); `queries/content_preconditions.py:186` (archive block, open-end rule); `queries/audit_history.py:372` (joins by relationship command names); `commands/access_grants.py:752,901` and `commands/access_grant_plans.py:1022,1238` (legacy change and revoke, by row id); `commands/memberships.py:1387` and `membership_end_plans.py` (membership end revokes every unrevoked row of the membership); `commands/entity_lifecycle.py:241` (physical-delete blocking). |
| Archive serialization | `archive_entity` locks the entity `FOR UPDATE` before `archive_blocked_reason` (`entity_lifecycle.py:~795-810`). |

### 2.2 Plan-entry reproduction results

A temporary database test (`tests/database/test_c11_repro_tmp.py`, run once against the local PostgreSQL 18 server at `ebe6c72`, then deleted; 5 passed) logged:

| ID | Finding | Kind |
|---|---|---|
| R1 | Two live `primary_controller` rows for two memberships on the same character in one campaign both insert (`live primaries in one campaign: 2`). | **Demonstrated gap** against ADR 0021 §2.3 (at most one live primary per campaign and character). Legacy rows keep this behavior; the new index applies to assignment rows only. |
| R2 | A legacy `primary_controller` row confers `discover`, `view_summary`, `view_full`, `view_inventory`, `view_knowledge` and `view_private`, and not `character.control`. | **Guard** (legacy rights preserved). |
| R3 | A legacy row with a start world time after any clock, on a campaign with no clock, still confers its capabilities (open-end rule, no clock). | **Guard** (ADR §2.4 item 6: legacy semantics unchanged). |
| R4 | The access overview lists a live legacy primary row; `archive_blocked_reason` returns no block when the only unrevoked row has a closed period. | **Guard** for the overview; the archive result is the baseline that T02 changes for dated assignment rows. |
| R5 | None of the six assignment columns and no `character.assign_control` capability exist. | Baseline fact. |

Source-inspected only (not reproduced): an undated assignment-shaped row would be indistinguishable from a legacy row to every reader in section 2.1 and would confer `view_private` and `view_knowledge`; membership end revokes every unrevoked row of the membership regardless of type; archive and an assignment writer would serialize on the entity row.

## 3. Changes

### 3.1 T01: storage, invariants and uniqueness

Migration `150_control_assignments` (revalidate the next free revision at start), additive, one transaction:

1. **Columns** (ADR §2.2):
   - `is_control_assignment BOOLEAN NOT NULL DEFAULT false`;
   - `campaign_id UUID`, backfilled from each row's membership, then `NOT NULL`, `REFERENCES campaign.campaigns(campaign_id)`, immutable (`core.enforce_immutable_columns`, revision 030);
   - `is_primary BOOLEAN NOT NULL DEFAULT false`, derived (never client-authoritative);
   - `assignment_period_kind TEXT NULL` with `CHECK (assignment_period_kind IN ('ongoing', 'dated'))` (the CHECK-on-text form of migration 141's `end_reason`);
   - `revoked_by_membership_id UUID NULL REFERENCES security.campaign_memberships ON DELETE SET NULL` and `revocation_reason TEXT NULL` (`CHECK (revocation_reason IS NULL OR char_length(revocation_reason) BETWEEN 1 AND 1000)`);
   - `is_control_assignment` and `assignment_period_kind` immutable after insert.
2. **Trigger** (`CREATE OR REPLACE` of the scope function, keeping every existing check):
   - set `campaign_id` from the membership when NULL; refuse a supplied value that differs;
   - set `is_primary := (type code = 'primary_controller')`;
   - when `is_control_assignment`, refuse a type other than `primary_controller` or `co_controller`;
   - refuse a `revoked_by_membership_id` of another campaign.
   Existing inserts (`grant_character_relationship`, `change_character_relationship`, factories) keep working unchanged because the trigger fills `campaign_id`.
3. **CHECK constraints** (ADR §2.3; all phrased `NOT is_control_assignment OR …` so legacy rows are untouched):
   - kind present exactly when an assignment (`is_control_assignment = (assignment_period_kind IS NOT NULL)`);
   - `ongoing` → both world-time endpoints NULL;
   - `dated` → `effective_from_world_time_id` set;
   - assignment → `expires_at IS NULL` and `timeline_id IS NULL`;
   - `revoked_by_membership_id` and `revocation_reason` only on revoked rows. A revoked assignment may have neither (membership end revokes without them).
4. **Indexes:**
   - replace `ux_membership_character_relationships_active_type` with the same columns and predicate `WHERE revoked_at IS NULL AND NOT is_control_assignment`, **keeping the name** (R01 `UniqueWait` declarations reference it);
   - new `ux_membership_character_relationships_live_primary` on `(campaign_id, character_id) WHERE is_control_assignment AND is_primary AND revoked_at IS NULL`;
   - new `ux_membership_character_relationships_live_assignment` on `(campaign_membership_id, character_id) WHERE is_control_assignment AND revoked_at IS NULL`;
   - supporting `ix_…_campaign_id` and partial `ix_…_revoked_by` indexes. Names stay within 63 bytes.
5. **Comments** on every new column, constraint-bearing behavior and index (the schema-comment reconciliation tests require them).
6. **Downgrade:** refuses with a clear error while any `is_control_assignment` row exists. It never deletes them silently and never lets them become legacy rows that would confer `view_private`. Otherwise it restores the exact previous index, trigger body and columns.
7. **Core metadata** (`persistence/tables/security.py`): the same columns, constraints and indexes, so `alembic check` reports no drift.
8. **Documentation:** [DATABASE_MODEL](../architecture/DATABASE_MODEL.md) §19.4 (assignment columns and invariants) and §7.3, and [DOMAIN_MODEL](../DOMAIN_MODEL.md) §8.4. Each marks `character.character_controllers` as retired by ADR 0021 §2.1. [tables.md](../reference/tables.md) gets the new columns and indexes.

T01 changes no resolver and no reader. Between T01 and T02, only tests can create an assignment row (no writer exists until S02).

### 3.2 T02: the dedicated, clock-aware resolver and every reader

1. **Closed matrix** in `domain/access.py`, beside `BUILTIN_RELATIONSHIP_CAPABILITIES`. `CONTROL_ASSIGNMENT_CAPABILITIES: dict[str, frozenset[str]]` has keys `primary_controller` and `co_controller`. Both get the identical set (OD-2), exactly ADR §2.5 item 2:
   - `character.discover`, `character.view_summary`, `character.view_full`, `character.view_inventory`;
   - `character.control`, `character.edit_mechanical_state`;
   - `character.view_player_profile`, `character.edit_player_profile`.

   It never contains:
   - `canon.edit`, `access.manage`, any world capability;
   - `character.view_private`, `character.view_knowledge`, `character.edit_narrative`, `character.interact`, `character.reveal`;
   - `character.view_public_profile`, `character.assign_control`.

   The matrix is code-only. Assignment rows never read `security.character_relationship_type_capabilities`, so a stray mapping row confers nothing on them. The two profile codes and the two operation codes have no consumer in C11; C12 and C20 add them behind their own gates. A structural test pins that no route consumes them yet.
2. **Legacy exclusion.** Add `AND NOT mcr.is_control_assignment` to the `rels` CTE. The legacy matrix and its semantics are otherwise unchanged (R2, R3).
3. **Assignment CTE in the same statement.**
   - **Clock:** factor `perspective_clock`'s SQL into one shared `campaign_clock` CTE; the perspective columns then read it. The statement stays single.
   - **`asgn` CTE:** selects the caller membership's rows that are `is_control_assignment` and `revoked_at IS NULL`, with `campaign_id = :campaign_id`, type active, and the character active and canon (the legacy entity conditions). A row is in effect when its kind is `ongoing`, or its kind is `dated`, the clock key is not NULL and `effective_period @> key`. The interval is half-open: the start is included and the end excluded. An upcoming dated row, and a dated row with no clock, are not in effect (OD-14 "undetermined").
   - **Mapping:** `_access_context_from_row` merges each in-effect row's matrix set into `character_capabilities`, so `has_capability`, discovery (`world_explorer.py:116`) and resource-grant denies apply unchanged. It records the source in a new `AccessContext.control_assignments: Mapping[character_id, ControlAssignmentSource]` field (assignment id, role, kind; default empty).
   - **Clock value:** a new `AccessContext.control_clock_key: int | None` exposes the one clock value the decision used (ADR §2.4 item 1, "one request clock").
4. **Readers** (section 2.1), each changed only as stated:
   - `queries/effective_access.py`:
     - the legacy relationship source adds `NOT is_control_assignment`;
     - a new source of kind `control_assignment` (label "Primary controller (ongoing)", "Co-controller (dated)" and so on, plus the character name) lists only in-effect assignments;
     - it uses one shared SQL fragment with the `asgn` CTE, so the panel and the resolver cannot disagree. The portal renders an unknown kind with its generic label (`EffectiveAccessPanel.tsx:13`), so no portal change.
   - `queries/access_overview.py` member relationships: add `NOT is_control_assignment`. The legacy change and revoke actions never see an assignment row.
   - `commands/access_grants.py` and `commands/access_grant_plans.py` legacy change and revoke: an assignment row id is refused exactly like a row of another campaign (the existing non-disclosing 404). It is never revoked, changed or audited by the legacy commands.
   - `api/parties.py` D4-C roster: the legacy relationship test is kept. A caller also qualifies when `access.control_assignments` holds a character that is a current member of the party and is not under a whole-character `campaign.view` deny. Retiring the legacy test waits for the legacy rows (ADR §2.10; P15-C13).
   - `queries/content_preconditions.py` archive block: the legacy condition gains `NOT is_control_assignment`. Any unrevoked assignment, of either kind and whatever its period, also blocks archiving. Archiving would otherwise silently end control, exactly the reason the legacy block exists.
   - `queries/audit_history.py`: no change. It selects by legacy relationship command names, so assignment audit rows (S02 command names) never appear under "Character relationship". A test pins that.
   - Membership end (`memberships.py`, `membership_end_plans.py`): no change. It already revokes every unrevoked row of the ending membership, which frees the primary slot. A test pins that this includes assignment rows.
   - `queries/bootstrap.py`: no change. Perspectives require `character.view_knowledge`, which no assignment confers. A test pins that.
   - `entity_lifecycle.py:241`: no change.
5. **Documentation:** [ACCESS_CONTROL](../api/ACCESS_CONTROL.md) gets a "Control assignments (P03-B)" subsection (sources, matrix, in-effect rule, exclusions, the legacy rule unchanged, the roster and archive effects). [DATABASE_MODEL](../architecture/DATABASE_MODEL.md) §19.7 records resolution order.

## 4. Files

| File | Task | Change |
|---|---|---|
| `database/migrations/versions/150_control_assignments.py` (new) | T01 | Section 3.1 |
| `src/dnd_ai/persistence/tables/security.py` | T01 | Core columns, constraints, indexes |
| `tests/database/test_control_assignment_storage.py` (new) | T01 | D1–D16 |
| `tests/database/test_control_assignment_migration.py` (new) | T01 | D17–D20 (retained data, downgrade) |
| `src/dnd_ai/domain/access.py` | T02 | Matrix, `rels` exclusion, shared clock CTE, `asgn` CTE, new context fields |
| `src/dnd_ai/queries/effective_access.py` | T02 | Exclusion plus the assignment source |
| `src/dnd_ai/queries/access_overview.py` | T02 | Exclusion |
| `src/dnd_ai/commands/access_grants.py`, `src/dnd_ai/commands/access_grant_plans.py` | T02 | Refuse assignment row ids in legacy change and revoke |
| `src/dnd_ai/api/parties.py` | T02 | Assignment branch of the D4-C roster rule |
| `src/dnd_ai/queries/content_preconditions.py` | T02 | Archive block |
| `tests/database/test_control_assignment_resolution.py` (new) | T02 | E1–E24 |
| `tests/unit/test_control_assignment_matrix.py` (new) | T02 | E25–E27 (closed matrix, no consumer) |
| Docs: DATABASE_MODEL, DOMAIN_MODEL, tables.md (T01); ACCESS_CONTROL, DATABASE_MODEL §19.7 (T02); this plan; the register | T01, T02 | As stated |

## 5. Commits and review boundary

- T01: `feat(db): add control-assignment columns and uniqueness to membership character relationships (P15-C11-S01-T01)`, then a records commit (section 11.3 and the T01 register row).
- T02: `feat(access): resolve control assignments through a clock-aware matrix and keep them out of legacy readers (P15-C11-S01-T02)`, then a records commit.
- **Independent review range for S01:** from the commit that adds this plan to T02's records commit. Per the C11 criteria ("Merge after compatibility review"), the review explicitly covers legacy compatibility: R2/R3 and every reader in section 3.2 item 4 behave unchanged for legacy rows.

## 6. Acceptance cases

Fixtures use the existing factories plus a test-only helper, `make_control_assignment(connection, membership, character, role, kind, *, from_time=None, to_time=None)`. It inserts directly, because no writer exists in S01, and must not be importable from `src`.

**T01 (storage):**

| ID | Case | Baseline expectation |
|---|---|---|
| D1 | An ongoing primary assignment inserts with `campaign_id` filled from the membership and `is_primary` true | fails (columns absent) |
| D2 | A supplied `campaign_id` of another campaign is refused; an `UPDATE` of `campaign_id` is refused | fails |
| D3 | An assignment of type `owner`, `viewer`, `portrayer` or `former_controller` is refused | fails |
| D4 | An assignment with no kind, or a legacy row with a kind, is refused | fails |
| D5 | `ongoing` with a start or an end world time is refused | fails |
| D6 | `dated` without a start is refused; `dated` with a start and no end derives `[from, ∞)`; with both, `[from, to)` | fails |
| D7 | An assignment with `expires_at` or `timeline_id` set is refused | fails |
| D8 | A second live primary for the same campaign and character (any membership, either kind) is refused by the live-primary index; after revoking the first it succeeds | fails |
| D9 | The same membership cannot hold a live primary and a live co-controller assignment on one character | fails |
| D10 | Several live co-controllers for one character coexist; a live primary and co-controllers coexist | fails |
| D11 | A membership holds one live legacy `primary_controller` row and one live primary assignment on the same character (legacy uniqueness unchanged) | fails |
| D12 | Two live legacy rows of the same membership, character and type are still refused by `ux_…_active_type`, under its existing name | **guard** (passes at baseline) |
| D13 | Two campaigns on the same timeline each hold their own live primary for one character | fails |
| D14 | `revoked_by_membership_id` of another campaign is refused; `revocation_reason` on an unrevoked row is refused | fails |
| D15 | A revoked assignment with no revoker and no reason is valid (the membership-end shape) | fails |
| D16 | Every pre-existing insert path still works unchanged: the relationship factory, and `grant_character_relationship` and `change_character_relationship` through their commands, produce legacy rows with `campaign_id` set and `is_control_assignment` false | **guard** (the pre-change paths pass at baseline; the new-column assertions are added after the migration) |
| D17 | Upgrade 149→150 on a populated copy: live, revoked, expired, dated, closed-period and timeline-scoped legacy rows keep every pre-existing column byte-identical; `campaign_id` equals the membership's campaign; `is_control_assignment` false; kind NULL | fails |
| D18 | After upgrade, each fixture user's `AccessContext` equals its pre-upgrade value | fails (revision 150 absent) |
| D19 | Downgrade 150→149 with no assignment rows restores the exact previous index definition (`pg_get_indexdef`), trigger body and columns | fails |
| D20 | Downgrade with one assignment row refuses and changes nothing | fails |

**T02 (resolution and readers):**

| ID | Case | Baseline expectation (at T01's records commit) |
|---|---|---|
| E1 | An in-effect ongoing primary confers exactly the matrix set: `character.control` yes; `view_private`, `view_knowledge` no; no campaign capability | fails (the assignment row is read as a legacy primary, so `view_private` is present) |
| E2 | A co-controller confers the identical set (OD-2) | fails |
| E3 | An ongoing assignment with no clock confers exactly the matrix set (OD-14) | fails (the legacy rule confers the legacy set instead) |
| E4 | A dated assignment with no clock confers nothing (undetermined) | fails |
| E5 | Dated, clock inside `[from, to)` confers; clock equal to `from` confers; clock equal to `to` does not; clock before `from` (upcoming) does not | fails |
| E6 | Branch timeline without its own clock: the parent's clock bounded at the branch point decides; parent time after the branch point is never used | fails |
| E7 | An assignment in campaign A confers nothing in campaign B on the same timeline (no inheritance; T1 and T25 resolution parts) | fails |
| E8 | A revoked assignment, an ended membership, an archived or non-canon character, or an inactive type confers nothing | fails for the type and canon parts; the others are guards |
| E9 | A whole-character `campaign.view` deny suppresses the character from discovery and `has_capability` despite an assignment (§2.9) | fails (no assignment source yet) |
| E10 | A legacy primary row and an assignment for the same membership each keep their own sets; the union is visible through `has_capability`; revoking the assignment leaves the legacy rights | fails |
| E11 | Legacy rows are unchanged: R2 (rights) and R3 (future-dated, no clock) | **guard** |
| E12 | The assigned character is discoverable through `api/world_explorer` | fails |
| E13 | The context exposes `control_assignments` (id, role, kind) and `control_clock_key`; the statement count per snapshot stays one | fails |
| E14 | `tests/database/test_access_snapshot_differential.py` passes unchanged (its corpus has no assignment rows) | **guard** |
| E15 | Effective access lists an in-effect assignment as kind `control_assignment` with its label and never as a character relationship; a dated row with no clock is not listed | fails |
| E16 | The access overview's member relationships omit assignment rows and still list legacy rows | fails |
| E17 | Legacy revoke and change of an assignment row id return the non-disclosing 404, write nothing and audit nothing, through the command and through each route | fails |
| E18 | D4-C roster: an in-effect assignment on a current party member qualifies; a dated-undetermined one does not; a denied character does not; the legacy branch still qualifies | fails |
| E19 | Archive is refused for a character with an unrevoked dated assignment whose period has an end; it is allowed after revocation | fails |
| E20 | Membership end revokes the member's assignment rows, freeing the primary slot for a new assignment | **guard** for revocation; the slot part fails until T01 |
| E21 | Audit history never shows assignment audit rows under character relationships | **guard** |
| E22 | Bootstrap offers no perspective from an assignment | fails (the legacy read confers `view_knowledge`) |
| E23 | A stray `character_relationship_type_capabilities` row (for example `primary_controller` → `canon.edit`) confers nothing on an assignment | fails |
| E24 | A legacy-revoke of an assignment row and the assignment's own resolution agree: the row stays live and in effect | fails |
| E25 | Unit: the matrix keys are exactly the two types, the sets are identical, and contain exactly ADR §2.5 item 2 | fails (no matrix) |
| E26 | Unit: no excluded code (section 3.2 item 1) is in either set | fails |
| E27 | Structural: no module under `src/dnd_ai/api` or `src/dnd_ai/commands` passes `character.control`, `character.edit_mechanical_state`, `character.view_player_profile` or `character.edit_player_profile` to `has_capability` or a requirement | **guard** |

**Test-first evidence.** Write each task's cases first and run them at that task's baseline. Record which fail as designated and which pass as guards. A case that fails for a reason of the test itself is corrected in the test, never by changing the expectation; record that.

## 7. Verification

From `C:\Users\nemes\dnd_ai` (PowerShell; the local PostgreSQL 18 server and `.env` as for focused runs):

1. Focused:
   - T01: `uv run pytest tests/database/test_control_assignment_storage.py tests/database/test_control_assignment_migration.py -q`, plus every existing test file that touches the table. Find them with `rg -l "membership_character_relationship|make_membership_character_relationship|character-relationships" tests`.
   - T02: adds `test_control_assignment_resolution.py`, `tests/unit/test_control_assignment_matrix.py`, `test_access_snapshot_differential.py`, `test_api_effective_access.py`, `test_api_access_overview.py`, `test_api_party_roster.py`, `test_character_relationship_concurrency.py`, `test_r01_s5e3_end_membership.py`, `test_supersession_publish_preconditions.py`, and the files the same search finds.
2. Full backend, once per task on the task's final executable code: `uv run python scripts/run_sharded_tests.py`. A failed first run and any rerun are reported separately; no cause is claimed without evidence.
3. Non-pytest checks: `uv run ruff format --check`, `uv run ruff check`, `uv run mypy src`, `uv lock --check`, `alembic check` (as [DEVELOPMENT §6](../DEVELOPMENT.md#6-testing) states it), `uv run python scripts/check_documentation.py`, `git diff --check`.
4. Portal: no portal file changes, so no portal run is required. If any portal file changes, stop (section 11.1).

**Mutation probes** (restore exact bytes, compare hashes; each must fail at least one named case):

| Probe | Mutation | Must fail |
|---|---|---|
| M1 | Drop `AND NOT is_control_assignment` from the replaced legacy index | D11 |
| M2 | Make the live-primary index ignore `is_primary` | D10 |
| M3 | The trigger stops filling `campaign_id` | D1, D16 |
| M4 | Remove the `rels` exclusion | E1, E22 |
| M5 | Treat a dated row with no clock as in effect | E4 |
| M6 | Use a closed interval (`[]`) for the dated check | E5 |
| M7 | Read the timeline's own clock only (no branch fallback) | E6 |
| M8 | Remove the assignment branch from the roster rule | E18 |
| M9 | Add `character.view_knowledge` to the co-controller set | E2 or E25 |
| M10 | Drop the archive assignment condition | E19 |

## 8. Authorization, disclosure, isolation and outcomes

- **Authorization.** An assignment confers only the closed matrix, and only while in effect, in its own campaign. It confers no campaign capability, no perspective and no private or narrative read. Denies win (§2.9). The legacy matrix is unchanged.
- **Disclosure.** The new explanation source names the role, kind and character, which the caller already discovers through the assignment. Nothing new reaches any other member. Legacy commands refuse assignment ids with the existing non-disclosing 404.
- **Isolation.** `campaign_id` is denormalized, verified and immutable; resolution also requires `campaign_id = :campaign_id`. Two campaigns on one timeline never share an assignment (E7, D13).
- **One clock per decision.** The clock is resolved inside the single authority statement and exposed as `control_clock_key`. The D4-C roster's party-membership test still uses its own membership clock read. That test is not a control decision, and the residual is recorded (section 10, R-6).
- **Draft preservation, retry identity, refusals, unknown outcomes, navigation, focus, announcements.** Not applicable: S01 has no route, command or user interface. These are planned for the writers in S02.
- **Late responses.** Not applicable (no client).

## 9. Intermediate states

- After T01 and before T02: the columns and indexes exist; no writer exists; legacy readers would misread an assignment row, but only tests create one. T02 must land, and S01 must be independently reviewed, before S02 exposes any writer (S02's stated prerequisite).
- After T02: assignments resolve correctly, but nothing creates them until S02-T01.

## 10. Decisions (routine; recorded)

- **R-1, storage form.** Kind is TEXT with a CHECK, following migration 141's `end_reason`. The ADR names a "lookup value"; a two-value closed set with no display metadata does not need a lookup table. No ENUM.
- **R-2, index name kept.** The replaced legacy index keeps `ux_membership_character_relationships_active_type`, so R01 `UniqueWait` declarations stay valid.
- **R-3, trigger fills `campaign_id`.** Existing insert paths and factories need no change.
- **R-4, safe downgrade.** The downgrade refuses while assignment rows exist instead of deleting them or letting them become privileged legacy rows.
- **R-5, matrix merge.** In-effect assignment capabilities merge into `character_capabilities`, so every existing consumer (`has_capability`, discovery, denies) applies them. The source is kept separately for explanations and the roster.
- **R-6, roster clock.** The roster's party-membership predicate keeps its own clock read; only the control half uses the snapshot's clock.
- **R-7, profile and operation codes.** They are in the matrix as the ADR states, with no vocabulary row and no consumer until C12 and C20 (E27 pins this).
- **R-8, archive.** Any unrevoked assignment blocks archiving, whatever its period, because the period can be in effect later.
- **R-9, entity conditions.** Assignment resolution uses the legacy entity conditions (character active and canon). Draft player characters (P03-C, OD-5) are not widened here.

No owner decision blocks S01.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

**T01**
1. Confirm that HEAD equals `origin/phase15/completion`, the worktree is clean, and HEAD is the planning commit. Confirm the Alembic head is still `149_reservation_fk_deferrable` and that the section 2.1 facts for the table, trigger and index hold. Report any difference before implementing.
2. Write D1–D20 first. Run them at the baseline; record designated failures and guards (D12, D16's pre-change part).
3. Implement section 3.1 only, in the section 4 T01 files.
4. Run the section 7 focused set, the full shard run and the non-pytest checks. Report a failed first run and any rerun separately.
5. Run M1–M3 with byte restoration and hash comparison.
6. Commit with the T01 subject and push. Record in section 11.3 and the T01 register row (actual SHAs and runs), then commit and push the records.

**T02**
1. Revalidate: HEAD equals origin, the worktree is clean, T01's records commit is present, and section 2.1's reader list still matches. Run `rg -n "membership_character_relationships" src` and stop if a new production reader appears that section 3.2 does not cover.
2. Write E1–E27 first; run them at the baseline and record fails and guards.
3. Implement section 3.2 only.
4. Run the section 7 focused set (T02), full shards and non-pytest checks.
5. Run M4–M10.
6. Commit with the T02 subject and push, then record and push the records commit.

**Permitted test adaptations (each named in the record):**
- a test that pins the Alembic head revision;
- schema-comment and table-inventory tests that enumerate columns or indexes;
- the D4-C structural test, if it pins the function body rather than its single caller;
- `tests/access_reference.py` **only** if the differential corpus has to include an assignment row, which it should not.

No other expectation changes.

**Stop conditions:**
- an API route, command writer or portal change becomes necessary;
- any legacy guard (D12, D16, E11, E14, E20, E21) fails;
- an R01 declaration other than the named index changes;
- a production reader of the table outside section 3.2 appears;
- the single-statement property cannot be kept;
- the ADR contract appears to need changing.

Report and stop; do not adapt the contract.

No PR, no S02 work, no consumers, no browser/AX checks, no acceptance.

### 11.2 Independent review boundary

The plan commit through T02's records commit. The review includes the compatibility review the C11 criteria require: legacy rights, the legacy index name and semantics, and every reader in section 3.2 item 4 for legacy rows.

### 11.3 Implementation record

(Empty until T01.)

## 12. C11 checkpoint coordination

### 12.1 Order, prerequisites and shared files

- **Order.** S01-T01, S01-T02, then **S01 independent review**, then S02-T01, S02-T02. T02 depends on T01's columns. S02-T01 may not start before S01 is independently reviewed; that is S02's stated prerequisite ([register](work-register.md#p15-c11-s02)), not a scheduling choice. S02-T02 follows S02-T01 because it extends the same authority resolver and routes.
- **S02 planned ahead of its prerequisite.** The [S02 plan](p15-c11-s02-control-changes-plan.md) is prepared now. Its section 2 lists the S01 contracts it relies on. At S02-T01 start, Sonnet revalidates them against the reviewed S01 code. If an S01 correction changes one of them, S02 stops and returns to Opus.
- **Shared files.**
  - `src/dnd_ai/domain/access.py`: S01-T02 (matrix, `asgn`), S02-T01 (owner and GM authority CTE), S02-T02 (delegation source).
  - `src/dnd_ai/persistence/tables/security.py`: S01-T01; S02-T02 (delegation table).
  - Migrations: `150` (S01-T01), `151` (S02-T02). Each task revalidates the next free revision.
  - R01 registries and the generated manifest: S02-T01, S02-T02.
  - Docs: ACCESS_CONTROL, DATABASE_MODEL, tables.md, operations.md, this register.
  - Each later task revalidates its own baseline: HEAD equals origin, the worktree is clean, the previous task's records commit is present, and the plan's section 2 facts for its files still hold.

### 12.2 C11 checkpoint merge requirements

The C11 PR may merge only when all of these hold. They are the register rule; nothing is added.

1. S01 and S02 are each independently reviewed, including the compatibility review in the C11 criteria, with any corrections confirmed.
2. On the integration head, D1–D20 and E1–E27 (this plan) and F1–F32 and H1–H22 ([S02 plan](p15-c11-s02-control-changes-plan.md#6-acceptance-cases)) pass, with:
   - one full backend shard run on the final executable code;
   - the non-pytest checks (`ruff format --check`, `ruff check`, `mypy src`, `uv lock --check`, `alembic check`, `git diff --check`).

   A portal run is required only if a portal file changed.
3. CI passes on that exact PR head.

### 12.3 Separate events (after the merge; not merge gates)

[actor-b](work-register.md#actor-b) (needs C12 and C20 too), [profile-authority](work-register.md#profile-authority), consumers using B's scope, browser and AX work for any later UI, `p15-integration` and `p15-owner`. None is granted by this plan.
