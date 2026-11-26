# D/P15-C11-S01 implementation plan: store and resolve control assignments

Owner register rows: [P15-C11](work-register.md#p15-c11), [P15-C11-S01](work-register.md#p15-c11-s01), [P15-C11-S01-T01](work-register.md#p15-c11-s01-t01), [P15-C11-S01-T02](work-register.md#p15-c11-s01-t02). Governing contract: [ADR 0021](../adr/0021-shared-actor-identity-control-and-authoring-responsibility.md) §2.1–§2.6, §2.9–§2.10 (owner-accepted, [adr21](work-register.md#adr21)); decisions OD-2 and OD-14; tests T2, T3, T5 (resolution part) and T25 (index replacement, clock boundaries, no branch inheritance) in [rules foundations §8](rules-foundations.md). The companion slice is [S02](p15-c11-s02-control-changes-plan.md). Checkpoint coordination for both slices is in [section 12](#12-c11-checkpoint-coordination).

Prepared by Opus, 2026-11-25. **Planned; not implemented.** Amended by Opus, 2026-11-26, after T01 stopped on its R01 declaration stop condition. The amendment authorizes the R01 relationship-declaration correction in section 3.1 item 9 and changes sections 2.1, 3.1, 4, 6, 7, 10 and 11. The stop and its evidence are recorded in section 11.3. Amended again by Opus, 2026-11-26, after T02 stopped on the R01 authority-reader classes. That amendment selects the always-on campaign clock with an accurate reader constant and a reviewed clock class (section 3.2 item 3a; R-13 to R-16). It changes sections 2.1, 3.2, 4, 6, 7, 8, 10, 11 and 12. Amended a third time by Opus, 2026-11-26, after the T02 draft stopped on A5a's controller-vocabulary guard. That amendment narrows the guard to the matrix declaration (section 3.2 item 1a; R-17; E37; M20–M25) and changes sections 3.2, 4, 6, 7, 10, 11 and 12.

- Starting SHA: `dabd7d1ab92a1575eb3769e539074ccbab34de8e`, the reviewed C10 PR head, with a clean worktree.
- Plan-entry head: `ebe6c7241a581cff1e2fac265a3af9230c656fa1`, the C10 merge (PR #79), reached by fast-forward. Its tree equals `dabd7d1`'s; no history was rewritten.
- C10 merge bookkeeping is a separate documentation commit, `b0d314210d3dc216a8cdfa3ba57727f79485cb7a`, before this plan.
- The S01-T01 baseline is the commit that adds this plan (reported in the handoff). T02's baseline is T01's records commit, `34215f242ac3f2b110b541d4a5e78718bc80da91`; the T02 amendment commit follows it.
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
| R01 declarations on the table (added 2026-11-26) | Five `WriteStep`s write the table: `GRANT_RELATIONSHIP_INSERT`, `CHANGE_RELATIONSHIP_INSERT`, `CHANGE_RELATIONSHIP_REVOKE_OLD` and `REVOKE_RELATIONSHIP` (`access_grant_plans.py:361-436`), and `END_REVOKE_RELATIONSHIP` (`membership_end_plans.py:460`). All five pin `RELATIONSHIP_TRIGGERS` (`membership_end_plans.py:304`, the scope function by `md5(prosrc)`). Two checkers apply to them. **Core**, at import (`domain/authorization_steps.py:1213-1223`): an INSERT names a `UniqueWait` for every named unique index of its table, and an UPDATE for each index whose key columns it sets. **Live catalogue** (`tests/r01_pre_write_catalogue.py`): it counts index dependencies through `pg_depend`, so predicate columns count too (lines 377-401). An omitted `NOT NULL` column must have a default (342-356), and the pinned triggers must equal the catalogue's for the command (427-438). The two live tests are `test_the_declarations_hold_against_the_live_catalogue` in `test_r01_s5e4_access_grants.py:974` and `test_r01_s5e3_end_membership.py`. No other R01 declaration writes the table. |
| Legacy resolver | `rels` CTE in `_ACCESS_CTES` (`domain/access.py:~1105-1135`): unrevoked, unexpired, `effective_to_world_time_id IS NULL`, timeline unset or the campaign's, type active, character active and canon. `_access_context_from_row` (`access.py:1626`) keeps a row's capability only if `BUILTIN_RELATIONSHIP_CAPABILITIES` (`access.py:169`) permits it. The whole decision is one statement (`read_authority_snapshot`, `access.py:1513`). |
| R01 reader tables (added 2026-11-26, T02 stop; at `34215f2`) | `AUTHORITY_READER_TABLES` (`access.py:1436`) must equal the tables the base statement plus the world and reveal sources name. `tests/unit/test_r01_authorization_structure.py:99` pins that, and line 113 checks that no route of the four post-write families (`authoring_scope`, `operation_scope`, `reveal_authority`, `route_capability_only`; 156 routes) writes a reader table outside `REVIEWED_POST_WRITE_TABLES` (`access.py:1470`: `core.entities`, `campaign.sessions` and the two revelation tables). The opt-in perspective tables (`campaign.timelines`, `campaign.timeline_clocks`, `core.world_times`, `campaign.campaign_parties`, `campaign.party_memberships`) are outside the constant today. They are read only with `with_perspective`, and only by the E2 engine routes, which are not in those families. Post-write writers of the clock tables, from the manifest and `src`: `POST /campaigns/{campaign_id}/clock/advance` and `…/clock/correct` (`campaign.timeline_clocks`) and `POST /campaigns/{campaign_id}/world-times` (`core.world_times`). All three are `operation_scope` routes with the single dependency campaign `canon.edit`. No post-write route writes `campaign.timelines`; its writers are the world timeline routes (`no_campaign_capability`). Each of the three registers exactly `route.canon.edit` and `campaign.canon.edit` (`api/access.py:168`, `commands/_content.py:53`; pinned for two of them by `test_r01_s4_operation_routes.py:567`). Both predicates call `has_capability` with no target, which reads `role_capabilities` only (`access.py:378`). |
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
   Existing unguarded inserts (`grant_character_relationship`, `change_character_relationship`, factories, seeds) keep working unchanged because the trigger fills `campaign_id`. The two R01 INSERT steps supply it explicitly (item 9).

   `is_primary` is derived for **every** row, legacy rows included, and the backfill matches what the trigger derives. This follows ADR §2.3 ("maintained by the type trigger"). It also means a later UPDATE never silently changes the value. A legacy `primary_controller` row therefore has `is_primary` true and still never enters the live-primary index, whose predicate requires `is_control_assignment` (D11b). `is_primary` alone never means "primary assignment": every reader pairs it with `is_control_assignment`.
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
   - supporting `ix_…_campaign_id` and partial `ix_…_revoked_by` indexes.
   - Every name this revision creates (constraints, indexes, trigger) stays within 63 bytes, so PostgreSQL never truncates one. The draft's `membership_character_relationships_revoked_by_membership_id_fkey` is 64 bytes and is renamed, for example to `membership_character_relationships_revoked_by_fkey` (D21).
5. **Comments** on every new column, constraint-bearing behavior and index (the schema-comment reconciliation tests require them).
6. **Downgrade:** refuses with a clear error while any `is_control_assignment` row exists. It never deletes them silently and never lets them become legacy rows that would confer `view_private`. Otherwise it restores the exact previous index, trigger body and columns.
7. **Core metadata** (`persistence/tables/security.py`): the same columns, foreign keys, indexes and comments, so `alembic check` reports no drift. CHECK constraints are **not** declared in Core, following the package convention (`persistence/tables/__init__.py:22-25`): Alembic does not compare them, and D4–D7 and D14 cover them in tests. Leaving them out changes no autogenerate result and nothing either R01 checker reads. The live catalogue reads CHECKs from `pg_constraint`, and the new ones use only built-in immutable functions.
8. **Documentation:**
   - [DATABASE_MODEL](../architecture/DATABASE_MODEL.md) §19.4 (assignment columns and invariants, plus one sentence on item 9) and §7.3, and [DOMAIN_MODEL](../DOMAIN_MODEL.md) §8.4. Each marks `character.character_controllers` as retired by ADR 0021 §2.1.
   - [tables.md](../reference/tables.md) is a name inventory with no per-table columns. It gets:
     - the current revision head, `150_control_assignments`, in its opening paragraph;
     - in the `character_controllers` disposition row, a short statement that the name is retired by ADR 0021 §2.1, that control assignments are marked rows of `security.membership_character_relationships`, and a link to DATABASE_MODEL §19.4.

     Column and index lists stay in DATABASE_MODEL. The earlier wording, "gets the new columns and indexes", was a plan error.
   - [ACCESS_CONTROL](../api/ACCESS_CONTROL.md) R01 S5-E4 section: one sentence under "Tests" naming G1, and stating that the relationship steps supply `campaign_id` and declare the assignment indexes.
9. **R01 relationship declarations (authorized by the 2026-11-26 amendment).** Section 11.3 records why: revision 150 makes the five declarations in section 2.1 fail three checks, at collection (Core) and in both live-catalogue tests. The correction preserves every checker guarantee. It changes `domain/authorization_steps.py`, `tests/r01_pre_write_catalogue.py`, every other declaration, every lock and lock order, the route registries and the manifest **not at all**.
   1. **The two legacy INSERT steps supply `campaign_id`.** `GRANT_RELATIONSHIP_INSERT` and `CHANGE_RELATIONSHIP_INSERT` add `campaign_id=bindparam("campaign")` and `_fk(mcr, "campaign_id", "campaign", CAMPAIGN_ROW_LOCK)`, the `CREATE_GRANT_INSERT` pattern (`access_grant_plans.py:441,458`). The value travels in `AccessPrepared`, which gains `campaign_id: uuid.UUID | None = None`. `prepare_grant_relationship` and `prepare_change_relationship` set it from their `campaign_id` parameter, and `write_grant_relationship` and `write_change_relationship` bind `prepared.campaign_id`. Their signatures and every API caller stay unchanged. (A first plan-time prototype that named `campaign_id` inside the write functions failed with a `NameError` 500; section 11.3.) Both plans already hold that campaign `FOR UPDATE` (`access_grant_plans.py:877,1066`), so no lock is added or moved. The value always equals the membership's campaign because `TARGET_MEMBERSHIP_LOCK` is campaign-bound, so the trigger's equality check cannot fire for these steps. Why not the trigger: the live catalogue refuses an omitted `NOT NULL` column without a default. It cannot see a trigger fill one, and teaching it that would be general trigger analysis.
   2. **The four access-grant steps declare the assignment indexes as never entered.** A new `_OUTSIDE_ASSIGNMENT_INDEXES` holds `UniqueWait` entries for `security.ux_membership_character_relationships_live_primary` and `…_live_assignment`. Each names G1. It is added (set union) to the two INSERT steps' `_COMPETING_RELATIONSHIP_WAIT` and to the two UPDATE steps' `_LEAVES_RELATIONSHIP_INDEX`. The semantics are exact:
      - the INSERTs never set `is_control_assignment`, so it takes its default, false;
      - the trigger reads that column but never sets it, and revision 150 makes it immutable;
      - so the row is outside both predicates and is never a unique-check entry for either index;
      - the UPDATEs set only `revoked_at`. After T02 they close legacy rows only, because assignment ids are refused (section 3.2 item 4), and a legacy row is outside both indexes before and after the update;
      - between T01 and T02 they could also close an assignment row, but only a test can create one. That update *leaves* both indexes, which also never waits.

      The existing named constants keep their meaning and their tests.
   3. **Membership end declares that it leaves the assignment indexes.** `END_REVOKE_RELATIONSHIP` revokes every unrevoked row of the membership, assignment rows included (E20). Its `unique_waits` becomes `_leaves_index(active_type) | _leaves_index(live_primary) | _leaves_index(live_assignment)`, using the existing helper and its existing test name, which G2 extends. Setting `revoked_at` takes an assignment row out of both predicates. The update therefore inserts no index entry and never waits, and a competitor's insert of the same key waits for the end's transaction.
   4. **Trigger pins.** In `RELATIONSHIP_TRIGGERS`, re-pin `enforce_membership_character_relationship_scope` to `md5(prosrc)` of revision 150's body. Add `tr_membership_character_relationships_enforce_immutable` (`_IMMUTABLE_FN`, `events={UPDATE}`, `args=("campaign_id", "is_control_assignment", "assignment_period_kind")`). Add `RELATIONSHIP_INSERT_TRIGGERS` and `RELATIONSHIP_UPDATE_TRIGGERS`, the event-filtered subsets, as `MEMBERSHIP_ROLE_TRIGGERS` is filtered at `membership_role_plans.py:399`. INSERT steps pin the INSERT subset and UPDATE steps the UPDATE subset. The new function body takes no lock: it adds only plain `SELECT`s of the type row and the revoker's membership.

   Plan-time validation (section 11.3) applied exactly this correction to the uncommitted implementation, then restored the bytes. Collection then succeeded with no errors, and all 41 live-catalogue tests passed.

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
1a. **A5a's vocabulary guard moves to the matrix (added 2026-11-26, T02 stop; R-17).** `tests/unit/test_player_profiles_structure.py::test_no_controller_capability_vocabulary_exists_in_the_application_or_the_seeds` forbids a quoted `character.view_player_profile` or `character.edit_player_profile` anywhere in `src`, in the seeds and in migration 147. Item 1 requires both codes in the matrix, so the draft fails it. The guard was A5's scope fence, not a permanent rule. The [player-profile design](player-profile-design.md) §2 item 6 and §3 assign "`CONTROL_ASSIGNMENT_CAPABILITIES`, including `character.view_player_profile` and `character.edit_player_profile`" to P03-B, and ADR 0021 §2.5 item 2 puts them in the matrix. The guard is replaced, under the new name `test_the_controller_profile_codes_appear_only_in_the_control_assignment_matrix` (E37), by a narrower one. Nothing else is exempted:
   - **Where the codes may appear.** Every quoted occurrence in `src/dnd_ai/**/*.py` must lie inside the matrix declaration. Occurrences are matched in the raw source, comments and docstrings included, with A5a's existing regular expression. The matrix declaration is the module-level assignment of `CONTROL_ASSIGNMENT_CAPABILITIES` in `domain/access.py`, plus the module-level assignment of each name that its dict values reference (today `_CONTROL_ASSIGNMENT_SET`), located by `ast`. There is no file-wide exemption for `domain/access.py`.
   - **Shape inside it.** Every quoted occurrence there must be an `ast.Constant` element of a set literal. The number of regex matches must equal the number of such constants, so a quoted code in a comment inside the declaration also fails. The codes found must be exactly the two.
   - **Who may name the matrix.** The `src` modules that contain `CONTROL_ASSIGNMENT_CAPABILITIES` are exactly `domain/access.py` (declaration and merge) and `queries/effective_access.py` (the explanation, a display that is never an authorization input). A consumer that iterates the matrix instead of writing a literal is therefore caught too.
   - **Seeds and migrations.** No file under `database/` (every seed and **every** migration, not only 147; `__pycache__` skipped) contains a quoted code. This is wider than A5a's check of migration 147.
   - **Unchanged:**
     - `tests/database/test_character_player_profiles_schema.py::test_no_controller_profile_capability_exists_yet` (no `security.capabilities` row; R-7);
     - the read-rule identifier test (`may_read_player_profile` consults only `has_effective_character_canon_edit`);
     - E27;
     - every other test in the file.

   C12 (profile-authority) narrows or retires E37 when it adds the vocabulary rows and the controller read and edit.
2. **Legacy exclusion.** Add `AND NOT mcr.is_control_assignment` to the `rels` CTE. The legacy matrix and its semantics are otherwise unchanged (R2, R3).
3. **Assignment CTE in the same statement.**
   - **Clock:** factor `perspective_clock`'s SQL into one shared `campaign_clock` CTE; the perspective columns then read it. The statement stays single. *Amended 2026-11-26:* `campaign_clock` and `asgn` are part of the **base** statement on every call, with no opt-in flag. Every access resolution therefore evaluates assignment authority: early checks, `resolve_access_context`, and every final check (R-13). The CTE is named `campaign_clock`, never `clock`, which is already the instant CTE. It reads only the three clock tables, takes no row lock, and its SQL is unchanged from today's `perspective_clock`.
   - **`asgn` CTE:** selects the caller membership's rows that are `is_control_assignment` and `revoked_at IS NULL`, with `campaign_id = :campaign_id`, type active, and the character active and canon (the legacy entity conditions). A row is in effect when its kind is `ongoing`, or its kind is `dated`, the clock key is not NULL and `effective_period @> key`. The interval is half-open: the start is included and the end excluded. An upcoming dated row, and a dated row with no clock, are not in effect (OD-14 "undetermined").
   - **Mapping:** `_access_context_from_row` merges each in-effect row's matrix set into `character_capabilities`, so `has_capability`, discovery (`world_explorer.py:116`) and resource-grant denies apply unchanged. It records the source in a new `AccessContext.control_assignments: Mapping[character_id, ControlAssignmentSource]` field (assignment id, role, kind; default empty).
   - **Clock value:** a new `AccessContext.control_clock_key: int | None` exposes the one clock value the decision used (ADR §2.4 item 1, "one request clock").
3a. **R01 reader classes (added 2026-11-26, T02 stop).** The always-on clock makes three tables inputs of every final check. That is the change R01's post-write rule ("a post-write request must not write a table its own decision reads") must review. Authorized changes, and no others:
   - **Accurate constant.** `AUTHORITY_READER_TABLES` gains exactly `campaign.timelines`, `campaign.timeline_clocks` and `core.world_times`. The existing equality test (`test_r01_authorization_structure.py:99`) is unchanged and must pass. `campaign.campaign_parties` and `campaign.party_memberships` stay opt-in perspective inputs outside the constant, as today.
   - **Reviewed clock class.** `REVIEWED_POST_WRITE_TABLES` gains exactly `campaign.timeline_clocks` and `core.world_times`. `campaign.timelines` is **not** reviewed: no post-write route writes it, so the disjointness check keeps protecting it.
   - **What is exempted, precisely.** A post-write request may write those two tables even though its final statement reads them. In that statement they feed only the `campaign_clock` key, and through it only the `asgn` in-effect test. Its outputs are `character_capabilities[character_id]` entries from the closed matrix, `control_assignments` and `control_clock_key`. A requirement can observe them only by:
     - calling `has_capability(..., character_id=…)` with one of the matrix codes;
     - reading the two control fields;
     - using the perspective component, which reads the same key.

     Nothing else is exempted. The two tables stay protected for every route outside the inventory below.
   - **Why the three current writers are safe.** Each one's final check is `route.canon.edit` then `campaign.canon.edit`. Both predicates use only these inputs:
     - `access is None`, which depends only on the `m` CTE (membership and status);
     - campaign lifecycle (`camp`);
     - `has_capability("canon.edit")` with no target, which reads `role_capabilities` only.

     No clock-derived output reaches either predicate. The closed matrix never contains `canon.edit` or any campaign capability (E26), and `character_capabilities` never enters a targetless check (`access.py:378`). Other paths:
     - **Denies:** they come from `grant_effects`, which the clock never touches.
     - **Revelations:** they are not clock-dependent.
     - **Reveal delegation, world authority and the subject-`gm` source:** none is registered by these routes.
     - **Visibility:** the advance route's `denied_event_ids` comes from grant denies plus lifecycle. It is a domain eligibility input computed from the early context before the write, not a final-check input.
     - **Fallback:** a replay judges `route.canon.edit` only (`test_r01_s4_operation_routes.py:567`).

     Why each write is harmless:
     - **`world-times`:** it inserts a new world time and never changes an existing `sort_key`. No trigger renumbers, and a stored `effective_period` was materialized at its own write. So the route cannot change any clock key or any assignment's effect, even for other callers.
     - **`advance` and `correct`:** they change the key. Their own final statement sees the request's uncommitted key, so the caller's `character_capabilities` may differ from the early check's. That is intended, and no requirement of these routes reads them (E33).
   - **Closing the table-wide scope.** A table-wide class would admit any future post-write writer, for example a controller operation (C20) that writes the clock and whose own decision reads `character.control`. Two structural tests close that:
     - E29 pins `REVIEWED_POST_WRITE_TABLES` to exactly its six tables.
     - E30 pins the inventory: the post-write routes that write either reviewed clock table are exactly the three above; each is `operation_scope` with exactly one dependency, campaign `canon.edit` with no world capability and no Foundry access; and no post-write route writes `campaign.timelines`.

     E32 pins at run time that each of the three registers exactly `route.canon.edit` and `campaign.canon.edit`, with no character, perspective, world, reveal, subject-`gm` or account requirement. A new writer, or a new requirement on one of the three, fails these tests and needs its own review. It is never admitted by the class.
   - **Concurrency.** The snapshot takes no row lock. A reader never waits for a clock writer's `FOR UPDATE` (E35); it sees the committed key. A request judged by an assignment whose effect a concurrent advance ends may therefore commit after the advance if its final statement ran first. That is the accepted R-D1 residual (instant, not commit), exactly as for an account deactivation. C20 decides whether controller operations share-lock the clock (R-16).
   - **Unchanged:** `test_post_write_routes_write_none_of_the_readers_tables_except_the_reviewed_classes` and `test_the_access_management_family_is_not_in_the_post_write_check` (logic, family set and the 156-route pin), the manifest, every lock and lock order, and every declaration.
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
5. **Documentation:** [ACCESS_CONTROL](../api/ACCESS_CONTROL.md) gets a "Control assignments (P03-B)" subsection (sources, matrix, in-effect rule, exclusions, the legacy rule unchanged, the roster and archive effects). [DATABASE_MODEL](../architecture/DATABASE_MODEL.md) §19.7 records resolution order. *Added 2026-11-26:* the owning R01 record is [ACCESS_CONTROL "Authorization timing and the final check (R01 S6)"](../api/ACCESS_CONTROL.md#authorization-timing-and-the-final-check-r01-s6), which the register's R01 section names as authoritative. It gains one paragraph, in the same commit as the constants: the final check reads the campaign clock; the reviewed clock class, with exactly what item 3a exempts and why; the three-route inventory and its tests; and the concurrency residual. The docstrings of both constants and of the disjointness test name the new class and point there. The paragraph is written with the implementation, not before it, so the contract never describes a reviewed class that does not exist. *Added 2026-11-26 (A5a guard):* the "Reserved, not built" bullet of ACCESS_CONTROL's A5a section keeps its A5a sentence. It gains one dated sentence: from P15-C11-S01-T02 the two codes are elements of `CONTROL_ASSIGNMENT_CAPABILITIES`, with no vocabulary row and no consumer, and C12 adds the controller branch. The [player-profile design](player-profile-design.md) records the transition beside A5a's record (committed with this amendment).

## 4. Files

| File | Task | Change |
|---|---|---|
| `database/migrations/versions/150_control_assignments.py` (new) | T01 | Section 3.1 |
| `src/dnd_ai/persistence/tables/security.py` | T01 | Core columns, constraints, indexes |
| `src/dnd_ai/commands/access_grant_plans.py` | T01 | Section 3.1 item 9.1–9.2 (the two INSERT steps and their call sites, `_OUTSIDE_ASSIGNMENT_INDEXES`, the event-filtered trigger subsets) |
| `src/dnd_ai/commands/membership_end_plans.py` | T01 | Section 3.1 item 9.3–9.4 (`END_REVOKE_RELATIONSHIP` waits, `RELATIONSHIP_TRIGGERS` pins and subsets) |
| `tests/factories.py` | T01 | `make_control_assignment` moved here from the storage test file (shared by D, G and E cases and by S02); test-only, never imported by `src` |
| `tests/database/test_control_assignment_storage.py` (new) | T01 | D1–D16, D11b, D16b |
| `tests/database/test_control_assignment_migration.py` (new) | T01 | D17–D21 (retained data, downgrade, untruncated names) |
| `tests/database/test_r01_s5e4_access_grants.py` | T01 | G1 (new test and its positive control), G4 |
| `tests/database/test_r01_s5e3_end_membership.py` | T01 | G2 (two new parametrization ids and their competitors; existing ids unchanged) |
| `src/dnd_ai/domain/access.py` | T02 | Matrix, `rels` exclusion, shared always-on `campaign_clock` CTE, `asgn` CTE, new context fields; `AUTHORITY_READER_TABLES` +3 and `REVIEWED_POST_WRITE_TABLES` +2 with their docstrings (section 3.2 item 3a) |
| `tests/unit/test_r01_authorization_structure.py` | T02 | New E28, E29, E30; the disjointness test's docstring names the clock class. Existing tests unchanged in logic |
| `tests/unit/test_control_assignment_separation.py` (new) | T02 | E31 |
| `tests/database/test_control_assignment_clock_routes.py` (new) | T02 | E32–E35 |
| `tests/database/test_r01_e2_perspective_snapshot.py` | T02 | Permitted adaptation only: `test_one_statement_no_row_lock` asserts the CTE name `campaign_clock` instead of `perspective_clock` |
| `src/dnd_ai/queries/effective_access.py` | T02 | Exclusion plus the assignment source |
| `src/dnd_ai/queries/access_overview.py` | T02 | Exclusion |
| `src/dnd_ai/commands/access_grants.py`, `src/dnd_ai/commands/access_grant_plans.py` | T02 | Refuse assignment row ids in legacy change and revoke |
| `src/dnd_ai/api/parties.py` | T02 | Assignment branch of the D4-C roster rule |
| `src/dnd_ai/queries/content_preconditions.py` | T02 | Archive block |
| `tests/database/test_control_assignment_resolution.py` (new) | T02 | E1–E24 |
| `tests/unit/test_control_assignment_matrix.py` (new) | T02 | E25–E27 (closed matrix, no consumer) |
| `tests/unit/test_player_profiles_structure.py` | T02 | Permitted adaptation only (section 3.2 item 1a): A5a's vocabulary test becomes E37 under its new name, and the module docstring's "no … vocabulary (P03-B)" clause says that the codes are confined to the matrix. Every other test in the file is unchanged |
| Docs: DATABASE_MODEL, DOMAIN_MODEL, tables.md, ACCESS_CONTROL R01 S5-E4 sentence (T01); ACCESS_CONTROL control-assignment subsection, the ACCESS_CONTROL R01 S6 reviewed-clock-class paragraph, DATABASE_MODEL §19.7 (T02); this plan; the register | T01, T02 | As stated |

## 5. Commits and review boundary

- T01: `feat(db): add control-assignment columns and uniqueness to membership character relationships (P15-C11-S01-T01)`, then a records commit (section 11.3 and the T01 register row).
- T02: `feat(access): resolve control assignments through a clock-aware matrix and keep them out of legacy readers (P15-C11-S01-T02)`, then a records commit.
- **Independent review range for S01:** from the commit that adds this plan to T02's records commit. Per the C11 criteria ("Merge after compatibility review"), the review explicitly covers legacy compatibility: R2/R3 and every reader in section 3.2 item 4 behave unchanged for legacy rows.

## 6. Acceptance cases

Fixtures use the existing factories plus a test-only helper, `make_control_assignment(connection, membership, character, role, kind, *, from_time=None, to_time=None)`. It inserts directly, because no writer exists in S01, and must not be importable from `src`. It lives in `tests/factories.py`, because the D, G and E cases and S02 all use it. The draft defined it locally in the storage test file. Its extra keyword arguments for refused shapes may stay.

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
| D11b | (added 2026-11-26) A legacy `primary_controller` row of member A has `is_primary` true, and member B's primary assignment on the same character still inserts: a legacy row never occupies the live-primary slot | fails (columns absent) |
| D16b | (added by the draft) Legacy rows from the factory and both unguarded commands have `campaign_id` set and `is_control_assignment` false | fails (columns absent) |
| D21 | (added 2026-11-26) Every constraint, index and trigger name revision 150 creates appears in `pg_catalog` exactly as written, with no 63-byte truncation | fails (revision absent) |

**T01 (R01 declaration evidence, section 3.1 item 9; added 2026-11-26).** Shape and collection checks (G3) are kept apart from the behavioral lock-wait evidence (G1, G2):

| ID | Case | Kind | Baseline expectation (at `7281d6c`) |
|---|---|---|---|
| G1 | `test_r01_s5e4_access_grants.py::test_a_legacy_relationship_write_never_waits_on_an_assignment_index`, the test G1's `UniqueWait` entries name. It runs on two connections with no route locks, so the index alone decides. Parametrized over the four access-grant steps (`GRANT_RELATIONSHIP_INSERT`, `CHANGE_RELATIONSHIP_INSERT`, `CHANGE_RELATIONSHIP_REVOKE_OLD`, `REVOKE_RELATIONSHIP`) × the two new indexes. Connection B holds an uncommitted assignment with the overlapping key: for live-primary, a primary assignment by another membership on the same character; for live-assignment, an assignment by the same membership on the same character. Connection A, under `SET LOCAL lock_timeout = '5s'`, executes the step's own `statement` with real binds on a legacy `primary_controller` row. For an INSERT that is a new row; for an UPDATE it revokes a committed row. A completes without `LockNotAvailable`. For the INSERT steps the reverse order holds too: A first, uncommitted; then B completes under the same timeout. Both commit, and both rows exist | behavioral (index wait) | fails (columns absent) |
| G1-control | Same module, `test_the_assignment_index_harness_detects_a_real_wait`: the same harness, with A inserting a **second assignment** with the same key while B's is uncommitted, raises `LockNotAvailable` (SQLSTATE 55P03) for each index. Without this control G1 could pass vacuously | behavioral (positive control) | fails (columns absent) |
| G2 | `test_r01_s5e3_end_membership.py::test_an_update_leaving_a_partial_unique_index_never_waits_for_a_competing_insert` gains ids `live_primary` and `live_assignment`. For those ids only, the test first commits an ongoing primary assignment of `e.membership` on `e.character`. The competitor, started while the end is parked at its audit insert, is: for `live_primary`, a primary assignment by another open membership on `e.character`; for `live_assignment`, a co-controller assignment of `e.membership` on `e.character`. Existing pattern: the competitor is blocked by the end's pid, the end returns 200, and then the competitor completes with no error. The docstring states that the `live_primary` competitor waits on the index entry of the updated row, and the `live_assignment` competitor on the membership row lock that the end holds `FOR UPDATE`. Existing ids and the shared `Member` fixture are unchanged | behavioral (route race) | fails (columns absent) |
| G3 | Shape: `uv run pytest tests --collect-only -q` reports no collection error, and both `test_the_declarations_hold_against_the_live_catalogue` tests pass. These checks prove that the declarations match the catalogue, not wait behavior | shape | collection errors in 47 modules with the draft (section 11.3) |
| G4 | `test_r01_s5e4_access_grants.py`: a relationship created through the grant route, and one through the change route (each keyed and unkeyed), has `campaign_id` equal to the route campaign and `is_control_assignment` false. Every existing grant and change route test passes unchanged | behavioral (route) | fails (columns absent) |

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

**T02 (R01 reader classes, section 3.2 item 3a; added 2026-11-26).** E28–E31 are structural or unit checks, which prove shape and separation. E32–E35 are behavioral database tests.

| ID | Case | Kind | Baseline expectation (at `34215f2`) |
|---|---|---|---|
| E28 | `test_r01_authorization_structure.py::test_the_base_statement_reads_the_campaign_clock`: `_authority_snapshot_sql(instant="fresh", with_world=False, with_reveal=False)` names `campaign.timelines`, `campaign.timeline_clocks` and `core.world_times` and contains the `campaign_clock` CTE. No opt-in flag adds or removes them. The existing equality test passes with the constant +3 | structural | fails (the clock is opt-in) |
| E29 | `…::test_the_reviewed_post_write_classes_are_exactly_the_six_tables`: `REVIEWED_POST_WRITE_TABLES` equals `core.entities`, `campaign.sessions`, the two revelation tables, `campaign.timeline_clocks` and `core.world_times` | structural | fails (four tables) |
| E30 | `…::test_the_post_write_writers_of_the_reviewed_clock_tables_are_exactly_the_three_clock_routes`: from the manifest, the post-write routes whose `command_writes` include `campaign.timeline_clocks` or `core.world_times` are exactly `POST …/clock/advance`, `POST …/clock/correct` and `POST …/world-times`. Each is `operation_scope` with exactly one dependency: `campaign_capability` `canon.edit`, `world_capability` null, `allow_foundry_access` false. No post-write route writes `campaign.timelines` | structural (route inventory) | **guard** (holds at baseline) |
| E31 | `tests/unit/test_control_assignment_separation.py`: build an `AccessContext` with no role capabilities, every matrix and legacy relationship code in `character_capabilities` for one character, a non-empty `control_assignments` and a `control_clock_key`, and wrap it in an `AuthoritySnapshot`. `route_capability_requirement(capability_code="canon.edit", …)` and `canon_edit_requirement` both refuse, and `has_capability(code)` with no target is false for every matrix code. With `canon.edit` in `role_capabilities` both pass. Their result is identical for every combination of `control_assignments`, `control_clock_key` and `character_capabilities` | unit (capability separation) | fails (no control fields) |
| E32 | `tests/database/test_control_assignment_clock_routes.py`: spy on `AuthorizationPlan.finalize`. For advance, correct and world-times, keyed and unkeyed, the requirement names are exactly `["route.canon.edit", "campaign.canon.edit"]`. None sets `perspective`, `world_id`, `reveal`, `gm_subject` or `account` | behavioral (requirements) | **guard** |
| E33 | Same file: the clock writer's own final check. A GM, with `canon.edit` from the role, holds a dated assignment `[t1, t2)` and an upcoming dated assignment `[t2, ∞)` on two characters, with the clock at t1. Advance to t2 returns 200. The finalize snapshot (spied) has `control_clock_key` = key(t2), the first assignment absent from `control_assignments` and the second present. The clock, event and audit rows are committed. Correct back to t1: 200, with the snapshot reversed. When the GM's role lapses before the final statement (the `test_r01_s4_operation_routes.py:364` pattern), correct and advance are refused and persist nothing, whatever assignments are in effect | behavioral (own decision) | fails (no control fields) |
| E34 | Same file: another member's assignments follow the routes. Member P has the two dated assignments of E33.<br>- With no clock: both undetermined (absent).<br>- First advance to t1, which creates the clock row: the first in effect.<br>- Advance to t2: the first ended, the second in effect.<br>- Correct to t1: the first again.<br>- Creating a world time between t1 and t2 through the route changes neither `control_assignments` nor `control_clock_key`.<br>- An ongoing assignment of P is in effect throughout. | behavioral (route effect) | fails |
| E35 | Same file: no new wait. An advance runs uncommitted on connection A, holding the clock row `FOR UPDATE`. On B, under `SET LOCAL lock_timeout = '2s'`, `read_authority_snapshot` completes without `LockNotAvailable` and returns the committed `control_clock_key`, while A's own snapshot returns the new key. After A commits, B returns the new key | behavioral (concurrency) | fails (no `control_clock_key`) |
| E36 | Unchanged, apart from the permitted CTE-name adaptation: `test_r01_s4_operation_routes.py`, `test_api_campaign_clock.py`, `test_api_clock_cause.py`, `test_api_world_time.py`, `test_campaign_clock_concurrency.py`, `test_world_time_concurrency.py`, `test_r01_e2_perspective_snapshot.py` (its clock cases still equal the Python resolver), `test_r01_e2_ai_routes.py` and both existing reader tests in `test_r01_authorization_structure.py` | **guard** | passes |
| E37 (added 2026-11-26, A5a guard) | `tests/unit/test_player_profiles_structure.py::test_the_controller_profile_codes_appear_only_in_the_control_assignment_matrix`, exactly as section 3.2 item 1a states: confined to the matrix declaration, set elements only, two matrix readers, nothing under `database/`. `test_character_player_profiles_schema.py::test_no_controller_profile_capability_exists_yet` passes unchanged beside it | structural (scope transition) | fails: no matrix declaration. A5a's original test passes at the baseline and fails on the draft; that failure was the stop |

**Test-first evidence.** Write each task's cases first and run them at that task's baseline. Record which fail as designated and which pass as guards. A case that fails for a reason of the test itself is corrected in the test, never by changing the expectation; record that.

## 7. Verification

From `C:\Users\nemes\dnd_ai` (PowerShell; the local PostgreSQL 18 server and `.env` as for focused runs):

1. Focused:
   - T01: `uv run pytest tests/database/test_control_assignment_storage.py tests/database/test_control_assignment_migration.py -q`, plus every existing test file that touches the table. Find them with `rg -l "membership_character_relationship|make_membership_character_relationship|character-relationships" tests`. The search covers the R01 relationship files; run these explicitly as well: `test_r01_s5e4_access_grants.py`, `test_r01_s5e4_access_races.py`, `test_r01_s5e3_end_membership.py`, `test_r01_s5e3_end_races.py`, `test_r01_s5e3_end_interactions.py`, `test_r01_s5f_keyed_cross_family_races.py`, `test_api_access_grants.py` and `tests/unit`. G3 also needs `uv run pytest tests --collect-only -q` with no errors.
   - T02: adds `test_control_assignment_resolution.py`, `tests/unit/test_control_assignment_matrix.py`, `test_access_snapshot_differential.py`, `test_api_effective_access.py`, `test_api_access_overview.py`, `test_api_party_roster.py`, `test_character_relationship_concurrency.py`, `test_r01_s5e3_end_membership.py`, `test_supersession_publish_preconditions.py`, and the files the same search finds. *Added 2026-11-26:* `tests/unit/test_r01_authorization_structure.py`, `tests/unit/test_control_assignment_separation.py`, `tests/database/test_control_assignment_clock_routes.py`, and the E36 files. *Added 2026-11-26 (A5a guard):* `tests/unit/test_player_profiles_structure.py` and `tests/database/test_character_player_profiles_schema.py`.
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
| M11 (T01, added 2026-11-26) | Remove `_OUTSIDE_ASSIGNMENT_INDEXES` from `GRANT_RELATIONSHIP_INSERT` | G3: collection fails with `needs a UniqueWait` (Core) |
| M12 (T01) | Remove the two new `_leaves_index` entries from `END_REVOKE_RELATIONSHIP` | G3: the end-membership live-catalogue test. The module still imports, which records that only the live check counts predicate columns |
| M13 (T01) | Remove `campaign_id` and its FK binding from `CHANGE_RELATIONSHIP_INSERT` | G3: the access-grants live-catalogue test (`omitted NOT NULL column campaign_id`) |
| M14 (T01) | Drop `is_control_assignment` from the live-primary index predicate (migration and Core both, so the database tests run) | G1 (live-primary, INSERT ids) and D11b |
| M15 (T02, added 2026-11-26) | Remove `campaign.timeline_clocks` and `core.world_times` from `REVIEWED_POST_WRITE_TABLES` | The existing disjointness test, naming exactly the three clock routes; E29 |
| M16 (T02) | In a byte-restored copy of `tests/r01_route_manifest.json`, add `campaign.timeline_clocks` to the `command_writes` of `POST /campaigns/{campaign_id}/sessions/{session_id}/start` | E30. The disjointness test still passes, which records that the table-wide class alone would admit the writer |
| M17 (T02) | Make a targetless `has_capability` also consult the union of `character_capabilities` | E31 |
| M18 (T02) | Make `campaign_clock` and `asgn` opt-in again (present only with `with_perspective`) | E28 and E3 or E5 |
| M19 (T02) | Remove `core.world_times` from `AUTHORITY_READER_TABLES` | The existing reader-equality test |
| M20 (T02, A5a guard, added 2026-11-26) | Add a module-level `CONTROLLER_PROFILE_READ: Final = "character.view_player_profile"` to `domain/access.py`, outside the matrix declaration | E37, naming `domain/access.py` and the line. E27 still passes, which records that `domain/access.py` has no blanket exemption and that E27 alone would not catch this |
| M21 (T02) | Add `_CONTROLLER_READ = "character.view_player_profile"` to `queries/player_profiles.py` | E37 (E27 still passes: `queries` is outside its scope) |
| M22 (T02) | Append a comment line with a quoted `character.edit_player_profile` to one seed file | E37, naming the seed |
| M23 (T02) | Create a temporary file under `database/migrations/versions/` containing a quoted code, then delete it | E37, naming the file (A5a checked only migration 147) |
| M24 (T02) | Add a comment with a quoted code inside the `_CONTROL_ASSIGNMENT_SET` declaration | E37 (the match count no longer equals the set elements) |
| M25 (T02) | Import `CONTROL_ASSIGNMENT_CAPABILITIES` into `queries/player_profiles.py`, with no literal | E37 (the matrix readers) |

## 8. Authorization, disclosure, isolation and outcomes

- **Authorization.** An assignment confers only the closed matrix, and only while in effect, in its own campaign. It confers no campaign capability, no perspective and no private or narrative read. Denies win (§2.9). The legacy matrix is unchanged.
- **Disclosure.** The new explanation source names the role, kind and character, which the caller already discovers through the assignment. Nothing new reaches any other member. Legacy commands refuse assignment ids with the existing non-disclosing 404.
- **Isolation.** `campaign_id` is denormalized, verified and immutable; resolution also requires `campaign_id = :campaign_id`. Two campaigns on one timeline never share an assignment (E7, D13).
- **One clock per decision.** The clock is resolved inside the single authority statement and exposed as `control_clock_key`. The D4-C roster's party-membership test still uses its own membership clock read. That test is not a control decision, and the residual is recorded (section 10, R-6). *Added 2026-11-26:* the clock routes' own final statement reads the request's uncommitted clock, so their `control_clock_key` is the post-write value; none of their requirements reads it (E32, E33). A concurrent clock change is seen only once committed (E35; R-16).
- **Draft preservation, retry identity, refusals, unknown outcomes, navigation, focus, announcements.** Not applicable: S01 has no route, command or user interface. These are planned for the writers in S02.
- **Late responses.** Not applicable (no client).

## 9. Intermediate states

- After T01 and before T02: the columns and indexes exist; no writer exists; legacy readers would misread an assignment row, but only tests create one. T02 must land, and S01 must be independently reviewed, before S02 exposes any writer (S02's stated prerequisite).
- After T02: assignments resolve correctly, but nothing creates them until S02-T01.

## 10. Decisions (routine; recorded)

- **R-1, storage form.** Kind is TEXT with a CHECK, following migration 141's `end_reason`. The ADR names a "lookup value"; a two-value closed set with no display metadata does not need a lookup table. No ENUM.
- **R-2, index name kept.** The replaced legacy index keeps `ux_membership_character_relationships_active_type`, so its existing R01 `UniqueWait` entries stay valid. *Amended 2026-11-26:* keeping the name was necessary but not sufficient. The two new unique indexes, the omitted `NOT NULL` column and the changed trigger also reach the five R01 declarations on the table (R-10).
- **R-3, trigger fills `campaign_id`.** Unguarded insert paths, factories and seeds need no change. *Amended 2026-11-26:* the two R01 INSERT steps supply it explicitly (R-10).
- **R-10, R01 relationship declarations (2026-11-26).** Correct the five declarations as section 3.1 item 9 states, and change neither checker:
  - Every new `UniqueWait` entry states what the step really does: never enters the index (G1), or leaves it (G2).
  - Each is backed by behavioral evidence. G1-control shows that the G1 harness can detect a wait.
  - Rejected alternatives:
    - adding entries only to satisfy collection (nominal);
    - excluding indexes by predicate in the Core or live checker (general predicate analysis, which would weaken a checked guarantee);
    - accepting trigger-filled `NOT NULL` columns in the live checker (trigger analysis);
    - making `campaign_id` nullable (contradicts ADR §2.2).
- **R-11, `is_primary` on every row.** Derived from the type for legacy rows too (section 3.1 item 2; ADR §2.3). Readers pair it with `is_control_assignment`.
- **R-12, CHECKs not in Core.** This follows the package convention (`persistence/tables/__init__.py:22-25`). Tests cover them; neither autogenerate nor R01 depends on Core CHECKs.
- **R-13, always-on assignment resolution (2026-11-26).** Assignment and clock resolution is part of the base statement on every call, not an opt-in. Rejected alternative, explicit opt-in (for example `with_control`):
  - every early-check and final-check path that can consult a character capability would have to opt in. That is the `require_campaign_capability` dependency (146 route uses), `resolve_access_context`'s nine direct callers, the 33 character-targeted `has_capability` calls, and the character-targeted final-check requirements, such as `view_tier_requirement` in `character_public_profile.py`;
  - an omission is silent. It drops the matrix rights from discovery, reads and final checks without an error, and lets an early check and its final check disagree;
  - a test against omission would itself have to enumerate every consumer, which is a larger and weaker guard than E28–E31.

  An opt-out only for the clock routes inverts the same risk and still needs the review in item 3a, so it is rejected too. Cost: the base statement gains one small recursive CTE over the campaign's timeline chain, no lock and no second statement (E13, E35).
- **R-14, reviewed clock class (2026-11-26).** `campaign.timeline_clocks` and `core.world_times` join `REVIEWED_POST_WRITE_TABLES`, with the argument, inventory and tests of section 3.2 item 3a. `campaign.timelines` joins the reader constant only. The class is table-wide because the existing mechanism is. E29, E30 and E32 narrow it in effect to the three reviewed routes and their two role-only requirements, without changing the existing disjointness test.
- **R-15, constant accuracy (2026-11-26).** The constant names every table the base statement reads. The opt-in perspective-only tables (`campaign.campaign_parties`, `campaign.party_memberships`) stay outside it, as today: no post-write family route registers a perspective requirement, and E32 pins that for the clock routes. This plan does not widen that pre-existing scope.
- **R-16, concurrency residual (2026-11-26).** No lock is added: the snapshot reads the clock by MVCC. A request authorized by an assignment that a concurrent clock change ends may commit after that change if its final statement ran first (R-D1). No route consumes the control codes in C11 (E27). C20 decides, in its own plan, whether controller operations share-lock the clock row, and it must review item 3a's inventory if any of them writes a clock table.
- **R-4, safe downgrade.** The downgrade refuses while assignment rows exist instead of deleting them or letting them become privileged legacy rows.
- **R-5, matrix merge.** In-effect assignment capabilities merge into `character_capabilities`, so every existing consumer (`has_capability`, discovery, denies) applies them. The source is kept separately for explanations and the roster.
- **R-6, roster clock.** The roster's party-membership predicate keeps its own clock read; only the control half uses the snapshot's clock.
- **R-7, profile and operation codes.** They are in the matrix as the ADR states, with no vocabulary row and no consumer until C12 and C20 (E27 pins this).
- **R-17, A5a's guard is a scope fence, narrowed (2026-11-26).** A5a's "no controller vocabulary" test enforced A5's boundary ("A5 adds no … vocabulary, matrix entry or grant path. These belong to P03-B"). It was not an architectural rule: the A5 design gives the matrix to P03-B, and ADR 0021 §2.5 item 2 lists the codes. Section 3.2 item 1a narrows it to the matrix declaration. The alternative, renaming the codes or building them from fragments to evade a regular expression, would keep the test green while it detected nothing, so it is rejected. Exempting `domain/access.py` as a whole is rejected too, because it would admit a consumer beside the matrix (M20).
  - **No operational adoption.** At plan time (draft tree, 2026-11-26) the codes reach no decision:
    - the only `src` occurrences are the two set elements and a backticked docstring mention in `domain/player_profiles.py`;
    - no route, dependency, requirement, `has_capability` call, grant catalogue, deny list or seed names them, and `security.capabilities` has no row for them;
    - the read rule consults only `has_effective_character_canon_edit`;
    - the generic consumers of `character_capabilities` each test their own named codes: discovery (`world_explorer.py:116`, the discover codes), bootstrap (`character.view_knowledge`) and `has_capability` itself (exact code membership).
  - **Display only.** The effective-access explanation lists all eight matrix codes as held through `control_assignment`. Lacking a vocabulary row, the two profile codes display as their codes. That describes what the resolver holds; it is not an authorization input and discloses no profile content. C12 adds the rows and their display names.
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

**T01 continuation after the 2026-11-26 amendment** (the worktree holds the draft; section 11.3):
1. Confirm HEAD is still `7281d6c84b5f4767a94f323acf2adf12b7ce6077` and equals `origin/phase15/completion`. Confirm the worktree holds exactly the draft files listed in section 11.3, plus this amended plan, and nothing else. Do not reset, clean or recreate the draft.
2. Commit this plan amendment alone first (stage only this file) as `docs: amend the P15-C11-S01 plan for the R01 relationship declarations (P15-C11-S01-T01)`. Push it.
3. Test first, for the added cases. Write D11b, D21, G1, G1-control, G2's two ids and G4, and move `make_control_assignment` to `tests/factories.py`.
   - **Baseline run:** run the added cases at `7281d6c` in a temporary detached worktree (`git worktree add --detach <scratch path> 7281d6c…`, with the new and changed test files copied in), then remove that worktree. The main worktree is never reset or stashed. Each case is expected to fail because the columns are absent.
   - **Draft schema, before item 9:** run G1, G1-control, G2 and G4 in the main worktree with a temporary, byte-restored copy of the two plan modules that only lets them import. G1, G1-control and G2 are expected to pass already, because they test the schema's wait behavior, not the declarations. G3 is expected to fail.
   - Record every result. Never commit the temporary copy.
4. Make the section 3.1 item 9 changes and the name fix in item 4, then the documentation in item 8.
5. Run the section 7 focused set (T01, including G3), then one full shard run and the non-pytest checks.
6. Run M1–M3 and M11–M14, restoring bytes and comparing hashes.
7. Commit the implementation with the T01 subject (unchanged) and push. Then commit and push the records (section 11.3 and the T01 register row).

**T02**
1. Revalidate:
   - HEAD equals origin and the worktree is clean;
   - T01's records commit `34215f242ac3f2b110b541d4a5e78718bc80da91` and the T02 amendment commit after it are present;
   - section 2.1's reader list still matches. Run `rg -n "membership_character_relationships" src` and stop if a new production reader appears that section 3.2 does not cover;
   - (2026-11-26) the "R01 reader tables" row of section 2.1 still holds: the constants' contents, the 156-route pin, and the three clock-table writers and their requirements.
2. Write E1–E37 first; run them at the baseline and record fails and guards (E11, E14, E20's revocation part, E21, E27, E30, E32 and E36 are guards).
3. Implement section 3.2 only, including items 1a and 3a and the item 5 documentation.
4. Run the section 7 focused set (T02), full shards and non-pytest checks.
5. Run M4–M10 and M15–M25.
6. Commit with the T02 subject and push, then record and push the records commit.

**Permitted test adaptations (each named in the record):**
- a test that pins the Alembic head revision;
- schema-comment and table-inventory tests that enumerate columns or indexes;
- the D4-C structural test, if it pins the function body rather than its single caller;
- `tests/access_reference.py` **only** if the differential corpus has to include an assignment row, which it should not;
- (T01, 2026-11-26) the two new ids and their competitor branches in the end-membership "leaves" test (G2), and moving `make_control_assignment` into `tests/factories.py`;
- (T02, 2026-11-26) `test_r01_e2_perspective_snapshot.py::test_one_statement_no_row_lock` asserting the CTE name `campaign_clock` instead of `perspective_clock`. The single-statement and no-row-lock assertions stay, and so does every other line of that file. The clock-only prototype broke no other test in the files it ran (section 11.3);
- (T02, 2026-11-26) the docstring of the disjointness test naming the clock class. Its code, family set and route-count pin stay unchanged;
- (T02, 2026-11-26, A5a guard) in `tests/unit/test_player_profiles_structure.py`, replacing `test_no_controller_capability_vocabulary_exists_in_the_application_or_the_seeds` with E37 exactly as section 3.2 item 1a states, and adjusting the module docstring's vocabulary clause. The record names the old and new test ids. No other test in that file, and no other A5 test, changes.

- (T02, 2026-11-26, schema-version boundary; owner-authorized after the third stop) in `tests/database/test_control_assignment_migration.py::test_d17_d18_upgrade_preserves_legacy_rows_and_access_contexts`: T02's production resolver reads revision-150 columns (`is_control_assignment`, `campaign_id`, `assignment_period_kind`, `effective_period`), so it cannot run against the revision-149 database that D18's "before" side uses. The test reads the revision-149 side with `tests/access_reference.reference_resolve_access_context` (the frozen pre-R01-S1 multi-statement resolver: it names no revision-150 column, shares no SQL with the production statement and reads the database state itself) and the post-upgrade side with the production `resolve_access_context`. It compares the legacy access fields explicitly (`user_id`, `campaign_id`, `campaign_membership_id`, `timeline_id`, `role_capabilities`, `character_capabilities`, `grant_effects`, `campaign_lifecycle_status`, `revelations`) and does not compare the additive control fields, which it asserts empty instead. It asserts the expected non-empty legacy capabilities on both sides (live, open-ended dated and own-timeline rows confer their built-in sets; revoked, expired, closed-period and other-campaign rows confer nothing) and the refusal of a member of campaign Two in campaign One, so two empty or equally wrong contexts cannot pass. It runs under `real_relationship_policy`, so the reference and production sides apply the same policy. D17's stored-row assertions are unchanged. The reference resolver, production code and every other test are unchanged. A mutation of the production resolver's legacy semantics (dropping the closed-period exclusion) fails this test (MD18).

No other expectation changes. The section 3.1 item 9 edits are production changes authorized by this plan, not test adaptations.

**Stop conditions:**
- an API route, command writer or portal change becomes necessary;
- any legacy guard (D12, D16, E11, E14, E20, E21) fails;
- an R01 declaration changes beyond section 3.1 item 9 (the five relationship steps, `RELATIONSHIP_TRIGGERS` and its two subsets, and the two call sites' `campaign` bind);
- `domain/authorization_steps.py` or `tests/r01_pre_write_catalogue.py` would have to change, or a lock would have to be added, removed or reordered;
- after item 9, either live-catalogue test reports any problem, or another declaration's does;
- G1-control does not raise `LockNotAvailable` (the harness cannot observe a unique wait), or a G1 or G2 case shows a wait the declaration does not describe;
- any existing grant, change, revoke or end-membership route test changes outcome;
- a production reader of the table outside section 3.2 appears;
- the single-statement property cannot be kept;
- (T02, 2026-11-26) any of the following:
  - a post-write route other than the three in section 3.2 item 3a writes `campaign.timeline_clocks` or `core.world_times`, or any post-write route writes `campaign.timelines`;
  - one of the three registers any requirement besides `route.canon.edit` and `campaign.canon.edit`;
  - the reader constant must name any table besides the three, or the reviewed set must gain any table besides the two;
  - `test_r01_authorization_structure.py`'s existing reader or disjointness test needs a change beyond its constants and the named docstring;
  - E35 shows a wait;
  - E33 shows a clock route refused, or a decision changed, by its own clock write;
  - the perspective results in `test_r01_e2_perspective_snapshot.py` change;
- (T02, 2026-11-26, A5a guard) any of the following:
  - E37 can pass only with a wider exemption than section 3.2 item 1a (another module, another declaration, a file-wide exemption, or codes built to evade the pattern);
  - a module other than the two matrix readers needs `CONTROL_ASSIGNMENT_CAPABILITIES`;
  - a profile code would need a `security.capabilities` row, a seed, a migration, a grant or deny catalogue entry, or a consumer;
  - `test_no_controller_profile_capability_exists_yet` or the read-rule identifier test fails;
  - any of M20–M25 passes E37;
- the ADR contract appears to need changing.

Report and stop; do not adapt the contract.

No PR, no S02 work, no consumers, no browser/AX checks, no acceptance.

### 11.2 Independent review boundary

The plan commit through T02's records commit. The review includes the compatibility review the C11 criteria require: legacy rights, the legacy index name and semantics, and every reader in section 3.2 item 4 for legacy rows. It also covers the section 3.2 item 1a scope transition of A5a's guard (R-17).

### 11.3 Implementation record

**T01 stop (Sonnet, 2026-11-25; recorded by Opus, 2026-11-26).** Baseline `7281d6c84b5f4767a94f323acf2adf12b7ce6077`. Sonnet's uncommitted draft:
- `database/migrations/versions/150_control_assignments.py` (new);
- `src/dnd_ai/persistence/tables/security.py`;
- `tests/database/test_control_assignment_storage.py` and `tests/database/test_control_assignment_migration.py` (new);
- `docs/DOMAIN_MODEL.md`, `docs/architecture/DATABASE_MODEL.md` and `docs/reference/tables.md`.

Its evidence as reported, preserved here:
- **Test first:** 20 of 22 cases failed at the baseline (17 storage cases on `UndefinedColumn`; 3 migration cases on the absent revision). D12 and the pre-change part of D16 passed as guards.
- **After the draft:** 21 implemented cases pass (D1–D20 and D16b).
- **Not yet run:** broader collection is blocked, so there is no focused-set, full shard, non-pytest or mutation evidence.

Sonnet stopped on "an R01 declaration other than the named index changes". The two new unique indexes in Core metadata make `WriteStep` validation raise at import for `insert_relationship` (`…_live_primary needs a UniqueWait`), which breaks collection of 47 test modules.

**Opus investigation (2026-11-26; no commit, every experiment byte-restored and hash-checked).**
- *Core check, reproduced.* `import dnd_ai.commands.access_grant_plans` raises for the INSERT steps. `membership_end_plans` imports, because Core counts index key columns only and the revoke steps set only `revoked_at`.
- *Live check, observed.* A temporary copy that only lets the module import (placeholder waits on the two INSERT steps) left exactly two failing live-catalogue tests out of 41 catalogue tests. Every problem was on the five relationship steps:
  - the three UPDATE steps lack waits for both new indexes, because `revoked_at` is a predicate column under `pg_depend`;
  - both INSERT steps omit `NOT NULL campaign_id`, which has no default;
  - the scope trigger's pinned hash no longer matches;
  - the new `tr_membership_character_relationships_enforce_immutable` is unpinned on the UPDATE steps.
- *Proposed correction, validated.* Section 3.1 item 9, applied temporarily in full:
  - `pytest tests --collect-only` collected 11,390 tests with no error;
  - all 41 catalogue tests passed;
  - the focused R01, access-grant, storage and unit run is recorded below.

  Both plan modules were restored byte for byte (SHA-256 `4923b21c…` and `bde46b5d…` before and after).
- *Draft findings outside the stop.*
  - The 64-byte FK name (section 3.1 item 4).
  - `tables.md` still states revision head 149 and lists columns in a disposition row (item 8).
  - The local factory (section 6).
  - D16 exercises only the unguarded commands; G4 adds the R01 route paths.

*Focused run under the prototype* (local PostgreSQL 18, serial pytest; investigation evidence, not T01 verification):
- **First prototype:** `test_r01_s5e4_access_grants.py`, `test_r01_s5e4_access_races.py`, `test_r01_s5e3_end_membership.py`, `test_api_access_grants.py`, both draft storage files and `tests/unit` gave **89 failed, 2,713 passed, 5 skipped**.
  - 88 failures were in the grant and change routes. They were a `NameError` 500 from the prototype's own call-site edit (it named `campaign_id` inside the write functions).
  - The 89th was `tests/unit/test_config.py::test_local_session_allowed_origins_defaults_to_dev_topology_outside_production`. It also fails with no prototype applied, because the local environment's allowed-origins value contains an extra tunnel origin. It is environmental and unrelated to C11.
- **Corrected prototype** (`AccessPrepared.campaign_id`, as item 9.1 now states):
  - the four R01 and access-grant files gave **371 passed, 5 skipped**;
  - storage, migration and `tests/unit` gave **2,430 passed, 1 failed** (the same environmental `test_config` case).

  The plan modules were byte-restored after each run.
- **Not run:** a full shard run, the non-pytest checks and mutation probes. G1, G1-control, G2, G4, D11b and D21 do not exist yet.

**T01 implementation (Sonnet, 2026-11-26).**

- **Commits.** The plan amendment is `305588bc11af7591a9bd18223c82718dd4f2b22a`. The implementation is `5b5b22d3650f756e2477d5b504c18bae0caf50a2`. The records commit follows it. The baseline was `7281d6c84b5f4767a94f323acf2adf12b7ce6077` (HEAD and `origin/phase15/completion`, clean apart from the draft and the amended plans).
- **Files.** `database/migrations/versions/150_control_assignments.py`; `persistence/tables/security.py`; `commands/access_grant_plans.py` and `commands/membership_end_plans.py` (item 9 only); `tests/factories.py` (`make_control_assignment`, `relationship_type_id`); the storage and migration test files; `test_r01_s5e4_access_grants.py` (G1, G1-control, G4); `test_r01_s5e3_end_membership.py` (G2); DATABASE_MODEL, DOMAIN_MODEL, `tables.md`, ACCESS_CONTROL. No change to `domain/authorization_steps.py`, `tests/r01_pre_write_catalogue.py`, any other declaration, any lock or lock order, any route, command writer or portal file.
- **Test first.**
  - *Original cases, baseline `7281d6c`, before the draft:* 20 of 22 failed (17 storage cases on `UndefinedColumn`, 3 migration cases on the absent revision). D12 and the pre-change part of D16 passed as guards. 21 cases passed on the draft (D1–D20 and D16b).
  - *Added cases, temporary detached worktree at `7281d6c` (removed afterwards):* all 18 failed. D11b, the 8 G1 ids, the 2 G1-control ids, the 4 G4 ids and the 2 G2 ids failed on the absent columns (`is_control_assignment`, `campaign_id`); D21 failed on the absent revision.
  - *Draft schema with a temporary import-only copy of the two plan modules* (placeholder `UniqueWait`s on the two INSERT steps; SHA-256 `4923b21c…` and `bde46b5d…` before and after, restored byte for byte): D11b, G1 (8), G1-control (2), G2 (2 ids) and G4 (4) passed, 17 in all, as the plan expected. D21 failed because the 64-byte FK name was truncated. Both live-catalogue tests failed (G3). `pytest tests --collect-only` with the unmodified draft had failed with 47 collection errors (the stop).
  - No expectation was changed. No case failed for a reason of the test itself.
- **Implementation.** Section 3.1 items 1–9 as written: the migration (columns, backfill, trigger, CHECKs, indexes, comments, refusing downgrade), Core columns, foreign keys, indexes and comments (no CHECKs, R-12), `AccessPrepared.campaign_id` set by both prepare functions and bound as `prepared.campaign_id`, `_OUTSIDE_ASSIGNMENT_INDEXES` on the four access-grant steps, the two new `_leaves_index` entries on `END_REVOKE_RELATIONSHIP`, the re-pinned scope trigger, the new immutable pin and `RELATIONSHIP_INSERT_TRIGGERS` and `RELATIONSHIP_UPDATE_TRIGGERS`, the FK rename to `membership_character_relationships_revoked_by_fkey`, and the item 8 documentation.
- **Implementation details the plan left open.**
  - The scope function's campaign check is `ELSIF v_campaign_id IS NOT NULL AND NEW.campaign_id <> v_campaign_id`. The first version compared with `IS DISTINCT FROM`, and an UPDATE of a row whose membership no longer exists (left by tests that clean up with `session_replication_role = replica`) then raised, because the membership's campaign was NULL. The earlier checks of this function tolerate such rows. Two existing tests, `test_api_npc_authoring.py::test_a_published_npc_shows_players_identity_but_never_gm_notes` and `test_relationship_capability_defaults.py::test_revoking_the_relationship_removes_the_perspective_on_the_next_call`, failed in the first focused run with exactly that message and passed after the change. The pinned `md5(prosrc)` is `91065820eeab803c9a42a13511a93523` (the draft's first body was `75fe763b…`).
  - `is_primary` is derived and backfilled for every row (item 2, R-11), so D17 asserts it equals the type for legacy rows.
- **Permitted adaptations.** Two, both named in the plan: the two new ids and their competitor branches in the end-membership "leaves" test (G2), and the move of `make_control_assignment` into `tests/factories.py`. No test pins the Alembic head revision, and no schema-comment or table-inventory test needed a change.
- **Focused set (T01).** `pytest tests --collect-only`: 11,408 tests, no collection error (G3). Both `test_the_declarations_hold_against_the_live_catalogue` tests pass. After the final code, the storage, migration, access-grants and end-membership files together gave 287 passed, 5 skipped. An earlier serial run of the 68 files the section 7 search finds plus the R01 relationship files, `test_api_access_grants.py` and `tests/unit` gave 4 failed, 4,843 passed, 5 skipped. The 4 failures were:
  - `tests/unit/test_config.py::test_local_session_allowed_origins_defaults_to_dev_topology_outside_production`, which fails in this local environment with no C11 change (an extra allowed origin; reported, not changed). It passed in the shard run;
  - the two tests above, fixed as described;
  - `test_api_characters_inventory_only.py::test_a_revoked_grant_closes_the_inventory_again`: a blanket `UPDATE security.resource_grants SET revoked_at = now()` meets orphaned grants (their membership no longer exists) left in the shared session database by earlier tests, and `enforce_resource_grant_scope()` refuses. It fails identically, in the same file order, in a detached worktree at `305588bc` (the baseline code), so it is not caused by C11. It passed in the shard run.
- **Full shard run.** `uv run python scripts/run_sharded_tests.py`, on the final executable code (before the mutation probes, which were restored): **first run 11,401 passed, 6 skipped, 1 failed**, 11,408 collected and executed, 28m04s. The failure was `tests/database/test_r01_s5d_invitation_routes.py::test_a_revoke_that_holds_the_invitation_first_makes_the_acceptance_wait_then_refuses_it[unkeyed]` (shard 3): the gate was "not reached after 15.26s", with no backend non-idle. No cause is claimed. **Rerun, reported separately:** that test (both ids) alone passed, and the whole file passed (59 passed). No second full run was made.
- **Non-pytest checks.** `ruff format --check`, `ruff check`, `mypy src`, `uv lock --check`, `alembic check` (a freshly migrated throwaway database: no drift; one head, `150_control_assignments`), `scripts/check_documentation.py` and `git diff --check` all pass.
- **Mutation probes** (every edit byte-restored; SHA-256 of the five touched files compared before and after, identical each time):

| Probe | Failed (as required) |
|---|---|
| M1 | D11 (D12, the guard, still passed) |
| M2 | D10 |
| M3 | D1, D16, D16b |
| M11 | collection: `WriteStep 'insert_relationship': unique index …live_assignment needs a UniqueWait` (G3 Core) |
| M12 | the end-membership live-catalogue test; the module still imports |
| M13 | the access-grants live-catalogue test |
| M14 | D11b and G1 (`live_primary`, all four access-grant steps) |

- **Stop conditions.** None applied after the amendment. No legacy guard failed (D12 and D16 pass). No declaration other than item 9 changed. G1-control raised `LockNotAvailable` for both indexes. No route test changed outcome.
- **CI.** Pending the checkpoint PR. No browser or AX work.

**T02 stop (Sonnet, 2026-11-26; recorded by Opus, 2026-11-26).** Baseline `34215f242ac3f2b110b541d4a5e78718bc80da91` (HEAD and `origin/phase15/completion`, clean). Sonnet made no T02 change. Section 3.2 needs campaign-clock data (`campaign.timelines`, `campaign.timeline_clocks`, `core.world_times`) in the base single-statement reader. Naming them in `AUTHORITY_READER_TABLES` makes the post-write disjointness test flag advance, correct and world-times, and the plan did not authorize a reviewed-class change. Sonnet stopped on that.

**Opus investigation (2026-11-26; prototype evidence, not T02 verification).** No commit. Every temporary change was byte-restored: `domain/access.py` SHA-256 `14fe0374…78ae` before and after each run. The temporary probe test was deleted, and `git status` was clean afterwards.
- **Prototype.** Clock only, no `asgn`: today's `perspective_clock` SQL moved into the base statement as `campaign_clock`, exposed as a `control_clock_key` column, and the constant gained the three tables.
  - `tests/unit/test_r01_authorization_structure.py`: the reader-equality test passed with the +3 constant. The disjointness test failed with exactly three offenders: `POST …/clock/advance` and `POST …/clock/correct` (`campaign.timeline_clocks`) and `POST …/world-times` (`core.world_times`). 12 passed, 1 failed. That reproduces the stop.
  - **Adding `campaign.timeline_clocks` and `core.world_times` to the reviewed set** (not `campaign.timelines`): that file, `test_r01_s4_operation_routes.py`, `test_api_campaign_clock.py`, `test_campaign_clock_concurrency.py`, `test_api_world_time.py`, `test_access_snapshot_differential.py`, `test_r01_e2_perspective_snapshot.py` and `test_r01_e2_ai_routes.py` gave **281 passed, 1 failed**. The failure was `test_r01_e2_perspective_snapshot.py::test_one_statement_no_row_lock`, which asserts the CTE name `perspective_clock` (now a permitted adaptation). The perspective result cases all passed.
  - **Concurrency probe** (two connections, committed fixture of `test_campaign_clock_concurrency.py`): with an advance uncommitted on A, B's statement under `lock_timeout = '2s'` completed and returned the committed key, `144000`. A's own statement returned its uncommitted key, `432000`, and still held `canon.edit` from the role. After A committed, B returned `432000`. 2 passed.
- **Decision-path trace** for the three routes (entry, scope, locks, writes, final check) is summarized in section 2.1 and section 3.2 item 3a.
- **Not run:** `asgn`, the matrix, E1–E36, a full shard run, the non-pytest checks and mutation probes.

**T02 second stop (Sonnet, 2026-11-26; recorded by Opus, 2026-11-26).** The amendment commit `364e1074e71aea902334d07f1da7d35b378f80be` was HEAD and origin. Sonnet's uncommitted T02 draft was in the worktree, and Opus preserved it untouched: no reset, clean, stash or commit. As Sonnet reported it:
- E1–E35 pass on the draft.
- A focused and unit run gave 2,429 passed, with two failures:
  - `tests/unit/test_player_profiles_structure.py::test_no_controller_capability_vocabulary_exists_in_the_application_or_the_seeds` (offender `domain/access.py`);
  - the known environmental `tests/unit/test_config.py::test_local_session_allowed_origins_defaults_to_dev_topology_outside_production`.
- A baseline clock audit-count anomaly, which passed in isolation, remains **unexplained**.
- No full shards, final static checks, mutation series or implementation commit.

Sonnet stopped because the existing guard conflicts with section 3.2 item 1 and E25.

**Opus investigation (2026-11-26; prototype evidence, not T02 verification).** The investigation found that the guard is A5's scope fence and that nothing in `src` adopts the codes (R-17). Every temporary edit was byte-restored. SHA-256 before and after:
- `test_player_profiles_structure.py` `c896fd36…`;
- the draft `domain/access.py` `dda5bc72…`;
- `queries/player_profiles.py` `9d3544a3…`;
- `database/seeds/core.source_types.yaml` `6e00f366…`.

The temporary migration file was deleted, and `git status` showed the same 15 draft entries afterwards.
- **Reproduced:** A5a's test on the draft failed with `offenders = ['domain/access.py']`.
- **Narrowed guard (section 3.2 item 1a), temporarily in place of A5a's test.** That file plus `tests/unit/test_control_assignment_matrix.py` on the draft gave **250 passed**.
- **Test first:** with the 364e107 `domain/access.py` swapped in, the guard failed on "exactly one module-level matrix declaration".
- **`test_no_controller_profile_capability_exists_yet`** (database) passed on the draft.
- **Probes** (script numbering differs; mapped to section 7):

| Plan probe | Result |
|---|---|
| M20 | E37 failed (`domain/access.py:239`); E27 passed |
| M21 | E37 failed (`queries/player_profiles.py:23`); E27 passed |
| M22 | E37 failed (the seed path) |
| M23 | E37 failed (the temporary migration path) |
| M24 | E37 failed (match count) |
| M25 | E37 failed (matrix readers); E27 passed |

A further shape, a second module-level set that the matrix references and that holds an existing code, passed E37, E25 and E27. It declares no new code and stays inside the declaration rule, so it is an accepted shape, not a probe.
- **Not run:** E37 as committed test code, a full shard run, the non-pytest checks and the M4–M10 and M15–M19 series. The audit-count anomaly was not investigated here.

**T02 third stop (Sonnet, 2026-11-26; owner-authorized adaptation).** HEAD and origin `a7f813ca81e293d3e4648ce6804d25d599b242ed`. On the draft, with E37 in place, the first full shard run gave **11,470 passed, 6 skipped, 1 failed** (11,477 collected, 33m31s): `test_control_assignment_migration.py::test_d17_d18_upgrade_preserves_legacy_rows_and_access_contexts` (shard 4), `UndefinedColumn: mcr.is_control_assignment`, because the new resolver read a revision-150 column on the revision-149 database before the upgrade. That run is **not** relabelled as passing. The adaptation is the schema-version-boundary bullet of the permitted-adaptation list above.

**T02 implementation (Sonnet, 2026-11-26).**

- **Commits.** Original baseline `34215f242ac3f2b110b541d4a5e78718bc80da91` (T01 records). Plan amendments `364e1074e71aea902334d07f1da7d35b378f80be` (R01 reader classes) and `a7f813ca81e293d3e4648ce6804d25d599b242ed` (A5a guard narrowed to the matrix). Implementation `2cab2bd0a6771d027bd59e1e0c5c1e77cc28764c`, which also carries the schema-version-boundary adaptation and its plan amendment (owner-authorized after the third stop). The records commit follows it.
- **Files.** Production: `domain/access.py` (`CONTROL_ASSIGNMENT_CAPABILITIES`, `ControlAssignmentSource`, `AccessContext.control_assignments` and `control_clock_key`, the shared `CAMPAIGN_CLOCK_CTE` and `control_assignments_in_effect_from_sql`, the `rels` exclusion, the `asgn` CTE, `_PERSPECTIVE_CTES` removed in favour of `campaign_clock`, the two constants and their docstrings); `queries/effective_access.py`, `queries/access_overview.py`, `queries/content_preconditions.py`, `commands/access_grants.py`, `commands/access_grant_plans.py`, `api/parties.py`. No change to any lock or lock order, R01 declaration, route, manifest, `domain/authorization_steps.py`, `tests/r01_pre_write_catalogue.py` or the reference resolver. Tests: `test_control_assignment_resolution.py`, `test_control_assignment_clock_routes.py`, `tests/unit/test_control_assignment_matrix.py`, `test_control_assignment_separation.py` (new); E28-E30 in `test_r01_authorization_structure.py`; E37. Docs: ACCESS_CONTROL (section 3y, the R01 S6 reviewed-clock-class paragraph, the A5a sentence), DATABASE_MODEL section 19.7, this plan.
- **Permitted adaptations (each named).**
  1. `test_r01_e2_perspective_snapshot.py::test_one_statement_no_row_lock`: asserts the CTE name `campaign_clock` instead of `perspective_clock` (same test id).
  2. The docstring of `test_post_write_routes_write_none_of_the_readers_tables_except_the_reviewed_classes` names the clock class (same id; logic, family set and the 156-route pin unchanged).
  3. A5a guard: `tests/unit/test_player_profiles_structure.py::test_no_controller_capability_vocabulary_exists_in_the_application_or_the_seeds` is replaced by `test_the_controller_profile_codes_appear_only_in_the_control_assignment_matrix` (E37), and the module docstring's vocabulary clause is adjusted. No other test in that file changed. `test_character_player_profiles_schema.py::test_no_controller_profile_capability_exists_yet` is unchanged and passes.
  4. Schema-version boundary: `test_control_assignment_migration.py::test_d17_d18_upgrade_preserves_legacy_rows_and_access_contexts` (same id) reads the revision-149 side with `reference_resolve_access_context` and the post-upgrade side with the production resolver, compares the legacy access fields explicitly, asserts the expected non-empty capabilities and a refusal on both sides, asserts the additive control fields empty, and runs under `real_relationship_policy`. D17's stored-row assertions are unchanged. See the permitted-adaptation list in section 11.1 for the reasoning.
- **Test first.**
  - *E1-E36 at the baseline,* with a temporary import-only shim appended to `domain/access.py` (the matrix constant and the source dataclass only; SHA-256 `14fe0374…78ae` before and after, restored byte for byte). Three cases were corrected in the test itself, never in an expectation: E12 (it passed at the baseline because the legacy reading also confers discovery, so it now uses a dated assignment with an end), E22 (the member needed the player role for bootstrap to list the campaign) and E35 (the plan must be created after the transaction begins). Final baseline result: 28 database cases failed as designated (resolution and clock-route files), E28 and E29 failed, the 16 E31 ids failed on the absent control fields. Guards that passed: E11, E20 (revocation and slot), E21, E27, E30, E32 (6 ids), E33's two lapse cases. E25 and E26 passed only because of the shim (without it the modules do not import).
  - *E14 and the E36 files at the baseline* (shim in place): 290 passed, 1 failed. The failure was `test_api_clock_cause.py::test_an_identical_retry_replays_and_a_changed_input_conflicts` (`assert 16 == 2`, an audit-row count). That whole file passed alone (20 passed). **Unexplained; no cause is claimed.**
  - *E37:* run with `domain/access.py` replaced by `git show 34215f2:src/dnd_ai/domain/access.py`, it failed with "exactly one module-level matrix declaration"; restored (SHA-256 `dda5bc72…df068e` before and after); on the draft E37 plus the matrix tests gave 250 passed.
- **Focused and unit runs.**
  - *Draft before E37 (already reported):* 2,429 passed, 2 failed: the old A5a test (the stop) and the environmental `tests/unit/test_config.py::test_local_session_allowed_origins_defaults_to_dev_topology_outside_production` (an extra allowed origin; reported, not changed).
  - *Final code:* the 73 files of the section 7 set (the files the search finds plus the named R01, clock, E36, storage and migration files), `tests/unit` and `test_character_player_profiles_schema.py`: **5,113 passed, 5 skipped, 1 failed, 1 error** (22m12s). The failure is the same environmental `test_config` case. The error is `fixture 'app_read_write_engine' not found` for `test_character_player_profiles_schema.py::test_the_runtime_roles_can_read_the_profile_and_every_write_is_refused_by_the_database` in that combined invocation; that file alone passes (27 passed), and it passed in the full run. No cause is claimed for the combined-invocation error.
- **Full shard runs** (`uv run python scripts/run_sharded_tests.py`), reported separately:
  - *First run (draft with E37, before the schema-boundary adaptation):* **11,470 passed, 6 skipped, 1 failed**, 11,477 collected and executed, 33m31s. The failure was `test_control_assignment_migration.py::test_d17_d18_upgrade_preserves_legacy_rows_and_access_contexts` (shard 4): `UndefinedColumn: mcr.is_control_assignment`, because the new resolver read a revision-150 column on the revision-149 database before the upgrade. This is **not** a passing run and is not relabelled.
  - *Second run (final executable code, alone on the machine, sequential):* **11,471 passed, 6 skipped, 0 failed**, 11,477 collected and executed, 31m29s (shards 3,373 / 2,687 / 2,500 / 2,911 passed). The only difference from the first run is the D17/D18 test, which now passes.
- **Non-pytest checks** on the final code: `ruff format --check`, `ruff check`, `mypy src` (300 files), `uv lock --check`, `scripts/check_documentation.py` and `git diff --check` pass. `alembic check` on a freshly migrated throwaway database returns 0 (one head, `150_control_assignments`).
- **Mutation probes** (every edit byte-restored; SHA-256 of the touched files, the manifest and the migration directory listing compared before and after, identical each time):

| Probe | Failed (as required) |
|---|---|
| M4 | E1 (both roles) and E22 |
| M5 | E4. A first attempt, deleting only the `IS NOT NULL` test, **survived**: `NULL @> x` is already not true, so it is an equivalent mutant and not a kill. The recorded mutation treats a dated row with no clock as in effect |
| M6 | E5 (`equal-to-to`) |
| M7 | E6 |
| M8 | E18 (two cases) |
| M9 | E25 and E26 and E2 |
| M10 | E19 (`dated-with-end`) |
| M15 | the existing disjointness test (the three clock routes) and E29 |
| M16 | E30 (the disjointness test still passes, which records that the table-wide class alone would admit the writer) |
| M17 | E31 |
| M18 | E28 and E5 (`inside`) |
| M19 | the existing reader-equality test and E28 |
| M20 | E37 (E27 still passed) |
| M21 | E37 (E27 still passed) |
| M22 | E37 |
| M23 | E37 (the temporary migration file was deleted afterwards) |
| M24 | E37 |
| M25 | E37 (E27 still passed) |
| MD18 (added by the schema-boundary authorization) | D17/D18: dropping the closed-period exclusion from the production legacy `rels` read fails the comparison |

- **Stop conditions.** The third stop (the D17/D18 test) was authorized and resolved as stated. None other applied: no legacy guard failed, no declaration, lock or manifest changed, the reviewed set holds exactly the six tables and the reader constant exactly the three added, E35 showed no wait, E33 showed no refusal from the route's own clock write, the perspective results are unchanged, and no M20-M25 probe passed E37.
- **CI.** Pending the checkpoint PR. No browser or AX work.
- **Luna's S01 ranges.** T01 implementation with its plan amendment: `7281d6c84b5f4767a94f323acf2adf12b7ce6077` to `5b5b22d3650f756e2477d5b504c18bae0caf50a2` (amendment `305588bc11af7591a9bd18223c82718dd4f2b22a`), T01 records `34215f242ac3f2b110b541d4a5e78718bc80da91`. T02 implementation: `34215f242ac3f2b110b541d4a5e78718bc80da91..2cab2bd0a6771d027bd59e1e0c5c1e77cc28764c` (with the amendments `364e1074…` and `a7f813ca…`). Combined S01: `7281d6c84b5f4767a94f323acf2adf12b7ce6077..<T02 records SHA>`, covering legacy compatibility, the section 3.1 item 9 declarations, the section 3.2 item 3a reader classes and the item 1a A5a guard transition.

## 12. C11 checkpoint coordination

### 12.1 Order, prerequisites and shared files

- **Order.** S01-T01, S01-T02, then **S01 independent review**, then S02-T01, S02-T02. T02 depends on T01's columns. S02-T01 may not start before S01 is independently reviewed; that is S02's stated prerequisite ([register](work-register.md#p15-c11-s02)), not a scheduling choice. S02-T02 follows S02-T01 because it extends the same authority resolver and routes.
- **S02 planned ahead of its prerequisite.** The [S02 plan](p15-c11-s02-control-changes-plan.md) is prepared now. Its section 2 lists the S01 contracts it relies on. At S02-T01 start, Sonnet revalidates them against the reviewed S01 code. If an S01 correction changes one of them, S02 stops and returns to Opus.
- **Shared files.**
  - `src/dnd_ai/domain/access.py`: S01-T02 (matrix, `asgn`), S02-T01 (owner and GM authority CTE), S02-T02 (delegation source).
  - `src/dnd_ai/persistence/tables/security.py`: S01-T01; S02-T02 (delegation table).
  - `src/dnd_ai/commands/access_grant_plans.py`: S01-T01 (relationship declarations, section 3.1 item 9) and S01-T02 (refusing assignment ids). `src/dnd_ai/commands/membership_end_plans.py`: S01-T01 only. S02's writers declare their own steps on this table, so they reuse `RELATIONSHIP_UPDATE_TRIGGERS` and `RELATIONSHIP_INSERT_TRIGGERS` and the waits on the two assignment indexes.
  - `src/dnd_ai/domain/access.py` reader constants and `tests/unit/test_r01_authorization_structure.py`: S01-T02 (section 3.2 item 3a); S02-T02 adds its delegation table to `AUTHORITY_READER_TABLES` (S02 section 2.2 item 6).
  - Migrations: `150` (S01-T01), `151` (S02-T02). Each task revalidates the next free revision.
  - R01 registries and the generated manifest: S02-T01, S02-T02.
  - Docs: ACCESS_CONTROL, DATABASE_MODEL, tables.md, operations.md, this register.
  - Each later task revalidates its own baseline: HEAD equals origin, the worktree is clean, the previous task's records commit is present, and the plan's section 2 facts for its files still hold.

### 12.2 C11 checkpoint merge requirements

The C11 PR may merge only when all of these hold. They are the register rule; nothing is added.

1. S01 and S02 are each independently reviewed, including the compatibility review in the C11 criteria, with any corrections confirmed.
2. On the integration head, D1–D21 (with D11b and D16b), G1–G4 (with G1-control) and E1–E37 (this plan) and F1–F33 and H1–H22 ([S02 plan](p15-c11-s02-control-changes-plan.md#6-acceptance-cases)) pass, with:
   - one full backend shard run on the final executable code;
   - the non-pytest checks (`ruff format --check`, `ruff check`, `mypy src`, `uv lock --check`, `alembic check`, `git diff --check`).

   A portal run is required only if a portal file changed.
3. CI passes on that exact PR head.

### 12.3 Separate events (after the merge; not merge gates)

[actor-b](work-register.md#actor-b) (needs C12 and C20 too), [profile-authority](work-register.md#profile-authority), consumers using B's scope, browser and AX work for any later UI, `p15-integration` and `p15-owner`. None is granted by this plan.
