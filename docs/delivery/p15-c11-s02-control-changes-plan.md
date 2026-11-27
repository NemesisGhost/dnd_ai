# D/P15-C11-S02 implementation plan: change ongoing control

Owner register rows: [P15-C11](work-register.md#p15-c11), [P15-C11-S02](work-register.md#p15-c11-s02), [P15-C11-S02-T01](work-register.md#p15-c11-s02-t01), [P15-C11-S02-T02](work-register.md#p15-c11-s02-t02). Governing contract: [ADR 0021](../adr/0021-shared-actor-identity-control-and-authoring-responsibility.md) §2.4, §2.5 item 4, §2.6–§2.8 and §2.10 (owner-accepted); decisions OD-2, OD-4, OD-4a and OD-14; tests T1, T2, T3 and T5 (assignment parts), T25 (one-primary race, revoke against other writers, empty-set anchor), T78, T79 and T86 in [rules foundations §8](rules-foundations.md). Checkpoint order, shared files and merge requirements are in the [S01 plan, section 12](p15-c11-s01-assignment-storage-plan.md#12-c11-checkpoint-coordination).

Prepared by Opus, 2026-11-25. **Planned ahead of its stated prerequisite. Implementation may not start until [S01](work-register.md#p15-c11-s01) is independently reviewed.**

- Starting SHA `dabd7d1ab92a1575eb3769e539074ccbab34de8e`; plan-entry head `ebe6c7241a581cff1e2fac265a3af9230c656fa1` (C10 merge, fast-forward), as in the S01 plan.
- T01's baseline is the commit that records S01's independent review (with any confirmed correction), revalidated at start (section 11.1). T02's baseline is T01's records commit.
- CI: no run exists for C11.

## 1. Entry readiness and scope

**Prerequisite.** "P15-C11-S01 independently reviewed" is a stated prerequisite. This plan is prepared now because the checkpoint is planned as a whole. It relies on the S01 contracts listed in section 2.2. Revalidation against the reviewed S01 code is the first step of T01 (stop condition in section 11.1).

**Scope** (register criteria: "No implicit co-controller promotion, knowledge perspective or canonical edit right. Distinguish assignment delegation from reveal delegation."):
- **T01:** the three idempotent, audited commands and their routes, `assign_character_control`, `replace_primary_controller` and `revoke_character_control`, plus one read of a character's current control and history.
  - Authority: the new `character.assign_control`, held only by the built-in `campaign_owner` and `gm` roles (OD-4).
  - Explicit kind (OD-14), the ADR §2.8 lock protocol on the approved R01 class order, and history preservation.
- **T02:** the OD-4a delegation of `character.assign_control` to an assistant GM. It covers grant, revoke and read, the recipient's use of the T01 commands in that one campaign, no redelegation, and a strict separation from reveal delegation.

**Outside.**
- Controller operations and `lock_controller_operation_scope` ([P15-C20](work-register.md#p15-c20)).
- Player-profile editing ([P15-C12](work-register.md#p15-c12)).
- Legacy-row manifest and promotion ([P15-C13](work-register.md#p15-c13)): an assignment is never created from a legacy row automatically (ADR §2.10).
- Scheduled future hand-offs (ADR §2.3: not supported initially).
- Real-time expiry of control, a "who controlled at world time T" query route, and audit-history display of control changes.
- Any portal UI: consumers use B's accepted scope.

## 2. Current behavior and relied-on contracts

### 2.1 Source facts (at `ebe6c72`)

| Concern | Today |
|---|---|
| Writers of control | None. Legacy `grant_character_relationship` / `change_…` / `revoke_…` (`commands/access_grants.py`, `commands/access_grant_plans.py`; routes in `api/access_grants.py`) write legacy rows under `access.manage`. |
| Route machinery | Keyed pre-write routes register in `R01_PRE_WRITE_ROUTES` with `ReservationDeclarations`. Unkeyed ones register in `R01_UNKEYED_PRE_WRITE_ROUTES` (`api/r01_pre_write_routes.py`). `R01_FINALIZED_ROUTES` is generated (`api/r01_pending_routes.py`, `uv run python -m tests.r01_manifest`); `tests/unit/test_r01_pending_routes.py:124` pins 187 finalized routes. |
| Approved lock class order | World → role rows → delegation rows → memberships → accounts → campaign → catalogue rows → targets → dependent rows (`access_grant_plans.py` module docstring, S5-E2 C1–C4, S5-E4 AO-1). The relationship grant takes the target membership `FOR UPDATE`, accounts S/KS (S5-A), campaign `FOR UPDATE`, then the character entity `FOR UPDATE`. Administrative recovery now takes the promoted membership `FOR UPDATE`, then the campaign `FOR NO KEY UPDATE` (`commands/recovery.py:163`). |
| Built-in authority readers | `find_live_builtin_owner_assignment` and `find_live_builtin_gm_assignment` (`domain/access.py:1839,1876`); the reveal-authority CTEs in the single snapshot (`with_reveal`). |
| Delegation precedent | `security.character_reveal_delegations` (migration 141): bound to the grantee's specific built-in `gm` assignment row, one live row per grantee, `end_reason`, a guard trigger that refuses the capability in `role_capabilities`, `character_relationship_type_capabilities` and `resource_grants`, and unkeyed, naturally idempotent routes (`commands/reveal_delegation_plans.py`). |
| Built-in `assistant_gm` | Holds `campaign.view`, `canon.edit`, `character.view_full` (migration 086). It holds no assignment authority. |
| Operation catalogue | [operations.md](../api/operations.md) counts 349 operations; `scripts/check_documentation.py` requires one catalog row per registered method and path. |

### 2.2 Contracts S02 relies on from S01 (revalidate at T01 start)

1. The migration-150 columns, CHECKs, trigger behavior and the two new unique indexes, with their names (S01 section 3.1).
2. `CONTROL_ASSIGNMENT_CAPABILITIES`, the `asgn` CTE's in-effect rule, `AccessContext.control_assignments` and `control_clock_key` (S01 section 3.2 items 1–3).
3. Legacy readers exclude assignment rows, and legacy change and revoke refuse assignment ids (S01 section 3.2 item 4).
4. Membership end revokes assignment rows (S01 E20).
5. (Added 2026-11-26.) The R01 relationship declarations, as S01 section 3.1 item 9 left them.
   - `RELATIONSHIP_INSERT_TRIGGERS` and `RELATIONSHIP_UPDATE_TRIGGERS` pin the revision-150 scope trigger and the immutable-columns trigger.
   - Every step that writes `security.membership_character_relationships` must name `UniqueWait` entries for all three unique indexes on it.
   - S02's assignment INSERT really enters `…_live_primary` (primary only) and `…_live_assignment`. Its entries are therefore **competing** waits, each with its own race test (the `test_a_competing_active_relationship_of_the_same_type_is_a_unique_wait` pattern). They are not G1's "never enters" entries.
   - S02's revoke and replace UPDATEs leave those indexes (the G2 pattern).
   - An S02 INSERT supplies `campaign_id`, bound to the campaign lock it takes.
6. (Added 2026-11-26.) The R01 reader classes, as S01 section 3.2 item 3a left them.
   - The campaign clock and `asgn` are part of the base authority statement, with no opt-in. `AUTHORITY_READER_TABLES` includes `campaign.timelines`, `campaign.timeline_clocks` and `core.world_times`. `REVIEWED_POST_WRITE_TABLES` is exactly six tables (S01 E29).
   - S02's routes are pre-write (access management) and write no clock table. If an S02 route would write `campaign.timeline_clocks`, `core.world_times` or `campaign.timelines`, S01 E30 fails and S02 stops: it is never added to the clock inventory without an Opus review.
   - S02-T02's new `security.character_assign_control_delegations` table is read by the authority statement, so it joins `AUTHORITY_READER_TABLES` and is **not** a reviewed post-write class. No post-write route may write it (the existing disjointness test).
   - Capability separation: `AssignControlAuthority` (T01 and T02) never reads `control_assignments`, `control_clock_key`, the matrix or `character_capabilities`. An assignment never confers assignment authority (F33, beside S01 E31).
   - The step-10 re-judgment and `plan.finalize` read the clock without a lock. A dated assignment's in-effect status in the S02 read uses the same `campaign_clock` value as the decision's snapshot.

## 3. Changes

### 3.1 T01: assign, replace, revoke and read

**Authority.**
- A new snapshot component (opt-in, like `with_reveal`) returns the caller's `AssignControlAuthority`: `campaign_owner` or `gm` (the live built-in assignment row id), or `none`. T02 adds `delegation`.
- `access.manage`, `canon.edit`, custom roles, resource grants and control assignments never confer it. Assignment authority is not stored in `role_capabilities` (no vocabulary row in T01; T02 adds it with its guard).
- The route requirement is `campaign.view`. The operation authority is judged before any target lookup, so a refusal (403 `character_assign_control_required`, a fixed body) is identical for an existing and a missing character or assignment. That is the non-disclosing refusal T79 requires.

**Routes** (all under R01, `campaign_id` in the path):

| Method and path | Command | Keyed | Success |
|---|---|---|---|
| `POST /campaigns/{campaign_id}/characters/{character_id}/control-assignments` | `assign_character_control` | yes (optional `Idempotency-Key`) | 201 `{control_assignment_id}` |
| `POST /campaigns/{campaign_id}/characters/{character_id}/control-assignments/replace-primary` | `replace_primary_controller` | yes | 201 `{control_assignment_id, revoked_control_assignment_id}` |
| `POST /campaigns/{campaign_id}/control-assignments/{control_assignment_id}/revoke` | `revoke_character_control` | yes | 200 `{control_assignment_id, revoked}` |
| `GET /campaigns/{campaign_id}/characters/{character_id}/control-assignments` | read | — | 200 (below) |

**Request bodies.**
- Assign: `campaign_membership_id`, `role` (`primary_controller` or `co_controller`), `assignment_period_kind` (required: there is **no default**, OD-14), `effective_from_world_time_id` and `effective_to_world_time_id` (only for `dated`; start required, end optional), and an optional `reason`.
- Replace: the new primary's `campaign_membership_id`, its kind and period, and an optional `reason` recorded on the revoked row.
- Revoke: an optional `reason`.
- Every reason is 1–1000 characters when present.

**Refusals, in this order** (each writes nothing and no audit row):
1. The campaign route's own refusals.
2. 403 when there is no authority.
3. 422 for a malformed body: kind missing or unknown; `ongoing` with a world time; `dated` without a start; an end not after its start; a reason too long.
4. 404 for a character missing, of another world, or not active, and for a world time of another world. For revoke: an assignment id of another campaign, or a legacy relationship id.
5. 409 for an ineligible membership: ended, not active, another campaign's (404), or its account not active. Also 409 when the campaign is not active.
6. 409 `primary_controller_exists` when assigning a primary while a live primary row exists, including a dated one that has ended. Use replace.
7. 409 `control_already_assigned` when the assignee already holds a live assignment of either role on the character. That covers a replace that names a current co-controller or the current primary: no implicit promotion (OD-2).
8. 409 `no_primary_controller` for a replace with no live primary.

A revoke of an already revoked row returns 200 `revoked: false` and writes nothing.

**Writes.**
- Each writer is one transaction.
- Assign inserts one row (`is_control_assignment`, the kind, `granted_by_membership_id` = caller) and one `audit.change_log` row.
- Replace revokes the old primary (`revoked_at`, `revoked_by_membership_id`, `revocation_reason`), inserts the new row, and writes one audit row for each. Co-controller rows are untouched.
- Revoke sets `revoked_at`, `revoked_by_membership_id` and `revocation_reason`, and writes one audit row. It touches no co-controller and promotes nobody.
- A row is never edited in place otherwise.
- Audit rows hold no reason text; the reason stays on the row.

**Lock sequence.** This is ADR §2.8 mapped onto the approved R01 class order, never inverted. The ADR's "user row `FOR UPDATE`" becomes the S5-A account modes.
1. Keyed prefix: advisory key lock, reservation insert, actor account KS.
2. The caller's authority row (built-in owner or `gm` assignment) `FOR SHARE`.
3. Memberships, ascending id: the caller's `FOR SHARE`, and the assignee's (assign and replace) or the revoked row's membership (revoke and replace) `FOR UPDATE`.
4. Accounts: the caller's S, the target's KS.
5. `campaign.campaigns` `FOR UPDATE`.
6. The relationship type row (catalogue) KS.
7. The character's `core.entities` row `FOR UPDATE`. This is the stable anchor, taken even when no assignment exists, and the row future controller operations will share-lock.
8. The character's live assignment rows `FOR UPDATE`, bound to the discovered ids.
9. World-time rows KS (dated).
10. Then, at a fresh `clock_timestamp()` after the last wait: re-judge the authority, re-read the live assignment set under the anchor and compare it with the locked set (409 on a difference), and re-check eligibility.
11. Then `plan.finalize`, the declared writes, and the receipt.

Pin the sequence in the plan declarations and in the route-shape test. If any reproduced deadlock requires a different order, stop (section 11.1).

**Read** (`GET`, same authority, no locks, one snapshot):
- `controller`: the in-effect primary (membership id, display name, kind) or `null`;
- `co_controllers`: the in-effect co-controllers;
- `gm_operated`: true when no assignment is in effect (ADR §2.6: "controller: none (GM-operated)");
- `clock`: set or not, plus its display;
- `assignments`: every row for this character in this campaign, newest first, at most 200 with `truncated`. Each has its id, role, kind and membership. Ongoing rows read "ongoing since `granted_at`" and never carry a fictional date. Dated rows carry their period's displays. Each row carries a status (`in_effect`, `upcoming`, `ended`, `undetermined` (no clock), `revoked`), `granted_at`/`granted_by`, and `revoked_at`/`revoked_by`/`revocation_reason`. Status is derived from the same in-effect rule as S01's `asgn` CTE (a shared SQL fragment).
- *Clarified 2026-11-27 (correction S02-R1).* "One snapshot" means one SQL statement after the route's campaign gate. It embeds the authority statement (`build_authority_statement` with the assign-control component) and, in that statement:
  - reads the effective clock (`CAMPAIGN_CLOCK_CTE`) and the clock's display row;
  - reads every status (the shared fragment) and the history, with each period's display rows.

  The response's decision is judged from that statement's row, in the gate's refusal order. The history is read only when that statement's authority source is a holder's.

  The contract is statement coherence, not commit-time serialization: a change committed after the statement does not retract its response. No row lock is taken, and the response shape, ordering and the 200-row bound are unchanged.

**Documentation.**
- [identity-and-access.md](../api/identity-and-access.md) rows for the four operations, and the counts in [operations.md](../api/operations.md).
- An ACCESS_CONTROL subsection on assignment authority, refusals and the lock sequence.
- A note in DATABASE_MODEL §19.4.

### 3.2 T02: assistant-GM delegation (OD-4a)

**Migration** `151_assign_control_delegations` (revalidate the number):
1. **Capability row.** `security.capabilities` row `character.assign_control` ("Assign character control", sort order after `character.reveal`), vocabulary only.
2. **Guard trigger.** On `role_capabilities`, `character_relationship_type_capabilities` and `resource_grants`, refusing any row that names it. This is the migration 141 pattern, with names under 63 bytes.
3. **Table.** `security.character_assign_control_delegations`:
   - columns: `character_assign_control_delegation_id`, `campaign_id`, `grantee_campaign_membership_id`, `assistant_gm_membership_role_id` (the grantee's specific built-in `assistant_gm` assignment row, immutable), `granted_by_membership_id` (provenance, `ON DELETE SET NULL`), `granted_at`, `reason` (required, 1–1000), `revoked_at`, `revoked_by_membership_id`, `revocation_reason`, and `end_reason` in (`revoked`, `assistant_gm_assignment_lapsed`), plus timestamps;
   - CHECKs: closure consistency, revoker and reason only for `revoked`, `revoked_at >= granted_at`;
   - scope trigger: campaign, grantee, bound role row (which must be the built-in `assistant_gm` template's and belong to the grantee) and both actors in one campaign;
   - one live row per grantee (`WHERE revoked_at IS NULL`), plus indexes and comments.
4. **Grants.** As for the reveal-delegation table.
5. **Downgrade.** Lossy and documented, as 141: removing delegations only removes authority.

**Authority source.** The T01 component gains `delegation`. A delegation is in force only while all of these hold:
- it is unrevoked;
- its campaign is the route campaign;
- the grantee is the caller's active membership;
- the bound `assistant_gm` row is live (unrevoked, unexpired, the role active).

There are no lifecycle hooks. When the role ends, the delegation simply stops being in force, and a later re-grant of `assistant_gm` creates a new role row that the old delegation is not bound to. Losing the grantor's role does not affect it (provenance, ADR 0020 decision 7).

**Routes** (unkeyed pre-write, naturally idempotent, `R01_UNKEYED_PRE_WRITE_ROUTES`, following reveal delegations):

| Method and path | Command | Success |
|---|---|---|
| `POST /campaigns/{campaign_id}/assign-control-delegations` | `delegate_character_assign_control` | 201 created, or 200 when a live delegation is already bound to the grantee's current `assistant_gm` row (no write, no audit) |
| `POST /campaigns/{campaign_id}/assign-control-delegations/{grantee_campaign_membership_id}/revoke` | `revoke_character_assign_control_delegation` | 200 `{revoked}`; no live delegation is a no-op |
| `GET /campaigns/{campaign_id}/assign-control-delegations` | read | 200: live and closed rows, newest first, each with in-force status ("not in force: assistant GM role ended" for a lapsed binding), reasons and actors |

**Rules.**
- **Grantor and revoker.** A caller with a live built-in `campaign_owner` or `gm` assignment in this campaign. A delegated holder is refused 403: no redelegation. `access.manage` and custom roles are refused too.
- **Recipient.** An active membership of this campaign with a live built-in `assistant_gm` row. Otherwise 409 `assign_control_recipient_not_assistant_gm`; another campaign's membership is 404.
  - *Final-recipient instant (clarified 2026-11-27, correction S02-R2).* The recipient is judged again by `plan.finalize`'s one statement, after the grantor and at the same `t_auth`. That statement must find:
    - the membership of this campaign, open and active;
    - its account, active;
    - the bound built-in `assistant_gm` assignment, unrevoked, unexpired at `t_auth`, with its role active;
    - that assignment equal to the row the grant locked.

    The mechanism is an opt-in snapshot source declared by a requirement (`Requirement.assistant_gm_subject`, `AuthoritySnapshot.subject_assistant_gm_assignment`), the `subject_gm` predicate with the role code changed. The plain read after the last wait stays an early check. It is never the final word, and no other plain pre-finalization query substitutes for this check.

    Grantor checks, campaign binding, refusal order (grantor 403 before recipient 409), audit atomicity and the lock order are unchanged. This clarifies the existing eligibility rule and adds no scope.
- **Reasons.** Required on grant and on revoke (422 when blank or too long).
- **Lapsed rows.** A grant that finds a live row bound to a lapsed role row closes it (`end_reason = 'assistant_gm_assignment_lapsed'`) before inserting.
- **Revocation scope.** Revoking leaves every assignment the holder made unchanged and in force (T86).
- **Effect of a revocation.** The holder's next assign, replace or revoke is refused 403.

**Lock sequence** (class order; ADR §2.8 delegation row).
- **Grant:**
  - unlocked discovery of the caller's authority row and the grantee's `assistant_gm` row;
  - role class, ascending id: the caller's row S and the grantee's `assistant_gm` row U;
  - the 404 for a grantee of another campaign;
  - the grantee's delegation rows U;
  - memberships ascending: the grantee's `FOR NO KEY UPDATE` and the caller's KS;
  - `campaign.campaigns` `FOR UPDATE` (ADR step 2; it serializes with T01's writers);
  - after the last wait, at a fresh instant: re-judge the caller; confirm the grantee's live `assistant_gm` row is the locked row; confirm the live delegations equal the locked set.
- **Revoke:** the caller's role row S, the grantee's live delegation row U, the caller's membership KS, then the campaign U, re-judging after the waits.
- **T01 writers with delegation authority:** in the role class they take the bound `assistant_gm` row S, then the delegation row S (delegation class), before memberships. A revocation therefore either waits for an in-flight assign, or commits first and the assign is refused after its wait.

**Distinct from reveal delegation.**
- Reveal delegation: `character.reveal`, an owner grantor, a `gm` grantee, and its own table and routes.
- Assign-control delegation: `character.assign_control`, an owner or GM grantor, an `assistant_gm` grantee.
- Neither confers the other. Neither confers `access.manage`, `canon.edit` beyond the role's own, any controller operation or any character read. No shared table, function or route.

**Documentation.** Catalog rows and counts, the ACCESS_CONTROL OD-4a subsection, DATABASE_MODEL and [tables.md](../reference/tables.md) for the new table.

## 4. Files

| File | Task |
|---|---|
| `src/dnd_ai/commands/control_assignments.py` (new: direct commands, the oracle the route tests compare against) and `src/dnd_ai/commands/control_assignment_plans.py` (new: R01 declarations and lock/read/write phases) | T01 |
| `src/dnd_ai/api/control_assignments.py` (new router), `src/dnd_ai/api/app.py` (include it), `src/dnd_ai/api/r01_pre_write_routes.py`, generated `src/dnd_ai/api/r01_pending_routes.py` and `tests/r01_route_manifest.json` | T01, T02 |
| `src/dnd_ai/domain/access.py` (authority component), `src/dnd_ai/queries/control_assignments.py` (new read) | T01, T02 |
| `database/migrations/versions/151_assign_control_delegations.py` (new), `src/dnd_ai/persistence/tables/security.py`, `src/dnd_ai/commands/assign_control_delegations.py` and `…_plans.py` (new), `src/dnd_ai/api/assign_control_delegations.py` (new) | T02 |
| Tests: `tests/database/test_control_assignment_commands.py`, `…_api.py`, `…_concurrency.py`, `tests/unit/test_r01_c11_route_shape.py` (T01); `tests/database/test_assign_control_delegation.py`, `…_migration.py`, `…_concurrency.py` (T02) | T01, T02 |
| Docs: identity-and-access.md, operations.md, ACCESS_CONTROL, DATABASE_MODEL, tables.md (T02), this plan, the register | T01, T02 |

## 5. Commits and review boundary

- T01: `feat(api): assign, replace and revoke campaign character control (P15-C11-S02-T01)`, then a records commit.
- T02: `feat(api): delegate character.assign_control to assistant GMs under OD-4a (P15-C11-S02-T02)`, then a records commit.
- **Independent review range for S02:** T01's actual baseline through T02's records commit, including the C11 compatibility review: the legacy relationship routes, reveal delegations, membership end and recovery behave unchanged.

## 6. Acceptance cases

**T01 (F1–F33):**

| ID | Case | Baseline |
|---|---|---|
| F1 | The owner assigns an ongoing primary: 201, row fields, `granted_by`, one audit row named `assign_character_control` | fails (no route) |
| F2 | A GM assigns a dated co-controller with start and end; the period is derived | fails |
| F3 | Kind missing; `dated` without a start; `ongoing` with a world time: each 422, nothing written | fails |
| F4 | End not after start: 422 | fails |
| F5 | A world time of another world: 404, nothing written | fails |
| F6 | Assigning a primary while a live primary exists (ongoing; dated in effect; dated ended): 409 `primary_controller_exists` | fails |
| F7 | The assignee already holds a live assignment on the character: 409 `control_already_assigned` | fails |
| F8 | Ended, inactive or other-campaign membership; inactive account; inactive campaign: the stated 404/409 | fails |
| F9 | Character missing, of another world or archived: 404 | fails |
| F10 | `assistant_gm` without a delegation: 403 with the same body for an existing and a missing character; nothing written | fails |
| F11 | Player, observer, a custom role holding `access.manage` and `canon.edit`, and the character's primary and co-controller: each 403 (T78, T79) | fails |
| F12 | A non-member: the existing campaign 404 | **guard** |
| F13 | Replace P1 with P2: P1 revoked with revoker and reason, P2 inserted, two audit rows, co-controllers untouched, one transaction | fails |
| F14 | Replace with no live primary: 409 `no_primary_controller` | fails |
| F15 | Replace naming a current co-controller or the current primary: 409 `control_already_assigned`; the co-controller row is unchanged | fails |
| F16 | Revoke P1 with co-controllers C1 and C2: C1 and C2 stay live and in effect with the same capabilities; no primary; nobody promoted (T78) | fails |
| F17 | Revoking the last assignment makes the read report `gm_operated` | fails |
| F18 | Revoke of a revoked row: 200 `revoked: false`, no write, no audit | fails |
| F19 | Revoke of another campaign's assignment id or of a legacy relationship id: 404, nothing written | fails |
| F20 | A reason over 1000 characters: 422 | fails |
| F21 | Keyed retry of each writer after a committed response is lost: the identical receipt, no second row or audit; the same key with a different body gets the existing reuse refusal | fails |
| F22 | Two concurrent primary assigns for different members: exactly one 201, the other 409 `primary_controller_exists`; never 500 or a raw unique violation | fails |
| F23 | Revoke and assign on one character concurrently: serialized at the anchor; consistent outcome; no deadlock | fails |
| F24 | Assign against the assignee's membership end: either the assignment exists and the end revokes it, or the assign gets 409; never a live assignment on an ended membership | fails |
| F25 | Assign against a revoke of the caller's `gm` role: if the role revoke commits first, the assign gets 403 after its wait | fails |
| F26 | Assign against archive of the character: serialized at the entity row; never a live assignment on an archived character | fails |
| F27 | Deadlock matrix: each writer against the legacy relationship grant and revoke, membership end, role revoke, administrative recovery and archive on shared rows, repeated a bounded number of times: no `40P01` | fails |
| F28 | Read: current, co-controllers, `gm_operated`, clock, and history newest first. Ongoing rows read "ongoing since …"; dated statuses `in_effect`/`upcoming`/`ended`/`undetermined` follow the S01 rule at the boundaries; revoked rows show actor and reason; bounded with `truncated` | fails |
| F29 | Read by a non-holder: 403 with the same body for an existing and a missing character | fails |
| F30 | Campaign A's assignment confers nothing in campaign B on the same timeline, and B's read shows nothing (T1 assignment part) | fails |
| F31 | An NPC assigned to a player keeps its UUID, build and portrayal rows; no `view_private` or `view_knowledge` (T2). A character with no build or class is assignable and resolves (T3) | fails |
| F32 | An assignment made by the command resolves through S01 on the next request; after revoke the next request has none (T5 resolution part) | fails |
| F33 | (Added 2026-11-26; S01 section 3.2 item 3a separation.) Unit: an `AccessContext` holding every `CONTROL_ASSIGNMENT_CAPABILITIES` code in `character_capabilities`, live `control_assignments` and a `control_clock_key`, with no owner, `gm` or delegation source, yields `AssignControlAuthority` `none`. The authority component's SQL names none of the clock tables and no `asgn` output | fails (no component) |

**T02 (H1–H22):**

| ID | Case | Baseline |
|---|---|---|
| H1 | The owner delegates to an assistant GM with a reason: 201, bound to the `assistant_gm` row, one audit row | fails |
| H2 | A built-in GM delegates: success | fails |
| H3 | Reason missing, blank or over 1000: 422 | fails |
| H4 | Recipient without `assistant_gm`: 409 `assign_control_recipient_not_assistant_gm` | fails |
| H5 | Recipient of another campaign: 404; ended membership: 409 | fails |
| H6 | Grant by a custom `access.manage` holder, an assistant GM (delegated or not) or a controller: 403 | fails |
| H7 | A repeat grant while bound to the current role row: 200, no write, no audit | fails |
| H8 | The grantee's `assistant_gm` revoked: the delegation is no longer in force and the next assign is 403. The read says "not in force: assistant GM role ended". `assistant_gm` re-granted: still not in force. A new grant closes the lapsed row (`assistant_gm_assignment_lapsed`) and inserts | fails |
| H9 | The delegated assistant GM assigns, replaces and revokes in A, audited with the assistant GM as actor (T86) | fails |
| H10 | The same assistant GM is refused in campaign B (T86) | fails |
| H11 | The delegated assistant GM delegating to another assistant GM: 403 (no redelegation) | fails |
| H12 | Rows naming `character.assign_control` in `role_capabilities` (built-in or custom role), `character_relationship_type_capabilities` and `resource_grants` are refused by the guard; `create_resource_grant` refuses the code | fails |
| H13 | A GM revokes with a reason: `end_reason = 'revoked'`, revoker set, one audit row. The holder's next assign is 403; the assignments the holder made stay live and in effect (T86) | fails |
| H14 | Revoke with no live delegation: 200 no-op | fails |
| H15 | Revoke by the holder, another assistant GM or a player: 403 | fails |
| H16 | A delegation granted by GM H stays in force after H loses `gm` (T86) | fails |
| H17 | Delegation revoke against an in-flight delegated assign: serialized at the delegation row. Revoke first: the assign gets 403. Assign first: it completes and stays in history | fails |
| H18 | Grant against the grantee's role revoke and against the grantee's membership end: never a live delegation bound to a row that was not live at the insert | fails |
| H19 | Deadlock matrix: grant and revoke against the T01 writers, membership end, role revoke and change, administrative recovery, and reveal-delegation grant and revoke: no `40P01` | fails |
| H20 | Reveal and assign delegations are distinct. A reveal delegation confers no assignment authority; an assign-control delegation confers no `character.reveal`, `access.manage`, controller operation or extra character read | fails (no delegation); the reveal half is a **guard** |
| H21 | Delegations read: owner and GM see live and closed rows with status, reasons and actors; anyone else 403 | fails |
| H22 | Migration 151 upgrade leaves every existing row unchanged and creates no delegation; downgrade removes the table, guard and capability row; reveal delegations are untouched | fails |

**Corrections S02-R1 to S02-R3 (added 2026-11-27; review record in section 11.4, correction record in section 11.5).** Baseline column: the correction baseline `7339d3e8e89692b01d47f890a76fdb8467ede22d` code.

| ID | Case (file) | Finding | Baseline |
|---|---|---|---|
| F34 | Role revoked and committed while the read is parked before the statement that reads the history: the fixed 403, no history (`test_control_assignment_read_snapshot.py`) | R1 | fails (200 with the history) |
| F35 | Clock moved t10 → t20 while the read is parked before that statement: the display and every status come from one snapshot, here (t20, `ended`, not listed) | R1 | fails ((t10, `ended`)) |
| F36 | *Controls.* A role revoke, or a clock move, committed right **after** that statement ran. The response is the statement's own: 200 with the history, or (t10, `in_effect`). Statement coherence, not commit-time serialization | R1 | **guard** (passes) |
| F37 | One statement: exactly one statement after the route gate carries the assign-control authority, and it also reads `campaign_clock`, `core.world_times` and the history. Nothing runs after it, and no statement takes a row lock. It replaces F28's boundary argument | R1 | fails |
| F38 | The displayed clock equals `resolve_membership_clock` for six clock shapes: own root clock, none, branch inheriting below the branch point, bounded at it, unset parent, own branch clock | R1 | **guard** |
| H23 | The recipient's `assistant_gm` row is live at the eligibility read and expired at the final statement. The request's own bound instant is asserted to be before the expiry, otherwise the case is inconclusive. Result: 409 not-assistant, no delegation, no audit (`test_assign_control_delegation_recipient_final.py`) | R2 | fails (201) |
| H24 | The recipient's account is deactivated (committed without waiting: the grant does not lock it) while the grant is parked before `finalize`: 409, nothing written | R2 | fails (201) |
| H25 | Requirement capture: the grant's `finalize` judges the grantor, then the recipient, and its snapshot carries the bound row. The revoke declares no recipient. A unit test (`tests/unit/test_s02_r2_recipient_requirement.py`) adds three checks: the requirement's decisions; the new source reads no new table; the source is the `subject_gm` predicate with the role code changed | R2 | fails |
| H26 | *Guards.* The gated grant succeeds with no change, and a recipient membership suspension waits for the grant (the existing `FOR NO KEY UPDATE` protection) | R2 | **guard** |
| W1 | Statement isolation, for each of five step/index pairs (assign and replace × live primary and live assignment; the delegation INSERT × live delegation). The step's own statement waits on another connection's uncommitted competing key, for that transaction id, with no foreign-key check started. The competitor commits: a unique violation naming the index. The competitor rolls back: success (`test_control_unique_wait_evidence.py`) | R3 | **guard** (the evidence was missing, not the behaviour) |
| W2 | Same-parents control for each pair: the competitor's key is outside the index's predicate, and the step completes under `lock_timeout` with no wait | R3 | **guard** |
| W3 | Route controls: a same-parents competitor outside the index, behind a parked assign and a parked grant, is blocked by the request's pid (the old observation) **at its foreign key** (`fk_checks_started` true), and completes | R3 | **guard**: shows why the old observation was not discriminating |
| W4 | The three declared route tests (`test_a_competing_live_primary_is_a_unique_wait`, `..._live_assignment_...`, `test_a_competing_delegation_for_the_same_grantee_is_a_unique_wait`) additionally assert `fk_checks_started` false while the competitor waits, and the violation's constraint name | R3 | **guard** |

**Structural (not acceptance cases).**
- `tests/unit/test_r01_c11_route_shape.py` pins:
  - the three keyed and two unkeyed registrations;
  - each declaration's lock classes in the section 3 order;
  - each declared write (`Exactly`, `EachLockedRow(complete=True)`, `PerEvidence`, as the precedent modules use);
  - that no route passes a controller scope to a canonical command.
- The existing R01 structure tests must pass with the new routes declared.

**Test-first evidence.** As in the S01 plan: write first, run at the baseline, and record designated failures and guards. Correct test mistakes in the test, not in the expectation.

## 7. Verification

1. **Focused:** the section 4 test files. Add the neighbors, found with `rg -l "character-relationships|reveal-delegations|end_membership|recover|membership_roles" tests/database`, together with `tests/unit/test_r01_*.py` and the S01 test files.
2. **Manifest:** `uv run python -m tests.r01_manifest`, then `tests/unit/test_r01_pending_routes.py`.
3. **Full backend** once per task on its final executable code: `uv run python scripts/run_sharded_tests.py`. A first run and any rerun are reported separately, with no cause claimed without evidence.
4. **Non-pytest checks:** `ruff format --check`, `ruff check`, `mypy src`, `uv lock --check`, `alembic check`, `scripts/check_documentation.py`, `git diff --check`.
5. **Portal:** no portal change; no portal run unless a portal file changes, which is a stop condition.

**Mutation probes** (exact bytes restored, hashes compared):

| Probe | Mutation | Must fail |
|---|---|---|
| N1 | Judge "live primary exists" only at unlocked discovery | F22 |
| N2 | Skip the post-wait authority re-judge | F25 |
| N3 | Replace revokes a named co-controller's row and promotes it | F15 |
| N4 | Revoking a primary also revokes co-controllers | F16 |
| N5 | Accept built-in `assistant_gm` as authority | F10 |
| N6 | Ignore the bound `assistant_gm` row's liveness | H8 |
| N7 | Let a delegated holder grant | H11 |
| N8 | Delegation revoke also revokes the holder's assignments | H13 |
| N9 | Drop the campaign filter from delegation resolution | H10 |
| N10 | Remove the `role_capabilities` guard | H12 |
| N11 (S02-R1, added 2026-11-27) | Split the snapshot: judge the read's authority from an earlier `read_authority_snapshot` and read the history without the statement's holder filter | F34, F37 |
| N12 (S02-R1) | Display the clock from a separate `resolve_membership_clock` statement after the read's statement | F36 (clock control), F37 |
| N13 (S02-R2) | Omit the recipient final requirement | H23, H24, H25 |
| N14 (S02-R2) | Replace it with another plain read of the live `assistant_gm` row at a fresh instant before `finalize` | H23, H24, H25 |
| N15 (S02-R3) | The competitor's key is outside the index, and it holds the campaign row `FOR UPDATE` (a parent-row wait, not an index wait) | W1 (all ten) |
| N16 (S02-R3) | The discriminator always reports "no foreign-key check" | W3 |
| N17 (S02-R3) | Swap the expected index names (live primary ↔ live assignment) | W1 (the four assignment commit cases), W4 (the four assignment route cases) |

## 8. Authorization, disclosure, isolation and outcomes

- **Authorization.** Only the built-in owner and GM roles, or a live OD-4a delegation, hold `character.assign_control`, and they are re-judged under lock after every wait. Control assignments never confer it (OD-2).
- **Disclosure.** Non-holders get one fixed 403 before any target lookup. The read discloses member names and reasons only to authority holders, who already work with the member roster. Audit rows hold no free text.
- **Isolation.**
  - Every row and delegation is campaign-bound and checked by a trigger.
  - Authority and resolution filter on the route campaign.
  - Assignment ids of another campaign get 404.
- **Late-response ownership and unknown outcomes.**
  - The keyed writers use the existing reservation: a lost response is recovered by retrying with the same key, which returns the original receipt; a changed body under that key is refused.
  - The delegation routes are naturally idempotent: a repeated grant returns 200 with nothing written, and a repeated revoke is a no-op.
  - No partial result is possible: each writer is one transaction, and refusals precede `finalize`.
- **Retry identity.** The receipt binds the key to the caller, route and body fingerprint (existing machinery).
- **Draft preservation, read-only reconciliation, navigation, focus and announcements.** Not applicable: no UI in C11. A later consumer uses the read and the receipts.

## 9. Intermediate states

- **After T01:** only owners and GMs can change control. Assistant GMs are refused (correct under OD-4 without OD-4a).
- **After T02:** the full C11 behavior. Profile editing (C12) and operations (C20) remain unavailable to controllers.

## 10. Decisions (routine; recorded)

- **R-1, lock order.** ADR §2.8 is applied on the approved R01 class order. The ADR's user-row `FOR UPDATE` becomes the S5-A account modes. The ADR says the protocol "extends the existing relationship order and must not invert it", and the approved order *is* the existing order. No ADR edit.
- **R-2, keying.** Assignment writers are keyed. Delegation routes are unkeyed and naturally idempotent, following the reveal-delegation precedent.
- **R-3, authority not stored.** `character.assign_control` is judged from the built-in role rows and delegations, never from `role_capabilities`. Its vocabulary row and guard arrive with T02's migration.
- **R-4, no implicit role change.** Replace or assign naming a member who already holds a live assignment on the character is refused; it is not converted.
- **R-5, an ended dated primary still occupies the slot.** It must be replaced or revoked (no scheduled hand-offs, ADR §2.3).
- **R-6, delegation binding.** The delegation is bound to the specific `assistant_gm` row, with no lifecycle hooks. That keeps membership and role writers and their R01 declarations unchanged.
- **R-7, the GET read.** It is limited to authority holders. A broader read, for example for controllers themselves, is a consumer decision under B's accepted scope.
- **R-8, audit history.** Display of control changes is not added (S01 E21 pins their absence from the relationship category).

No owner decision blocks S02.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

**T01**
1. Revalidate before anything else:
   - HEAD equals `origin/phase15/completion` and the worktree is clean;
   - the register records S01 as independently reviewed (stated prerequisite), with any correction confirmed;
   - each section 2.2 contract matches the reviewed S01 code (names, columns, `AccessContext` fields, the `asgn` rule);
   - section 2.1's route registries and the 187-route pin still hold.

   Report the actual baseline SHA and any difference. Stop if a section 2.2 contract differs.
2. Write F1–F33 and the route-shape test first. Run them at the baseline; record designated failures and the F12 guard.
3. Implement section 3.1 only.
4. Regenerate the manifest. Run the section 7 focused set, full shards and non-pytest checks.
5. Run N1–N5.
6. Commit with the T01 subject and push. Record in section 11.3 and the T01 register row, then commit and push the records.

**T02**
1. Revalidate: HEAD equals origin, the worktree is clean, T01's records commit is present, T01's authority component and routes exist as section 3.1 states, and the next free migration number. Report the actual baseline SHA.
2. Write H1–H22 first. Run at the baseline; record fails and guards.
3. Implement section 3.2 only.
4. Regenerate the manifest. Run section 7 in full.
5. Run N6–N10.
6. Commit with the T02 subject, push, then record and push the records.

**Permitted test adaptations (each named in the record):**
- the finalized-route count pin (187 → 190 after T01, → 192 after T02) and the generated registries;
- operation counts in docs;
- a test that pins the Alembic head (T02);
- schema-comment and table-inventory enumerations.

No other expectation changes.

**Stop conditions:**
- a section 2.2 contract differs;
- a reproduced deadlock needs an order other than section 3's;
- a legacy, reveal-delegation, membership-end or recovery test fails;
- a portal change becomes necessary;
- controller operations, profile editing or legacy-row promotion appears necessary;
- the ADR contract appears to need changing.

Report and stop.

No PR, no consumers, no browser/AX checks, no acceptance. CI pending the checkpoint PR.

### 11.2 Independent review boundary

T01's actual baseline through T02's records commit, with the compatibility review (section 5).

### 11.3 Implementation record

**T01 implementation (Sonnet, 2026-11-26).**

- **Commits.** Actual baseline `e59da0b43e9e5d4719ea43b3ee647f142ed35344` (the commit that records S01's independent review; before it HEAD was `0785c8526450f290984d349bc83d9d0f7acea106`, and the two review documents were committed unchanged). Implementation `1d8ac924d0044121d0ae740475748f7fdd0e4747`. The records commit follows it; T02's baseline is that records commit.
- **Revalidation at start (no material discrepancy; nothing stopped).** S01's PASS WITH VERIFICATION LIMITS and the legacy-compatibility review are recorded (S01 plan section 11.4 and the register rows). The section 2.2 contracts match the reviewed code: single head `150_control_assignments`; the two assignment indexes and the legacy `active_type` index by name; `CONTROL_ASSIGNMENT_CAPABILITIES`, `AccessContext.control_assignments` and `control_clock_key`, the shared `CAMPAIGN_CLOCK_CTE` and `control_assignments_in_effect_from_sql`; `AUTHORITY_READER_TABLES` holding the three clock tables and `REVIEWED_POST_WRITE_TABLES` exactly six; the 187-route pin; the legacy relationship declarations naming all three indexes. The new routes write no clock table (the manifest tracer records none; S01 E30 and the disjointness test pass). Assignment authority never reads assignment- or clock-derived capabilities (F33).
- **Files.** Production: `commands/control_assignment_plans.py` (new: errors, request bodies, locks, steps, declarations, the authority requirement, prepare and write phases), `api/control_assignments.py` (new router, included in `api/app.py`), `queries/control_assignments.py` (new read), `domain/access.py` (`AssignControlAuthority`, `_ASSIGN_CONTROL_CTES`, `with_assign_control`, `AuthoritySnapshot.assign_control_authority` and `assign_control_row`), `domain/authorization.py` and `authorization_requirements.py` (`Requirement.assign_control`), `api/r01_pre_write_routes.py` (three keyed registrations), generated `api/r01_pending_routes.py` and `tests/r01_route_manifest.json`. No migration, no lock changed in any existing writer, no portal file. Tests: `tests/database/test_control_assignment_commands.py` (F1-F21, F28-F32), `tests/database/test_control_assignment_concurrency.py` (F22-F27, the index waits, the in-flight campaign 409), `tests/unit/test_r01_c11_route_shape.py` (route shape and F33). Docs: ACCESS_CONTROL section 3z, identity-and-access, operations (353 operations on 336 paths), DATABASE_MODEL sections 19.4 and 19.7.
- **Deviations from the section 4 file table.** There is no `commands/control_assignments.py` (the direct-command oracle): the plan phases are the only writers and the tests assert the stored rows. `test_control_assignment_commands.py` holds the API cases (no separate `_api.py`). The route-shape test pins the three keyed registrations; the two unkeyed ones are T02's and are added with them. The read takes the authority snapshot and then one history statement (the clock, the in-effect test and the statuses share one statement and one snapshot); it is not one statement end to end.
- **Permitted adaptations (each named).**
  1. Finalized-route pins 187 to 190: `test_r01_pending_routes.py`, `test_r01_e2_route_shape.py`, `test_r01_e4_route_shape.py`, `test_r01_s5e6_route_shape.py`; access-management family count 32 to 35.
  2. Generated registries: `r01_pending_routes.py`, `r01_route_manifest.json` (`uv run python -m tests.r01_manifest`).
  3. Per-slice registries that enumerate the keyed set or subtract earlier slices: `tests/r01_manifest.py` (`_C11S02_ROUTES` in `MIGRATED_ROUTES`, and `classify()` returning `access_management` for them, because they write a reader table and are pre-write), `test_r01_s2_route_shape.py`, `test_r01_s5d_route_shape.py`, `test_r01_s5e1_route_shape.py`.
  4. Beyond the plan's literal list, required by the same registry process and named for review: the reviewed-adopter allow-list of `ReservationDeclarations(` in `test_r01_s5c_no_route_opt_in.py` (adds `commands/control_assignment_plans.py`), and the Phase 15 acceptance manifest (`tests/scenario/phase15_route_manifest.py` family `control-assignments`; `test_phase15_acceptance_guards.py`: guarded 248 to 252, Phase 15 GM routes 200 to 201).
  5. Docs counts (operations.md) and the new catalog section.
- **Test first.** Run at the baseline with no production change:
  - *Commands file (49 cases).* First run 44 failed, 5 passed: F12 (the designated guard: a non-member gets the campaign 404), F5, and F9 (three cases). F5 and F9 passed **for the wrong reason** (an absent route also answers 404); both were strengthened with a positive control (a valid assign must first be 201) and then failed at the baseline: 48 failed, 1 passed (F12 only).
  - *Concurrency file.* First run (32 cases) 17 failed, 15 passed: the 15 were F27 matrix cases that passed vacuously because the writer route was absent. A positive control was added (the writer alone, uncontended, must succeed) and the recovery administrator setup was corrected (a test mistake: it used a raw insert instead of `make_system_role_assignment`). Final baseline: all 34 cases fail.
  - *Unit.* `test_r01_c11_route_shape.py`: collection error (no `control_assignment_plans` module), the designated failure of the shape pins and F33.
  - Test-side corrections after implementation, never expectations: F8 inactive campaign is the campaign route's own 404 at rest (the plan's 409 is pinned by the new race `test_f8_a_campaign_archived_while_the_request_waits_is_the_409`); second campaigns created by tests carry an owner so the access-manager retention trigger holds; error bodies are compared without their per-request correlation id; F26 archive-after-assign uses an NPC (S01's archive block covers NPC and player-character types only).
- **Race evidence for the new competing unique-index waits (not declarations alone).** `test_a_competing_live_primary_is_a_unique_wait` and `test_a_competing_live_assignment_is_a_unique_wait`, each for assign and replace: the request is parked at its audit INSERT with its assignment INSERT uncommitted; a competing INSERT of the same key queues behind the request's pid (observed through `pg_blocking_pids`; the waiting statement is an `INSERT INTO security.`), and when the request commits the competitor fails on the unique index; one live row remains. `test_an_assignment_insert_never_waits_on_the_legacy_index` runs each step's own statement under a lock timeout against an uncommitted legacy row with the same key (no wait). `test_a_revoke_leaving_the_assignment_indexes_never_waits_for_a_competing_insert` covers the closing UPDATEs of revoke and replace.
- **Concurrency cases.** F22 (one 201, one `primary_controller_exists`), F23 (revoke against assign), F24 (both orders against membership end), F25 (role revoke first gives 403 after the wait; and the authority is judged again after the last wait, before any eligibility refusal, shown by expiring the caller's gm row while the request waits for the campaign row with an ended assignee), F26 (both orders against the archive of an NPC), F27 (each writer against legacy grant, legacy revoke, membership end, role revoke, archive and administrative recovery; a positive control and three repetitions each; the database deadlock counter unchanged, no 5xx).
- **Focused and unit runs.**
  - *DB neighbours (the 142 files that name relationships, reveal delegations, membership end, recovery or membership roles, plus the S01 files, the profile schema file and the party roster file):* **4,786 passed, 6 skipped, 0 failed**, 50m26s.
  - *`tests/unit`, alone:* 2,441 passed, 1 failed: the known environmental `test_config.py::test_local_session_allowed_origins_defaults_to_dev_topology_outside_production` (extra allowed origin; reported, not changed). An earlier `tests/unit` run that **overlapped** another pytest run on the same machine (my launch error: an empty file list, then a restart) gave 43 failed, 2,399 passed; it was not repeated under overlap and **no cause is claimed**. The first `tests/unit` run (before the pin adaptations) gave 10 failed: the `test_config` case and nine route-count or registry pins, all adapted above.
- **Full shard runs** (`uv run python scripts/run_sharded_tests.py`), reported separately:
  - *First run:* **11,557 passed, 6 skipped, 9 failed**, 11,572 collected and executed, 31m11s. All nine were in `tests/scenario/test_phase15_acceptance_guards.py` (the route manifest did not classify the revoke route; its size pins). Not relabelled as passing.
  - *Second run (final executable code, alone on the machine):* **11,566 passed, 6 skipped, 0 failed**, 30m27s.
- **Non-pytest checks** on the final code: `ruff format --check`, `ruff check`, `mypy src` (303 files), `uv lock --check`, `scripts/check_documentation.py` and `git diff --check` pass; `alembic check` on a freshly migrated throwaway database returns 0 and `alembic heads` shows the single head `150_control_assignments`.
- **Mutation probes** (exact bytes restored; SHA-256 of the touched files and the manifest compared before and after, identical each time):

| Probe | Result |
|---|---|
| N1 (judge "live primary exists" at unlocked discovery only) | F22 fails |
| N2 (skip the post-wait authority re-judge) | the F25 expiry-precedence case fails. The plain F25 role-revoke race **passes** under N2: the revoked row's lock returns nothing, so the 403 comes from the lock itself; the re-judge is shown only by the expiry case |
| N3 (replace revokes a named co-controller's row) | both F15 cases fail |
| N4 (revoke also revokes co-controllers) | F16 fails, through the plan guard: the extra raw UPDATE after `finalize` is refused (500 `AuthorizationPlanViolationError`), so the semantic effect itself is not observed |
| N5 (accept `assistant_gm` as authority) | F10 fails |

- **Stop conditions.** None applied: no section 2.2 contract differed, no deadlock was reproduced, no legacy, reveal-delegation, membership-end or recovery test failed, no portal file changed, and controller operations, profile editing and legacy promotion were not needed.
- **Unresolved history carried, distinct.** The environmental `test_config` failure; the overlapped-run unit failures above; the earlier recorded clock audit-count anomaly and combined-invocation fixture errors were not observed in this task's runs and remain unresolved as recorded. CI is pending the checkpoint PR. No browser or AX work, no consumers, no PR.
- **Luna's S02 range.** T01's actual baseline `e59da0b43e9e5d4719ea43b3ee647f142ed35344` through the T02 records commit (not yet written). T01 implementation `1d8ac924d0044121d0ae740475748f7fdd0e4747`.

**T02 implementation (Sonnet, 2026-11-26/27).**

- **Commits.** Actual baseline `340267c6debb9560e08f8cb87c21d7c30766579c` (T01's records commit; HEAD equalled origin and the worktree was clean). Implementation `7f48e61a26e7988109e31193ee851c9f75cb4b59`. The records commit follows it. T01 implementation is `1d8ac924d0044121d0ae740475748f7fdd0e4747`. Task ranges: T01 `e59da0b43e9e5d4719ea43b3ee647f142ed35344..340267c6debb9560e08f8cb87c21d7c30766579c`; T02 `340267c6debb9560e08f8cb87c21d7c30766579c..` the T02 records commit. Combined S02 review range: `e59da0b43e9e5d4719ea43b3ee647f142ed35344..` the T02 records commit.
- **Revalidation at start (nothing stopped).** T01's implementation is present; the authority component (`with_assign_control`), the three keyed routes, the lock sequence and the registries (190 finalized, access_management 35) matched the recorded code. The next free migration number is 151 (head `150_control_assignments`; `e3f791aca64d` sits mid-chain). *T01's disclosed read.* Plan section 3.1 says the read is "no locks, one snapshot". T01's read is the authority snapshot, the clock display resolver and one history statement, all `READ COMMITTED`. Statuses, the in-effect test and the clock key share one statement and one `campaign_clock` CTE (the section 2.2 item 6 requirement), but the authority check and the displayed clock are separate statements, so "one snapshot" is not literally met end to end. I judged it not a violated testable requirement (F28 pins the boundaries; T02 does not depend on it), did not amend it, and left it disclosed for Luna's review. All T01 deviations are preserved unchanged.
- **Files.** Migration `151_assign_control_delegations` (vocabulary row `character.assign_control`, sort order 160; the table with the scope, immutable-column and updated-at triggers; one live row per grantee; the guard trigger on `role_capabilities`, `character_relationship_type_capabilities` and `resource_grants`; grants come from the bootstrap default privileges, as for the reveal table); `persistence/tables/security.py` and `__init__.py`; `domain/access.py` (`BUILTIN_CAMPAIGN_ASSISTANT_GM_ROLE_CODE`, source `delegation`, `assign_control_delegation`, the `ac_assistant` and `ac_delegation` CTEs; the table added to `AUTHORITY_READER_TABLES`, **not** to `REVIEWED_POST_WRITE_TABLES`); `commands/assign_control_delegations.py` (errors, end reasons, the 404 read), `commands/assign_control_delegation_plans.py` (declarations, locks, prepare and write phases, `grantor_requirement`), `api/assign_control_delegations.py`, `queries/assign_control_delegations.py`, two unkeyed registrations in `api/r01_pre_write_routes.py`, router include in `api/app.py`, generated registries. `commands/control_assignment_plans.py` gains `DELEGATION_ROW_LOCK` (after the authority row in the three T01 declarations), discovery of a delegated holder, and `HeldAuthority`; the T01 read accepts a delegated holder. `commands/membership_end_plans.py` pins the new guard trigger among the `resource_grants` triggers (the existing grant writers' declarations require every trigger on a written table to be pinned). Docs: ACCESS_CONTROL section 3aa (and 3z cross references), identity-and-access, operations (356 operations on 338 paths, 82 in identity-and-access), DATABASE_MODEL, tables.md (229 tables, head 151).
- **Deviations from the section 4 table.** There is no direct unguarded command module (as in T01): `assign_control_delegations.py` holds only the error vocabulary, constants and the unlocked 404 read; the plan phases are the only writers. The grant does not re-judge the recipient at `plan.finalize` (the snapshot has no subject `assistant_gm` source, unlike the reveal recipient); the recipient is judged by plain reads at a fresh instant after the last wait, under the grantee's `assistant_gm` row `FOR UPDATE` and membership `FOR NO KEY UPDATE`, and `finalize` re-judges the grantor (owner or `gm`, never `delegation`). A delegation row bound to a lapsed role is never closed by a hook (plan: no hooks); the read reports it "not in force".
- **Permitted adaptations (each named).** (1) Finalized-route pins 190 to 192 (`test_r01_pending_routes.py`, `test_r01_e2_route_shape.py`, `test_r01_e4_route_shape.py`, `test_r01_s5e6_route_shape.py`), access-management family 35 to 37; (2) generated registries `r01_pending_routes.py` and `r01_route_manifest.json`; (3) registries: `tests/r01_manifest.py` (`_C11S02T02_ROUTES`, classified `access_management`), `test_r01_s2_route_shape.py`, `test_r01_s5e2_unkeyed_registry.py`; (4) table inventory: `test_persistence_tables_package.py`, `test_role_grants.py` (`MANAGED_TABLES`); (5) operation counts and catalog; (6) reader-set enumeration `test_r01_authorization_structure.py` (the statement is built with `with_assign_control`, the component that names the new table). **Beyond the plan's literal list, named for review:** the T01 lock-sequence pins in `test_r01_c11_route_shape.py` gain `assign_delegation_row_share` (plan section 3.2 mandates that lock for delegated holders; the rank function gains a delegation class); the Phase 15 acceptance manifest and pins (`phase15_route_manifest.py` family `assign-control-delegations`; guarded 252 to 255, Phase 15 GM routes 201 to 204); and the `GRANT_TRIGGERS` pin in `membership_end_plans.py` (production declaration, adds a pin, removes nothing).
- **Test first.** Run at the baseline with no production change. *Database files* (56 collected: 30 behaviour, 24 concurrency, 2 migration): 55 failed, 1 passed. The one pass is the designated guard, the reveal half of H20. Four failures were first for the wrong reason (test mistakes, corrected in the test: an expired-row UPDATE that violated `ck_membership_roles_expires_after_granted`; a duplicate owner membership in the migration test); they were rerun at the baseline and failed for the right reason (404 or missing relation or revision). *Unit:* `test_r01_c11_route_shape.py` is a collection error (no `assign_control_delegation_plans` module), which also hides the modified T01 pins from that run. Refusal cases an absent route could satisfy (H3 422 aside, which a 404 cannot satisfy) carry a positive control: H5 and H14 (404) first assert the success shape; H12 asserts the capability row exists. Later test-side corrections, never expectations: the route requirement (`campaign.view`) needs a role beside the one under test or the refusal is the route's `forbidden`, not `character_assign_control_required` (custom manager, lapsed and re-granted roles, H16).
- **Race evidence.** H17 both orders (assign in flight, revoke queued on the delegation row; revoke first, assign refused 403 after its wait); H18 grant against grantee role revoke and against membership end, both orders (no delegation bound to a row not live at the insert); H19 matrix (grant and revoke against owner assign, delegated assign, membership end, role revoke, role change, administrative recovery, reveal grant and reveal revoke; positive control, three repetitions, deadlock counter unchanged, no 5xx); the live-index waits `test_a_competing_delegation_for_the_same_grantee_is_a_unique_wait` (a competing raw INSERT queues behind the grant and then fails on the unique index; it cannot be told apart from queueing at its foreign key on the `assistant_gm` row, and that is not claimed) and `test_a_delegation_closure_leaving_the_live_index_never_waits_for_a_competing_insert`. No deadlock was reproduced.
- **Focused runs.** New files: 30 + 24 + 2 passed (behaviour, concurrency, migration). T01 and S01 files plus the snapshot differential: 180 passed. Plan 7.1 neighbours (170 database files by the section 7 pattern, the T01 set and the new files): **5,061 passed, 6 skipped, 4 failed**, 54m11s. The four failures were mine: the new guard trigger on `resource_grants` was unpinned in the S5-E3, S5-E4 and S5-E5 grant declarations (three `test_the_declarations_hold_against_the_live_catalogue`), and `test_role_grants.py` `MANAGED_TABLES` lacked the table. Both fixed above; those four files rerun: 1,097 passed, 6 skipped. `tests/unit`: 2,448 passed and 2 failed at the last run before the final pin edits (the environmental `test_config` origin case and the reader-set enumeration, since fixed); the full shard run below covers `tests/unit` on the final code.
- **Full shard run** (`uv run python scripts/run_sharded_tests.py`, alone on the machine, final executable code): **11,637 passed, 6 skipped, 0 failed**, 11,643 collected and executed, 27m27s (this run passed the `test_config` case; it is environmental and was not touched). This is the only full run for T02.
- **Non-pytest checks** on the final code: `ruff format --check`, `ruff check`, `mypy src` (307 files), `uv lock --check`, `scripts/check_documentation.py` pass; `git diff --check` reports only the line-ending notices of this repository's `autocrlf`; `alembic check` on a freshly migrated database returns 0 and `alembic heads` shows the single head `151_assign_control_delegations`.
- **Mutation probes** (exact bytes restored; SHA-256 of the touched files and the manifest compared, identical each time).

| Probe | Result |
|---|---|
| N6 (ignore the bound `assistant_gm` row's liveness: the discovery read and the snapshot CTE) | the H8 expired-role case fails. The revoked-role variant passes under N6: the role row's lock (`revoked_at IS NULL`) returns nothing, so the 403 comes from the lock itself; liveness by expiry is shown only by the expired case |
| N7 (a delegated holder may grant) | H11 fails, through the plan guard: the request ends 500 `AuthorizationPlanViolationError` rather than a clean 201, so the semantic effect is not observed |
| N8 (revoking the delegation also revokes the holder's assignments) | both H13 cases fail, through the plan guard (500; the extra raw UPDATE after `finalize` is refused), as for T01's N4 |
| N9 as written (drop the campaign predicates from the delegation resolution) | **H10 survives (passes)**: resolution is also keyed by the caller's membership id, which belongs to one campaign, in the discovery, both lock bindings and the snapshot; the campaign predicate is defence in depth |
| N9' (resolve the delegation by user across campaigns at every layer: snapshot, discovery and both lock bindings) | H10 fails |
| N10 (no guard trigger on `role_capabilities`) | H12 fails |

- **Stop conditions.** None applied: no section 2.2 contract differed, no deadlock was reproduced, no legacy, reveal-delegation, membership-end or recovery test failed (the four neighbour failures were the unpinned trigger and the table inventory, see above), no portal file changed, and controller operations, profile editing and legacy promotion were not needed.
- **Unresolved history carried, distinct.** T01 evidence is unchanged and separate: first shard run 9 scenario-classification failures, final 11,566 passed and 6 skipped, the overlapped unit invocation's 43 unexplained failures (no cause claimed), the separate unit invocation 2,441 passed plus the environmental `test_config` failure, N2 and N4 limits and T01's extra adaptations. The earlier clock audit-count anomaly and combined-invocation fixture errors were not observed. CI is pending the checkpoint PR. No browser or AX work, no consumers, no PR.

### 11.4 Independent review of T01, T02 and combined S02 (Codex, 2026-11-27)

- **Review boundary.** T01 `e59da0b43e9e5d4719ea43b3ee647f142ed35344..340267c6debb9560e08f8cb87c21d7c30766579c`; T02 `340267c6debb9560e08f8cb87c21d7c30766579c..7339d3e8e89692b01d47f890a76fdb8467ede22d`; combined `e59da0b43e9e5d4719ea43b3ee647f142ed35344..7339d3e8e89692b01d47f890a76fdb8467ede22d`. Baselines and implementations are ancestors in the stated order. Branch `phase15/completion`, HEAD and origin agree at `7339d3e8e89692b01d47f890a76fdb8467ede22d`; the worktree was clean before review. Temporary probe files were removed; no implementation files were changed.
- **T01 verdict: CHANGES REQUIRED.** The assignment/replace/revoke paths preserve the intended refusal order, idempotency replay identity, anchor and lock sequence, post-wait authority re-judgment, eligibility checks, period validation, campaign scope, partial uniqueness constraints, audit atomicity and strict legacy-row separation. S01's reviewed resolver behavior remains intact. However, the assignment read does not meet section 3.1's explicit “no locks, one snapshot” contract: the endpoint checks assignment authority in `read_authority_snapshot`, resolves the displayed clock separately, then queries history and its status clock in another statement, all under `READ COMMITTED`. A controlled probe revoked the owner's role after the authority snapshot and before the history query; the request still returned 200 and the seeded assignment/reason data. Clock advancement between the display-clock read and history statement can likewise pair one displayed clock with statuses from another. This is a demonstrated cross-statement disclosure/consistency window, not justified by F28's boundary assertions. **Finding S02-R1 — split authorization/read snapshot, application, score 4/10 Medium:** supported path 1 (privileged assignment reader and a concurrent role/clock change), impact 2 (one request can disclose protected history after authority revocation or present a mismatched clock/status), triggerability 1 (requires a race), detection/recovery 0, blast radius 0. It fails the explicit one-snapshot read contract and blocks T01. Bounded correction: make authority, effective clock, and history/status part of one read statement/snapshot, preserving the fixed refusal and no-lock behavior; add controlled revoke/clock-change tests around that snapshot.
- **T02 verdict: CHANGES REQUIRED.** Grant/revoke/read routes remain campaign-bound, non-redelegating, naturally idempotent, and atomic; the holder's assignment rows remain untouched on delegation revoke. Migration 151's restricted vocabulary trigger and table constraints are correct in the tested catalogue; the delegation table is an authority reader, not a reviewed post-write exemption. T01's delegated-role and delegation-row lock order follows the approved role → delegation → membership → campaign order and the H17/H18/H19 races show both revocation orderings without a reproduced deadlock. But recipient eligibility is not part of the final authorization snapshot. **Finding S02-R2 — recipient expires after eligibility read, application, score 3/10 Low:** after the last waits, `_LIVE_ASSISTANT_SQL` binds `expires_at > :t` using a preceding `clock_timestamp()` query; `plan.finalize` then rechecks only the grantor. The assistant-GM row lock prevents a concurrent row update/revoke but cannot stop wall time. A temporary probe expired the recipient role during the eligibility statement: the endpoint returned 201 after expiry and committed a live-but-not-in-force delegation and its audit. Scores: supported path 1 (owner grants to assistant GM), impact 1 (stale delegation/audit, with no authority while its bound role is expired), triggerability 1 (expiry at the request boundary), detection/recovery 0 (read identifies lapsed binding and a later grant closes it), blast radius 0. This fails the required live-recipient check at the final decision instant. Bounded correction: include recipient membership/account and bound assistant-role liveness, including expiry at the final authorization instant, in the final snapshot after waits; keep the role lock and retry response for concurrent row changes, and test a role expiring between the precheck and finalization. The plan should make this final-recipient instant explicit; that clarifies the existing eligibility rule and adds no scope.
- **Finding S02-R3 — declared unique waits are not isolated by the race tests, test/evidence, score 2/10 Low.** T01's assignment INSERT competitors and T02's delegation INSERT competitor can be blocked on parent-row foreign-key checks because the request holds campaign/character or assistant-role rows in stronger modes. The delegation test explicitly says it cannot distinguish an assistant-role FK wait from the partial-index wait; the T01 tests also only observe blocking PID and eventual constraint failure, not the wait source. Eventual uniqueness errors demonstrate that indexes prevent duplicates, but do not establish the declared `UniqueWait` evidence required by S01 §2.2 item 5 and S02 §7.1 for the specific live indexes. No duplicate row was observed and no production uniqueness defect is demonstrated. This is an acceptance-evidence gap, not a product finding. Bounded correction: make each competing-index test distinguish the relevant index wait from FK/parent locks (or revise the evidence protocol with owner approval); retain separate tests for both T01 live indexes and the T02 live delegation index.
- **T02 disclosed mutations.** N7 and N8 are stopped by `AuthorizationPlanViolationError` when the mutation tries to add an undeclared write after finalization. This proves the structural plan guard, not the hypothetical semantic mutation by itself. The endpoint tests and source path still show the actual no-redelegation refusal and that revocation preserves assignments. N9's literal campaign-filter deletion survives H10 because the caller/grantee membership IDs are already campaign-specific; N9' broadens lookup across users and campaigns at every layer and fails H10. The campaign predicate is redundant defense in depth, not a demonstrated isolation defect. N6's expiry positive control is meaningful; the revoked-role variant is enforced by the row lock's missing result. N10 demonstrates the restricted-vocabulary guard. These limits do not erase the specific R2 issue.
- **Declarations and compatibility.** `GRANT_TRIGGERS` adds the migration-151 `resource_grants` capability-guard trigger to the existing grant writer declaration because the live catalogue requires all triggers on the written table to be pinned; it removes no protection. The new delegation row locks and route-shape ranks match the mandated lock order. Generated manifests, route counts, table inventory and `AUTHORITY_READER_TABLES` include the new endpoints/table, while `REVIEWED_POST_WRITE_TABLES` stays unchanged. No unauthorized reader exemption was added. The targeted compatibility/live-catalogue runs passed 997 tests/5 skipped across membership-end, access-grant, reveal-delegation, recovery-lock-order and role-grant files, plus 411 passed/1 skipped across the S5-E5 group grant, race, interaction, cardinality and resource-grant files. No S01, reveal-delegation, membership-end, recovery or existing resource-grant regression was demonstrated. S01's independent PASS WITH VERIFICATION LIMITS carries forward.
- **Review checks (separate from implementation history).** Focused S02 authorization, assignment concurrency, delegation, migration and R01 structure set: 244 passed. Controlled recipient-expiry probe: reproduced the post-expiry 201; controlled authority-revocation probe: reproduced the read after revocation. The temporary probe files were removed. `ruff format --check`, `ruff check`, `mypy src` (307 files), `uv lock --check`, documentation validation and `git diff --check` pass after probe cleanup. `alembic heads` reports the single expected head `151_assign_control_delegations`; `alembic check` could not run against the configured target because that database is not at the migration head. Migration 151's focused fresh-database tests passed in the 244-test run. No full shard was repeated.
- **History remains separate.** T01 first nine scenario-guard failures and final 11,566 passed/6 skipped; the overlapped unit run's 43 unexplained failures; T02's neighbor run (5,061 passed/6 skipped, four implementation failures later corrected), corrected related-file run (1,097 passed), and full run (11,637 passed/6 skipped) remain as recorded in §11.3. This review does not diagnose or replace those results.
- **Readiness.** Combined S02 is **CHANGES REQUIRED** until R1 and R2 are corrected and the declared unique-wait evidence is discriminating. The prior T01 note that F28 boundary pinning made its split snapshot acceptable is retained as implementation history, but does not satisfy the plan's explicit one-snapshot contract. No owner decision is inferred or recorded. C11 checkpoint acceptance remains ungranted; exact-head CI and the integrated C11 acceptance/full-backend evidence remain pending the checkpoint PR. No PR, consumers, browser/AX checks, pilot work or acceptance were started.

### 11.5 Correction of S02-R1, S02-R2 and S02-R3 (Opus, 2026-11-27)

**Status.** Every finding is **corrected, pending independent confirmation**. T01, T02 and combined S02 stay at Luna's **CHANGES REQUIRED** (section 11.4, kept unchanged as history) until Luna's re-review. S01's PASS WITH VERIFICATION LIMITS carries forward: no S01 regression was demonstrated. No owner decision was needed or inferred.

**Commits.** Correction baseline `7339d3e8e89692b01d47f890a76fdb8467ede22d`; HEAD and origin agreed. Luna's uncommitted review edits were backed up and committed verbatim, hash-identical to the uncommitted files, as `ed1babc70e2346072bb900a63d336f0b98d50ec3`. Then:

| Finding | Commit | Review range |
|---|---|---|
| S02-R1 | `d63653a1e0eb6ce3d8c827f3d34388a1373609e1` | `ed1babc70e2346072bb900a63d336f0b98d50ec3..d63653a1e0eb6ce3d8c827f3d34388a1373609e1` |
| S02-R2 | `38863655766a6bcfd99b3a5e29c0eddb9b08f843` | `d63653a1e0eb6ce3d8c827f3d34388a1373609e1..38863655766a6bcfd99b3a5e29c0eddb9b08f843` |
| S02-R3 | `beb0ff965d73b6a61ed2b4f73fc554d86d706d84` (tests only) | `38863655766a6bcfd99b3a5e29c0eddb9b08f843..beb0ff965d73b6a61ed2b4f73fc554d86d706d84` |

These records follow in their own commit. The combined correction range is `ed1babc70e2346072bb900a63d336f0b98d50ec3..` the records commit. Luna's original S02 range (section 11.4) is unchanged.

**S02-R1: design.**
- **One statement.** The read (`queries/control_assignments.read_character_control`) is one SQL statement, with no row lock. Its first CTE is the authority statement `read_authority_snapshot` runs (`domain/access.build_authority_statement`, with the assign-control component). `read_authority_snapshot` was refactored to build and parse through the same object, with the same SQL and parameters.
- **What the statement also reads.** Beside the authority CTE:
  - `CAMPAIGN_CLOCK_CTE`;
  - `clock_point`, the same timeline chain carrying the world-time id, so the display row is read in the statement;
  - every status, from the shared in-effect fragment;
  - the history with its period display rows, read only when the statement's own `assign_control_source` is a holder's.
- **Refusals.** The route judges the campaign `404`, the `campaign.view` `403` and the fixed `403 character_assign_control_required` from that row, in the route gate's order.
- **Unchanged.** Response shape, ordering, the 200-row bound and `truncated` are unchanged; the route dependency stays the early gate.
- **Self-check.** On every read, the clock point's key is checked against the statement's `campaign_clock` key and the authority statement's own `control_clock_key`; a mismatch raises.

**S02-R2: design.**
- **New snapshot source.** It is opt-in and declared by a requirement: `Requirement.assistant_gm_subject` → `AuthoritySnapshot.subject_assistant_gm_assignment`. It is the existing `subject_gm` predicate (R01 S5-E6) with the role code and the bind name changed, and it reads no new table.
- **The recipient requirement.** `assign_control_delegation_plans.recipient_requirement` is registered after `grantor_requirement`, so the grantor's 403 still precedes the recipient's 409. It refuses with `409 assign_control_recipient_not_assistant_gm` when the grantee holds no live assistant GM assignment at the final `t_auth`: the membership open and active in this campaign, the account active, the assignment unrevoked and unexpired, the role active. It refuses with `409 assign_control_recipient_changed` when the live row is not the locked row. Both refusals come before any write.
- **The early read.** It stays an early check.
- **Unchanged.** Locks and their order, grantor checks, campaign binding and audit atomicity. The revoke declares no recipient.
- **R01 pin.** `AuthorizationPlan.require` gains the one-subject-per-plan guard for the new source, exactly as the R01 E2 C-1 correction did for perspectives. Its R01 O-1 AST pin (`tests/unit/test_r01_o1_authorization_structure.py`) is re-pinned from `742c5127e08b421e` to `4be22a5b90b82899`, with the reason and the old digest in the comment.

  This is a **named adaptation for review**. The pin exists to force review of pre-write code changes, and this change is the reviewed one. Both digests were measured under Python 3.12.13 and 3.13.12 and agree, so the pin stays version-independent.
- **S01's E32.** It also asserts that the clock routes declare no assistant-GM subject, which keeps E32 closed for the new field.

**S02-R3: design (tests only).**
- **The mechanism.** PostgreSQL inserts the heap tuple and its index entries (where the unique check runs) before the AFTER-trigger foreign-key checks. A foreign-key check takes `RowShareLock` on its parent relation and holds a heavyweight `tuple` lock while it waits for a row lock. `fk_checks_started(pid)` reads exactly that from `pg_locks`.
- **W1, statement isolation.** For each of the five step/index pairs:
  - the step's own statement waits on another connection's uncommitted competing key, for that transaction id, with no foreign-key check started;
  - when the competitor commits, the unique violation's `constraint_name` is the declared index;
  - when it rolls back, the step succeeds.
- **W2, same-parents controls.** No wait under `lock_timeout`, so the shared parents (`FOR KEY SHARE` only) cause no wait.
- **W3, route controls.** They show that a foreign-key wait satisfies the old "blocked by the request" observation.
- **W4.** The three declared route tests also assert `fk_checks_started` false and the constraint name.
- **The declarations.** They still point at those three tests; no production declaration changed.
- **Limits.**
  - A route request cannot itself be shown waiting on these indexes with an outside competitor, because the competitor's `FOR KEY SHARE` on the campaign makes the request wait at its campaign `FOR UPDATE` first. Inside the application every writer of these rows takes that lock, so the index wait is a conservative declaration, demonstrated by statement isolation.
  - The discriminator relies on PostgreSQL's documented order of index insertion and AFTER-trigger checks and on `pg_locks`' lock vocabulary. It does not observe the wait at the index page.

**Why the original R3 tests could pass through an unrelated wait (prototype probe, baseline code, temporary file deleted).**
- *Conflicting competitor* (a primary of another member on the same character, behind an assign parked at its audit insert):
  - waiting on a `transactionid` `ShareLock`;
  - holding only `AccessShareLock` on the parent relations (its BEFORE-trigger reads);
  - no `RowShareLock` and no `tuple` lock;
  - result: `UniqueViolation ux_membership_character_relationships_live_primary`.
- *Same-parents competitor* (a co-controller of another member, no index conflict):
  - holding `RowShareLock` on `campaign.campaigns`, `character.characters`, `security.campaign_memberships` and `security.character_relationship_types`;
  - a granted `tuple` lock on `campaign.campaigns`;
  - waiting on a `transactionid` `ShareLock`;
  - result: completes once the request commits.
- Both satisfied the old assertions: blocked by the request's pid, and a waiting statement `INSERT INTO security.`.

**Test first, at the baseline code.**
- *First R1 run:* 3 failed as designated, 7 passed.
  - revoke-before: 200 with the revocation reason;
  - clock-before: `('Year 1010', 'ended', False)`;
  - one-statement: first recorded no statement. That was a test mistake: a thread-name filter, while the test client runs the app on another thread. Corrected in the test, it then failed for the designated reason.
- *R2:* 2 failed (expiry and account, each 201 with a delegation and audit), 2 passed. The expiry case's precondition held: the eligibility read's bound instant came before the expiry.
- *R3:* 17 + 5 passed, as expected for an evidence gap.
- *Final baseline pass over every new and modified case:* the six production files were replaced by their `HEAD` versions, then restored hash-identical. Result: **9 failed (designated), 33 passed (guards and controls)**.
  - R1: 3 failed, 8 passed, including the clock-after control added after N12;
  - R2 database: 3 failed (H25 included), 2 passed;
  - R2 unit: 3 failed, 1 passed;
  - R3: 17 + 5 passed.

**Mutation probes** (a temporary script outside the repository, run on the final code before the records). Each probe was applied, its tests run, and the exact bytes restored. SHA-256 of `api/control_assignments.py`, `queries/control_assignments.py`, `commands/assign_control_delegation_plans.py` and `test_control_unique_wait_evidence.py` matched after every probe.

| Probe | Result |
|---|---|
| N11 | F34 and F37 fail; F35 passes (its display is in the statement under the mutation) |
| N12 | first run: only F37 failed (a later display read pairs with a later clock only if the clock moves after the statement). The clock-after control (F36) was then added; rerun: F36 and F37 fail |
| N13 | H23, H24, H25 fail |
| N14 | H23, H24, H25 fail (the plain re-read runs before the gate, sees the row live and grants) |
| N15 | all ten W1 cases fail |
| N16 | both W3 route controls fail |
| N17 | the four W1 assignment commit cases and the four W4 assignment route cases fail |

**Verification on the final code (`beb0ff965d73b6a61ed2b4f73fc554d86d706d84`).**
- *Focused run.* Serial: 37 database files plus `tests/unit`. The database files are every C11 assignment and delegation file (commands, concurrency, read snapshot, clock routes, resolution, storage, migrations), the R3 evidence, every file with a live-catalogue declaration test, the legacy grant and R01 S5-E3/E4/E5/E6/F files, reveal delegation, recovery and stranding, the snapshot differential, E2 perspective and role grants.
  - Result: **4,568 passed, 6 skipped, 2 failed**, 17m58s.
  - Failure 1: the environmental `tests/unit/test_config.py::test_local_session_allowed_origins_defaults_to_dev_topology_outside_production` (an extra local allowed origin; not changed).
  - Failure 2: `test_r01_o1_authorization_structure.py::test_the_pre_write_code_is_unchanged_from_the_parent`, the `require` pin, re-pinned as described. That file then passed 16 of 16.
- *Earlier focused runs during the work:* the read, delegation, snapshot, structure and C11 shape files gave 172 passed; the R2 neighbours gave 127 passed.
- *Per-commit checks* (throwaway worktrees, each with its own synced environment and interpreter):
  - `d63653a` (R1 read, commands, R01 structure and O-1 files): 92 passed;
  - `3886365` (R2 files, delegation, clock routes, R01 structure and O-1): 82 passed.
  - **A first per-commit attempt is invalid and not counted:** the worktree environment lacked the `dev` extra, so `uv run pytest` reached the main checkout's pytest and imported the main `src`. It reported 1 failed and 91 passed for `d63653a`, and 82 passed for `3886365`.
- *Full backend shards:* `uv run python scripts/run_sharded_tests.py` on `beb0ff9`, alone on the machine, launched after the environment restore below. **First run: 11,673 passed, 6 skipped, 1 failed**; 11,680 collected and executed; 32m25s. Shards: 3,102, 2,838, 2,668 and 3,065 + 1 failed. The failure was `tests/database/test_r01_e4_reference_corpus.py::test_a_lapse_before_the_final_check_refuses_rolls_everything_back_and_a_retry_succeeds[grant-capability_removed_from_the_role-final]` (shard 4). The gate on the final authority statement was not reached after 18.2s, the request was still running, and no backend was non-idle (deadline report kept in the run directory). **No cause is claimed.** *Rerun, reported separately:* that test alone, all 30 parametrizations, passed, and the whole file passed (99). No second full run was made.
- *Non-pytest checks* on the final tree:
  - `ruff format --check` (1,015 files), `ruff check`, `mypy src` (307 files), `uv lock --check` and `scripts/check_documentation.py` pass;
  - `git diff --check` reports only the repository's line-ending notices;
  - `alembic upgrade head`, `alembic heads` (single head `151_assign_control_delegations`) and `alembic check` (exit 0) pass on a throwaway database created and dropped for this check. The configured database was not migrated. The existing foreign-key cycle sort warning was printed. No migration is part of this correction.
- *Environment incident (mine, recorded).* A diagnostic `uv run --python 3.12` in the main checkout rebuilt the project `.venv` with Python 3.12 and without the `dev` extra, so the first shard launch stopped at its partition check ("No module named pytest", no test run). The environment was restored with `uv sync --frozen --extra dev --python 3.13`: Python 3.13.12, pytest 9.1.1, editable `src`. Every main-checkout result above (the focused runs, the static checks, Alembic and the mutations) ran before that rebuild, on the original 3.13 environment.

**Named adaptations and file changes for review.**
- Production:
  - `domain/access.py`: `AuthorityStatement` and `build_authority_statement` (R1); the subject assistant-GM source (R2);
  - `queries/control_assignments.py` (R1; `get_character_control` replaced by `read_character_control`);
  - `api/control_assignments.py` (R1);
  - `domain/authorization.py` and `domain/authorization_requirements.py` (R2);
  - `commands/assign_control_delegation_plans.py` (R2).
- Tests:
  - new: `test_control_assignment_read_snapshot.py`, `test_assign_control_delegation_recipient_final.py`, `tests/unit/test_s02_r2_recipient_requirement.py`, `test_control_unique_wait_evidence.py`;
  - strengthened (assertions and docstrings only): the three declared route tests;
  - one assertion added to S01's E32;
  - the R01 O-1 `require` pin.
- Docs: ACCESS_CONTROL §3z and §3aa; this plan's sections 3.1, 3.2, 6, 7 and 11.5; the S01 plan §12.2 case ranges; the register.
- No lock or lock-order change, no R01 checker weakened, no reviewed-table exemption, no capability adoption, no migration.

**Remaining limitations.**
- **The expiry case (H23).** It depends on one bounded interval: `expires_at` is set one second after the request is parked before its role lock, and the request must reach its eligibility read inside that second. The case asserts this from the request's own bound parameter, so a slow machine makes it fail inconclusively, never pass falsely.
- **The R3 limits.** As stated in the S02-R3 design above.
- **The R1 contract.** It is statement coherence. A revocation that commits after the read's statement does not retract the response (F36), by design.
- **Unchanged history.** The T01 and T02 history in section 11.3, Luna's review checks in section 11.4, the environmental `test_config` failure and the earlier unexplained anomalies remain as recorded.
- **Not done.** Exact-head CI and the integrated C11 acceptance and full-backend evidence are pending the checkpoint PR. No PR, merge, consumers, browser or AX checks, pilots or acceptance.
