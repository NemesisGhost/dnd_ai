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
