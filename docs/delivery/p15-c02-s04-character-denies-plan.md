# D/P15-C02-S04 implementation plan: manage approved character-scoped denies

**Status:** Opus plan prepared 2026-11-21; **owner decisions recorded 2026-11-21** (OD-S04-1 = A, OD-S04-2 = A; [§10.1](#101-owner-decisions-recorded-2026-11-21)) and the contract refined from the code ([§10.2](#102-verified-effects-and-refinements-sonnet-2026-11-21)). T01 and T02 are implemented ([§11.3](#113-implementation-record-sonnet-2026-11-21-independent-review-pending)); independent review is pending. Work-register row: [D/P15-C02-S04](work-register.md#p15-c02-s04), tasks [T01](work-register.md#p15-c02-s04-t01) and [T02](work-register.md#p15-c02-s04-t02). Parent checkpoint: [D/P15-C02](work-register.md#p15-c02).

**Baseline.** Read at `0d8d494fcf7535c6cbaf77be425ce8661e16e4cc` ("docs: record P15-C02-S03 independent review (11.4); T01, T02 and S03 pass with verification limits"), the finalized S03 records commit.
- It is the head of `phase15/completion` and equals `origin/phase15/completion`. The worktree was clean. No repository-path `AGENTS.md` exists.
- It is also the head of **PR #71** (open, draft, base `main`). This plan does not change PR #71.
- **CI as read on 2026-11-21:**
  - run `44965989830` for `0d8d494` was **in progress**, and is not a pass;
  - run `44961622195` for `98b0238` **succeeded**, as recorded in [S03 §11.4](p15-c02-s03-reveal-delegations-plan.md#114-independent-implementation-review-of-t01-t02-and-combined-s03-codex-2026-11-21);
  - run `44951144761` for `3381f7e`, recorded in the register as "in progress", has since **completed with failure**. Its one failed job is "Portal tests, lint, and build". In its failed log, one S01 test failed: `src/pages/CharacterPublicProfilePage.test.tsx` › "Cancel still returns focus to Release". The next run, `44961622195`, passed the same suite on a later head. It is one observed failure, not diagnosed here and not shown to repeat. It is recorded for the C02 checkpoint (§7.2), not as an S04 defect.
- **Preserved review records.** The following are unchanged:
  - S01's pass with verification limits ([S01 plan §11.4 to §11.8](p15-c02-s01-draft-release-plan.md#118-f1-r1-independent-confirmation));
  - S02's passes with verification limits ([S02 plan §11.14](p15-c02-s02-revelations-plan.md#1114-independent-confirmation-of-r-s02-4a-and-r-s02-4b-codex-2026-11-21));
  - S03's passes with verification limits ([S03 plan §11.4](p15-c02-s03-reveal-delegations-plan.md#114-independent-implementation-review-of-t01-t02-and-combined-s03-codex-2026-11-21));
  - every historical local shard failure and its separately recorded reruns.

**How each statement was established.** By reading source, documents and git/GitHub metadata at the baseline. No application, test or probe was run, and no application, test, schema or backend file changed.

**Contract sources.**
- Commands:
  - `src/dnd_ai/commands/access_grants.py`: `_validate_resource_grant_target` and its `_CHARACTER_ENTITY_TYPE_CODES` exception, `_resolve_grantable_capability_id`, `create_resource_grant` and `revoke_resource_grant`;
  - `commands/access_grant_plans.py`.
- Routes:
  - `src/dnd_ai/api/access_grants.py`: `POST /campaigns/{id}/resource-grants` and `…/{resource_grant_id}/revoke`;
  - `api/access_overview.py`.
- Queries: `queries/access_overview.py` (`list_grantable_resource_capabilities`, `list_assignable_campaign_characters`, and the member and group grant rows) and `queries/effective_access.py`.
- Domain rules:
  - `domain/access.py`: `RESOURCE_GRANT_CAPABILITY_CATALOG`, `GENERIC_TARGET_CAPABILITY_CODES = {campaign.view, canon.edit}` and `CHARACTER_TARGET_CAPABILITY_CODES`;
  - `domain/public_profiles.py`: `whole_character_denied`, `canon_edit_denied_for_character` and `has_effective_character_canon_edit`;
  - `domain/player_profiles.py`.
- Design and decisions:
  - [shared characters §8](shared-characters.md#8-a2a-review-correction-a2a-r-making-the-d8-denies-creatable-proposed-def-018) (A2a-R, DEF-018) and §5.7a (D8);
  - the owner's 2026-11-07 answers Q1 (deny only), Q2 (portal control waits for A6, now this slice) and Q3 (DEF-016 separate);
  - [DEF-016](defects.md#def-016--a-per-character-canonedit-deny-is-not-read-by-the-view-tier-and-inventory-resolvers);
  - [ACCESS_CONTROL](../api/ACCESS_CONTROL.md) resource grants (§3k) and the A2a-R note.
- Portal:
  - `portal/src/components/AddResourceGrant.tsx`, `AddGroupResourceGrant.tsx`, `ResourceTargetSelector.tsx`, `RevokeResourceGrant.tsx` and `EffectiveAccessPanel.tsx`;
  - `hooks/useAddResourceGrant.ts`, `useAddGroupResourceGrant.ts`, `useRevokeResourceGrant.ts` and `useAccessWriteCompletion.ts`;
  - `pages/AccessPage.tsx` and `pages/CampaignAccessPage.tsx`;
  - `types/accessOverview.ts` and `types/effectiveAccess.ts`.
- Standards: [portal behavior §6.4](../reference/portal-behavior.md#64-access-management), the register's [execution stages and review gates](work-register.md#execution-stages-and-review-gates), and the [grading rubric](grading.md).

---

## 1. Entry readiness

### 1.1 Prerequisites

| Requirement | Source | State at the baseline |
|---|---|---|
| Checkpoint entry criteria: `a4` merged, `r01` owner accepted | [C02 criteria](work-register.md#criteria-p15-c02) | Met; confirmed in [S01 plan §1](p15-c02-s01-draft-release-plan.md#1-entry-readiness). Nothing since changes them |
| Slice-specific gate | S04 row: "Checkpoint entry criteria; no additional slice-specific gate" | None |
| Task gates | T01, T02: "Completed Opus plan for P15-C02-S04 and its required slice prerequisites" | This plan. It is complete except for OD-S04-1 |
| Backend deny contract | A2a-R (DEF-018), reviewed in the A2a records | **Present.** The command accepts a character, npc or player-character entity under `entity_id` for a `deny` of `campaign.view` or `canon.edit`, and refuses the matching `allow` (§2.1) |
| Other slices | None named | S01 to S03 are reviewed. S04 uses none of their code. Its "reveal authority survives the edit-only deny" criterion meets S01's release, S02's `can_reveal` and S03's delegation read (§2.3) |

`a5c`, `copy-ui` and `preview` are not S04 prerequisites.

### 1.2 Readiness verdict

- **S04 is eligible.**
- **T01 cannot start until OD-S04-1 is recorded.** The server answers which permissions may be granted for which target kind. It does not say that a character may be an `entity_id` target, or that it may be one only for a deny of two codes (gap G-1, §2.4). Building T01 on today's contract would make the browser hold a target policy that only the command enforces.
- **T02 depends on T01's offer**, not on a further owner decision. Its display and revoke paths use existing contracts.
- **OD-S04-2 has a recommended default.** It is not blocking unless the owner chooses option B or C.

### 1.3 C02 merge scope (unchanged)

C02 merges only with S01 to S04 together. Every included slice must be independently reviewed, the PR acceptance cases must pass, and CI must pass on the integration head ([register execution stages](work-register.md#execution-stages-and-review-gates); [S02 plan §1.3](p15-c02-s02-revelations-plan.md#13-does-c02-merge-only-with-s01-to-s04-together); the owner's OD-2 of 2026-11-21). S04 is the last C02 slice. Its review completes the set of slice reviews but is not, by itself, merge readiness (§7.2).

---

## 2. Verified current behavior

### 2.1 Write routes (existing; A2a-R)

| Route | Gate | Body | Result |
|---|---|---|---|
| `POST /campaigns/{campaign_id}/resource-grants` | `access.manage` (route dependency). No ownership check; any holder may deny anyone, including a co-owner or themselves | `{capability_code, effect, grantee_campaign_membership_id \| grantee_access_group_id, <one target column>, reason?}` | 201 `{resource_grant_id}` |
| `POST /campaigns/{campaign_id}/resource-grants/{resource_grant_id}/revoke` | `access.manage` | none | 200 `{resource_grant_id}`. An already-revoked grant is a documented no-op with no audit row |

**Both are keyed.** They support `Idempotency-Key` through the R01 S5-E4 pre-write plan: a replay with the same key and body returns the stored receipt, and the same key with another body is the idempotency 409. Unlike S03's routes, a deliberate retry with the reserved key is replay-safe. The portal's existing hooks already reserve one key per identical body and reuse it on a retry (`useAddResourceGrant.resolveIdempotencyKey`).

**What the command accepts for a character** (A2a-R §8.3, read in `_validate_resource_grant_target` and `_resolve_grantable_capability_id`):

| Target column | Target | Capability | Effect | Result |
|---|---|---|---|---|
| `entity_id` | an active character, npc or player character of the campaign's world | `campaign.view` (the whole-character deny) or `canon.edit` (the per-character `canon.edit` deny) | `deny` | Accepted |
| `entity_id` | the same | either | `allow` | 404 (`TargetNotInCampaignWorldError`), nothing written |
| `entity_id` | the same | any `character.*` code | either | 404 (capability catalog) |
| `character_id` | a character | a `character.*` code | either | Accepted (the existing catalog; unchanged) |
| `character_id` | a character | `campaign.view` or `canon.edit` | either | 404 (catalog) |

**Other refusals:**
- an archived or other-world character: 404;
- an ended, inactive or foreign grantee: 404;
- an identical active deny: 409 (`ux_resource_grants_active`);
- a caller without `access.manage`: 403.

All refusals are non-disclosing.

### 2.2 What the two denies do (backend; unchanged by S04)

- **Whole-character deny (`campaign.view`).** The caller cannot read the character anywhere a reader checks it: character detail, sheet, parties, relationships, inventory, rosters, event explanations, World Explorer, public profile, revelations, and the surfaces that render a revealed character. It binds owners and delegated GMs too. A denied owner keeps `access.manage` and can still remove the deny.
- **`canon.edit` deny.** It is operation-specific, per ADR 0021 §2.9. Through `has_effective_character_canon_edit` it blocks:
  - saving the character's public-profile draft (403 `public_profile_edit_denied`);
  - the GM branch of the player profile (D15, `domain/player_profiles.py`).

  A GM with no reveal authority also loses the public-profile read, since their read rests on effective `canon.edit`. **Reveal authority is untouched.** An owner or delegated GM under this deny can still read, release and reveal.
- **DEF-016 (open, owner's separate decision).** A `canon.edit` deny does **not** lower the GM-tier character view or the inventory, and does not stop other character authoring. Those readers look under `character_id`.

### 2.3 Backend proofs that already exist (slice criteria)

| Criterion | Existing proof |
|---|---|
| Both denies are creatable through the route, the allows are refused, and a `character.*` code under `entity_id` is refused | `tests/database/test_character_public_profile_grant_denies.py::test_the_grant_route_creates_both_denies_and_refuses_allows_and_wrong_targets`; `test_resource_grant_target_column.py` |
| Key replay and duplicate refusal | `…grant_denies.py::test_the_grant_route_replays_a_key_and_refuses_a_duplicate` |
| Archived and foreign-world characters, and other own-column kinds, are refused | `…::test_the_grant_route_refuses_an_archived_character_a_foreign_world_and_other_own_column_kinds` |
| Self-deny binds, and the self-denied owner can still revoke | `…::test_a_whole_character_deny_binds_a_delegated_gm_and_an_owner_who_denies_themselves` |
| `canon.edit` deny: no save, but reading and releasing continue | `…::test_a_canon_edit_deny_on_an_owner_blocks_saving_not_reading_or_releasing` |
| `canon.edit` deny does not stop a revelation | `test_character_revelations.py::test_a_whole_character_deny_is_404_and_a_canon_edit_deny_does_not_stop_a_revelation` |
| Member and group grantees; a group deny follows group membership and deactivation | `…grant_denies.py::test_a_group_deny_follows_membership_changes_on_the_next_request`, `…::test_deactivating_a_denying_group_lifts_it_and_reactivating_does_not_restore_it`, `…::test_a_group_canon_edit_deny_blocks_saving_for_an_owner_added_to_it` |
| The overview and the explanation name the denied character | `…::test_the_overview_and_the_effective_access_explanation_name_the_denied_character` |
| Raw allow rows under `entity_id` change no reader | `…::test_raw_allow_rows_under_entity_id_change_no_current_reader` |

**Not yet proven:** that S03's new `GET …/reveal-delegations` still reports the delegation as effective under a `canon.edit` deny. The criterion "separate reveal authority survives the edit-only deny" meets that read for the first time here. BD6 adds the proof (§6.3).

### 2.4 What the client can learn today: the gaps

| Gap | Evidence | Consequence |
|---|---|---|
| **G-1 (blocking T01): no server value names the character-deny option** | `list_grantable_resource_capabilities` returns one row per `(code, target_type)` from the catalog: `(campaign.view, entity)`, `(canon.edit, entity)` and the nine `(character.*, character)`. Its docstring says the grain "is coarser than one sub-rule": a character is accepted under `entity` for a deny of these two codes only. `assignable_characters` lists the world's active characters, but nothing ties them to the `entity` rows or to `deny` | To offer the option today, the portal would hard-code three facts the server alone enforces: characters may be `entity_id` targets; only for `deny`; only for these codes. If the policy changed (for example, DEF-016's resolution adding a code), the portal would offer a refused write or hide an accepted one |
| **G-2 (copy, not blocking): `canon.edit` on a character does less than its name says** | DEF-016 (§2.2) | A label such as "Edit canon" invites an owner to believe the GM can no longer edit or see the character. See OD-S04-2 |
| **G-3 (not blocking): the overview row does not say that an `entity` target is a character** | `MemberResourceGrantView` carries `target_type: "entity"`, `target_id` and `target_display_name`, which A2a-R fills only for a character | T02 can still identify a character deny without inference: its `target_id` is in the overview's own `assignable_characters`, and its code is in the server's deniable list (D-6). Both are server data from the same read. No backend change |
| **G-4 (observation, out of scope): the explanation labels a character denial by raw code and "Entity"** | `EffectiveAccessPanel` renders `campaign.view — Entity (Aria)`; `EffectiveAccessDenial` has no `target_id` | Correct but cryptic. A clearer label needs a target id or kind on the denial, a backend change outside S04's criteria. Recorded as O-2 (§10) |

### 2.5 Portal at the baseline

- **Where grants live.** The Access page (`/app/:campaignId/access`) lists each member's and each group's direct resource grants with **Revoke access** or **Remove denial**. It renders the A2a-R character name for a character deny that already exists (raw SQL or the API), as "View Campaign (Deny) on Aria".
- **Grant forms.** `AddResourceGrant` (members) and `AddGroupResourceGrant` (groups) build a type → resource → effect → permission cascade from `grantable_resource_capabilities`.
  - The `entity` picker deliberately excludes characters (`ResourceTargetSelector.tsx` `EntityPicker` category filter; P-8).
  - The `character` type writes `character_id`, whose catalog refuses both codes.
  - So the portal cannot create either deny.
  - A deny needs the existing confirmation checkbox. Pickers auto-select the first option.
- **Authority binding.** `CampaignAccessPage` mounts the overview only while the applied session grants `access.manage` (C01-S02). Losing it unmounts every card, form, hook and in-flight request. Regaining it starts a fresh read with everything closed.
- **After a write.** Hooks call `onChanged`, which announces in the page's persistent `role="status"` region and re-reads the overview. That unmounts the page body while loading. Open cards and explanations are kept by id (`useAccessDisclosure`), so an open explanation re-mounts and re-reads. `useAccessWriteCompletion` then reloads the session when the write may affect the caller (the caller's own card, or a group they are in), or re-reads it in place otherwise.
- **Failures.** 403 and 404 both show "You do not have permission to make this change." 409 and 400 show "changed elsewhere. Reload". Anything else shows "could not be added. Try again." A retry with the same body reuses the reserved key. 401 reloads the session. Unmount aborts and drops the key.

---

## 3. Outcome, scope and exclusions

### 3.1 User outcome

An access manager can deny one member or one access group either:
- **everything about one character** (the whole-character deny); or
- **editing one character's profiles** (the per-character `canon.edit` deny).

They do it from the existing Access page, choosing the character explicitly. They can see each deny on the member's or group's card in plain words, and remove it through the existing revoke. After either change, the member list and any open "What can this person do?" explanation are read again from the server, so the remaining sources and denies shown are current.

### 3.2 In scope

- **T01, the offer.**
  - The server lists the deniable character permissions (OD-S04-1).
  - The member and group grant forms gain one target kind, **Character (deny only)**. Its rules:
    - it appears only when the server lists at least one deniable permission and at least one character;
    - the effect is fixed to Deny;
    - there is no auto-selected character;
    - permissions come from the server list, minus any already actively denied for that character and grantee;
    - the existing deny confirmation applies;
    - the request writes `entity_id` with `effect: "deny"` and the existing `Idempotency-Key`.
  - Accurate hint text for each permission (OD-S04-2).
- **T02, the display, removal and reconciliation.**
  - Character denies are labelled in plain words on member and group cards and in the Remove denial confirmation.
  - Unknown-outcome and refusal copy for the new kind.
  - A 403 from any resource-grant write re-reads the session in place, so a lost `access.manage` unmounts the page.
  - Focus after the list re-read.
  - Tests that the explanation's sources and remaining denies are re-read after add and remove, and after group-membership and target changes.

### 3.3 Exclusions

- **No change to the existing allow catalog or to the existing kinds' behavior.**
  - The `character` (character_id), `entity`, `event`, `knowledge_item`, `quest` and `session` kinds keep their options, auto-selection, copy and status mapping.
  - Only the 403 session re-read (D-4) is shared, and it narrows nothing.
- **No allow on a character under `entity_id`** (Q1), and no `character.*` code under `entity_id`.
- **No DEF-016 fix.** The `canon.edit` deny's effect is described, not widened (OD-S04-2).
- **No new route, lock, write, authorization rule or schema.** Under OD-S04-1 = A, one additive field is added to an existing read.
- **No change to S01, S02 or S03 code or records**, to the Reveal authority tab, or to revelations.
- **No explanation-label redesign** (G-4, O-2) and no copy change on the existing kinds' error messages (O-1).
- **No impact preview.** Portal behavior §6.4 asks for "a concise impact preview" before saving a grant. The existing forms provide the confirmation sentence, not a preview. The new kind adds per-permission hint text. A true audience preview is `preview`, an owner disposition outside S04.
- Not in this slice: `copy-ui`, `preview`, browser/AX runs, persona runs and owner acceptance.

---

## 4. Affected files and interfaces

| Area | Files | T01 | T02 |
|---|---|---|---|
| Backend read (OD-S04-1 = A) | `src/dnd_ai/queries/access_overview.py` (new `list_deniable_character_capabilities`), `src/dnd_ai/api/access_overview.py` (`deniable_character_capabilities` on `CampaignAccessOverviewResponse`) and, optionally, a named constant in `domain/access.py` (D-2) | ✓ | |
| Backend tests | `tests/database/test_api_access_overview.py` (BD1–BD5); new `tests/database/test_character_denies_and_reveal_authority.py` (BD6–BD8) | ✓ | |
| Portal types | `portal/src/types/accessOverview.ts` (optional `deniable_character_capabilities?`, so the 23 files with overview fixtures compile unchanged) | ✓ | |
| Portal forms | `components/AddResourceGrant.tsx`, `components/AddGroupResourceGrant.tsx`, `components/ResourceTargetSelector.tsx` (a `CharacterDenyPicker` without auto-select), a small shared `utils/characterDenies.ts` (labels, hints, the field mapping and the "is a character deny" test) | ✓ | |
| Portal display and removal | `pages/AccessPage.tsx` (labels), `components/RevokeResourceGrant.tsx` (labels and confirmation for a character deny), and `hooks/useAddResourceGrant.ts`, `useAddGroupResourceGrant.ts` and `useRevokeResourceGrant.ts` (403 → in-place session re-read, D-4) | | ✓ |
| Portal tests | `components/AddResourceGrant.characterDeny.test.tsx`, `components/AddGroupResourceGrant.characterDeny.test.tsx`, `pages/CampaignAccessPage.characterDeny.integration.test.tsx`, and the three hooks' tests | ✓ | ✓ |
| Docs | [ACCESS_CONTROL](../api/ACCESS_CONTROL.md) (the overview field and the A2a-R note: "the portal offers both denies from S04"); [portal behavior §6.4](../reference/portal-behavior.md#64-access-management) (a **Character denials** entry); the `list_grantable_resource_capabilities` docstring (its "until A6" sentence); `ResourceTargetSelector.tsx`'s P-8 comment. No catalog row changes, since no route is added | ✓ | ✓ |

---

## 5. Task commits

| Task | Commit message | Content |
|---|---|---|
| T01 | `P15-C02-S04-T01: offer the whole-character and canon.edit denies on a character from a server-listed option` | Backend first (OD-S04-1 = A): the query, the response field, BD1–BD8 and docs. Then the portal: type, picker, both forms, hint copy, O1–O16, and docs. One commit, like S03-T01. If the shard run finds a needed adjustment, a follow-up commit names it, as S03's `5e1a22e` did |
| T02 | `P15-C02-S04-T02: show and remove character denies in plain words and re-read effective access after permission or target changes` | Labels, confirmation, refusal and unknown-outcome copy, the 403 session re-read, focus after the re-read, R1–R18, and the portal-behavior entry |

Each commit leaves the tree working: T01 alone offers and creates the deny, and the existing generic rendering shows it. Nothing is pushed by the implementer unless asked.

---

## 6. Acceptance cases

Fake-server portal tests unless marked. "Re-read" means a new request whose response is the one rendered, never a locally edited list.

### 6.1 T01: the offer (O1–O16)

| # | Case |
|---|---|
| O1 | A member card's **Add direct resource access** lists **Character (deny only)** as a type when the overview has a non-empty `deniable_character_capabilities` and at least one `assignable_characters` entry. It is absent when either is empty, or when the field is missing (an older fixture) |
| O2 | The same for a group's form. It is absent for an archived group (the existing `isActive` rule) |
| O3 | **The allow catalog is preserved.** With the new field present, the existing types, their order, their permission lists for Allow and Deny, and their pickers are identical to those without it (snapshot of the option lists). Choosing **Character** (character_id) still offers only `character.*` codes |
| O4 | In the new kind there is no Allow control. The effect is Deny, stated in text, and the deny confirmation is required |
| O5 | **No implicit target.** The character select starts on "Choose a character". Add stays disabled until a character, a permission and the confirmation are chosen. A list change never moves an existing choice to another character (D-3) |
| O6 | The permission list is exactly the server's `deniable_character_capabilities`, in server order, labelled from the portal's copy for known codes (OD-S04-2, corrected copy in §10.2) and by the server `display_name` for an unknown code (hint: none beyond the label). Each known code has its hint, and the hint text equals §10.2's, which states only effects the code and the existing tests establish |
| O7 | **Request body:** `entity_id` is the chosen character, with `effect: "deny"`, the chosen `capability_code`, and exactly one grantee (membership or group). No `character_id` and no `reason` unless the existing form collects one. Headers: CSRF and `Idempotency-Key` |
| O8 | **Duplicates.** A permission already actively denied to this grantee for this character (an existing grant with `target_type: "entity"`, the same `target_id`, `effect: "deny"` and the same code) is not offered. When none remain, the form says "Both denials are already in place for this character" and offers no Add |
| O9 | **Pending.** Every control is disabled and the button is busy. A second submit sends nothing |
| O10 | **Success.** The page's persistent region announces "Denial added." The overview is re-read, and the new grant appears on the card. When focus was displaced, it moves to that card's **Direct resource access** heading, or to the status region if the card is gone (D-5) |
| O11 | **Unknown outcome** (network error or 5xx). The form stays open with its selection and says "We couldn't confirm whether the denial was added. Trying again sends the same request and can't add it twice." **Try again** resends the identical body with the **same key**. Changing any selection drops the key, and the next send uses a new one |
| O12 | **409** (duplicate or idempotency conflict): "This denial may already be in place. Refresh the access list to see the current state." with **Refresh access list** (a read only). No resend |
| O13 | **404**: "That character or member is no longer available for a denial." No retry is offered. **Refresh access list** is offered |
| O14 | **403**: "You no longer have permission to manage access." The session is re-read in place (D-4). When the fresh session lacks `access.manage`, the page body unmounts: form, selection and status are gone. When it still has it, the form stays with the message |
| O15 | **Authority loss while pending.** A session change that removes `access.manage` mid-request unmounts the form. The request is aborted, nothing is announced, and a late response does not render |
| O16 | **Navigation.** Changing campaign, or to another Access tab, mid-request aborts it. No announcement reaches the new page. A return mounts a fresh overview with the form closed |

### 6.2 T02: display, removal and reconciliation (R1–R18)

| # | Case |
|---|---|
| R1 | A member's character deny renders as "Denied: everything about Aria" or "Denied: editing Aria's profiles". A grant counts as a character deny only when it is a `deny` with `target_type: "entity"`, its code is in `deniable_character_capabilities`, and its `target_id` is in the same overview's `assignable_characters` (D-6). Every other grant renders exactly as before |
| R2 | The same on a group card |
| R3 | **Remove denial** names the character and the denial. The confirmation says that access may return from another source, which is true for the whole-character deny. For `canon.edit` it says editing may return. It calls the existing revoke route with a key |
| R4 | Revoke success announces "Denial removed." and re-reads the overview. The deny is gone. Focus follows D-5 |
| R5 | **Effective access after add.** With that member's explanation open, adding a whole-character deny re-reads the explanation, which lists the denial with the character's name, from the new response |
| R6 | **Effective access after remove; remaining denies.** With two character denies and the explanation open, removing one re-reads the explanation, which still lists the other and not the removed one |
| R7 | **Group deny reaches a member.** A group deny re-reads an open explanation of a group member, which lists it. Removing that member from the group (the existing control) re-reads it, and the explanation no longer lists the denial |
| R8 | **Group deactivated.** Deactivating the denying group (the existing control) re-reads the overview. The group's grants show as the server returns them (revoked, so absent), and an open explanation no longer lists the denial |
| R9 | **Target change.** The next overview omits an archived character's deny and that character in the picker. The form, which was closed by the re-read, offers no option for it |
| R10 | **Self-deny.** On the caller's own card, adding a whole-character deny reloads the session (the existing `affectsCaller`). The page returns with the deny listed and **Remove denial** available, because the owner keeps `access.manage` |
| R11 | **Revoke unknown outcome.** Network error or 5xx: "We couldn't confirm whether the denial was removed. Trying again sends the same request." **Try again** reuses the same key |
| R12 | **Revoke of an already-revoked deny** (the server's 200 no-op) is reported as removed, and the re-read shows the server's state |
| R13 | **Revoke 403** re-reads the session in place, as in O14. **Revoke 404**: "This denial is no longer available." with **Refresh access list** |
| R14 | **Authority restoration.** After a loss (O14), a session that grants `access.manage` again mounts a fresh overview read with every card, form and explanation closed and no old message |
| R15 | **Late response.** A revoke response arriving after an overview re-read that already lacks the grant does not re-announce or move focus twice |
| R16 | **Disclosure.** No resource-grant id, character id, reason text from another grant, server message or audit data is rendered or announced by the new kind or labels |
| R17 | The existing allow grants' display, revoke text and status messages are unchanged (regression on the existing Access page tests) |
| R18 | The 403 re-read also applies to the existing kinds' writes (D-4). A test for one existing kind shows the session is re-read and nothing else changes |

### 6.3 Backend cases (database tests; BD1–BD5 only if OD-S04-1 = A)

| # | Case |
|---|---|
| BD1 | `GET …/access-overview` returns `deniable_character_capabilities` = `[campaign.view, canon.edit]` with `capability_id`, `code` and `display_name`, in a stable order |
| BD2 | `grantable_resource_capabilities` is unchanged: the same set as the catalog-derived list at the baseline (an exact set comparison) |
| BD3 | **The list matches the command.** For each listed code and each of character, npc and player character, the route accepts a membership deny under `entity_id` (201), and the matching `allow` is 404. A generic code absent from the list would be refused. The test iterates the response, so a list or command drift fails it |
| BD4 | A deactivated capability (`is_active = false` in the test transaction) is omitted from the list, as from `grantable_resource_capabilities` |
| BD5 | The field is campaign-independent and identical for every reader who passes `access.manage`. A player is refused the overview (existing) |
| BD6 | **Reveal authority survives the edit-only deny.** An owner grants a delegation to a GM (S03 route). An access manager denies that GM `canon.edit` on a character through the route. Then:<br>• `GET …/reveal-delegations` still shows the GM's delegation as effective;<br>• `GET …/revelations` for the character returns `can_reveal: true`;<br>• `GET …/public-profile` returns 200 with `can_edit: false` and `can_release: true` (the GM reads through reveal authority);<br>• saving the draft is 403 `public_profile_edit_denied`;<br>• a revelation create succeeds (201) and a release succeeds (201). |
| BD7 | **The whole-character deny is narrower than the delegation.** The same GM under a whole-character deny on that character gets 404 on its revelations and profile. `GET …/reveal-delegations` still lists the delegation, because nothing revoked it. A revelation of another character still succeeds |
| BD8 | Removing the BD6 deny through the revoke route restores `can_edit: true` on the next request, and the delegation is unchanged |
| BD9 | **What the edit-only deny takes away besides saving** (the facts the hint states, §10.2). For a built-in GM who holds `canon.edit` and has no reveal authority, a `canon.edit` deny on the character makes the public-profile read 404 while the same GM keeps `GET …/characters/{id}` (the DEF-016 limit) and a player-profile read is 404 for every GM under the deny. A character other than the denied one is unaffected |

BD6–BD8 are worth adding under either option: they are the only proof that S03's new read and the S04 denies agree.

---

## 7. Verification

### 7.1 Automated checks (per commit, by Sonnet; again by the independent reviewer)

- **From `portal/` in PowerShell:** `npm test` (with counts), `npm run lint` and `npm run build`.
  - Run the new S04 tests plus `pages/CampaignAccessPage.resourceGrant.integration.test.tsx`, `pages/CampaignAccessPage.effectiveAccess.integration.test.tsx`, `pages/AccessPage.test.tsx` and the three hook tests, and report those counts separately.
  - S01's, S02's and S03's focused suites must still pass unchanged.
- **Backend (T01):**
  - `uv run pytest tests/database/test_api_access_overview.py tests/database/test_character_denies_and_reveal_authority.py tests/database/test_character_public_profile_grant_denies.py tests/database/test_resource_grant_target_column.py`;
  - `ruff format --check`, `ruff check` and `mypy src`;
  - the shard runner `uv run python scripts/run_sharded_tests.py`, because a shared read's response changes.
- **From the repository root:** `uv run python scripts/check_documentation.py` and `git diff --check`.
- **Mutation probes** (at least one per commit, restored, with SHA-256 recorded before and after):
  - T01: offer Allow in the new kind, or write `character_id`. O4 or O7 must fail.
  - T01: auto-select the first character. O5 must fail.
  - T01, backend: add `character.view_full` to the deniable list. BD3 must fail.
  - T02: identify a character deny by a non-null `target_display_name` alone, or skip the explanation re-read. R1 (with a crafted non-character name) or R6 must fail.
- **Recording runs:** report first runs and reruns separately. A full-suite failure is recorded as it happened, and an isolated rerun is not a suite pass.

### 7.2 C02 checkpoint integration (not S04's verdict)

S04's independent review completes the four slice reviews. **C02 merge readiness is a separate judgment.** It needs:
- the PR acceptance cases on the integrated head;
- CI passing on that head.

It must also account for:
- the observed `44951144761` portal failure (one S01 focus test). Show whether it repeats before it is called non-repeatable;
- run `44965989830`'s outcome for `0d8d494`.

This plan claims no merge readiness. A green PR #71 run belongs to its head only.

### 7.3 Separate events (not S04's review verdict, and not C02 merge gates)

- **Persona browser checks** at the final integrated head, under [browser](work-register.md#browser):
  - **pending from S03:** the owner grants to a GM, and that GM's next reveal succeeds; the owner revokes, and the GM's next reveal is refused;
  - **added by S04:** the owner denies that delegated GM `canon.edit` on a character, and the GM can still reveal and release it but cannot save its draft;
  - a whole-character deny hides the character from the GM's pages;
  - a self-deny can be removed by the owner;
  - a group deny follows membership.
- **AT checks** under [ax](work-register.md#ax) and [b16](work-register.md#b16): the type select and the new picker's labels; the confirmation; hint association; announcements in the persistent region; focus after the re-read; reflow at 320 CSS px and at actual zoom.
- **Owner acceptance** at [actor-a](work-register.md#actor-a) and [p15-owner](work-register.md#p15-owner).

None of these is performed, accepted or waived here, and none is marked complete by S04's review.

---

## 8. Authorization, disclosure, concurrency and cleanup

- **Who may act.** Any `access.manage` holder, exactly as the route allows. The portal binds the whole page to the applied session's `access.manage` (existing). S04 adds no ownership rule. A deny of a co-owner, or of oneself, is allowed (A2a-R §8.4) and is offered on every member card.
- **Precedence.** Deny wins in `grant_effects` over every allow source: role, relationship, group, direct allow and revelation. S04 does not restate it in the browser. The copy says what the deny blocks (OD-S04-2) and, on removal, that access "may return from another source".
- **Overlapping sources.** Membership and group denies, and a raw stray row, are distinct rows that all count. The card shows the member's direct denies, and each group's card shows its own. Only the server's explanation combines them (R5–R8). The portal never computes "is this member denied".
- **Target safety.** Characters come only from the overview's `assignable_characters` (active, the campaign's world, access-manager audience). There is no implicit first choice (D-3). The overview re-read after any write unmounts the form, so a selection cannot outlive the list it came from. A concurrent archive gives 404 (O13).
- **Protected-state cleanup.**
  - Loss of `access.manage` unmounts the overview, cards, forms, selections and in-flight writes (existing; O14, O15).
  - A 403 now triggers the session re-read that discovers it (D-4).
  - Navigation aborts (O16).
  - The new kind keeps no data outside the overview's boundary.
- **Pending and uncertain writes.** Both routes are keyed. A deliberate **Try again** with the same body reuses the reserved key and is a safe replay. The server returns the stored receipt, or 403 first if `access.manage` was lost, because the route dependency runs before the replay lookup.
  - There is no automatic retry.
  - An aborted write (navigation or unmount) drops its key. Its outcome is unknown, and the next overview read shows it.
  - A later fresh send of the same deny is at worst a 409 duplicate (the unique index), never a second active row.
- **Retry ownership.** Only the open form owns a retry. Once the form is closed or unmounted, the only recovery is a read (**Refresh access list**).
- **Concurrency.** The command's lock order is unchanged (grantee, campaign, account, target `FOR UPDATE`, capability). The A2a-R race tests cover a deny against a release and a save. S04 adds no lock.

---

## 9. Intermediate states

| After | State |
|---|---|
| T01 | Access managers can create both denies for members and groups. Existing cards show them in the generic form ("View Campaign (Deny) on Aria"), which is accurate but terse. Removal works through the existing control. Failures use the T01 copy. The 403 session re-read is not yet in place |
| T02 | Plain-word labels, removal copy, the 403 re-read, focus and the reconciliation tests. S04 is complete for review |

Neither state changes S01 to S03 behavior.

---

## 10. Decisions

### 10.1 Owner decisions recorded 2026-11-21

- **OD-S04-1 = option A.** An additive `deniable_character_capabilities` field on the access overview, derived from the server rule. No portal constant (B) and no change to `grantable_resource_capabilities` (C).
- **OD-S04-2 = default A.** Offer the existing `canon.edit` deny with precise wording about what it does now. DEF-016 is not resolved and the deny's semantics are not widened. The wording below (§10.2) replaces the draft wording in this section's option text, because the code check found the draft wording inaccurate.

The alternatives are kept below as decided-against records.

### OD-S04-1 (decided: A): how the portal learns which denies a character may receive

**A (recommended). Add one field to the existing overview.**
- **The field:** `GET …/access-overview` gains `deniable_character_capabilities: [{capability_id, code, display_name}]`, the active capabilities a character may be denied under `entity_id`.
- **Its source:** the same catalog entry and guard the command enforces (D-2). BD3 pins the list to the command.
- **Cost:** about 25 lines of query and DTO code, the BD1–BD5 tests and the doc note. The portal type is optional, so none of the 23 files with overview fixtures changes.
- **What it leaves alone:** no route, lock, write or authorization rule, and the existing `grantable_resource_capabilities` contract.

**B. Portal constant.**
- **How it works:** the portal intersects a fixed `{campaign.view, canon.edit}` with the server's `entity` rows, and treats a character under `entity` as deny-only. The server's 404 is the backstop.
- **What it saves:** no backend change and no shard run for T01.
- **Why not:** it duplicates a policy the command enforces, and it is precisely the target rule A2a-R narrowed. It is admissible, since there is precedent in the `EntityPicker`'s P-8 category filter, but not recommended.

**C. Change the grain of `grantable_resource_capabilities`.** Each row would gain `effects` and the entity types it accepts. That redesigns a contract C01 reviewed, and it touches 23 fixture files and the existing forms' cascade. Not recommended.

### OD-S04-2 (decided: A, with the corrected wording of §10.2): describing the `canon.edit` deny while DEF-016 is open

**A (default). Offer it with copy that states its present effect.**
- **Label:** "Editing this character's profiles".
- **Hint (draft wording, superseded by §10.2):** "Stops them editing this character's public profile and profile notes. It doesn't change what they can see of the character or other character editing. Reveal authority is not affected."
- **The whole-character deny:**
  - label: "Everything about this character";
  - hint: "Hides this character from them everywhere in this campaign, including owners and anyone who can reveal."
- **DEF-016** stays open for its separate decision. If its fix widens the deny, the hint changes with it.

**B. Decide DEF-016 first.** S04-T01 would wait for that decision and its own backend slice.

**C. Offer only the whole-character deny now.** This contradicts the S04 criteria ("operation-specific canon.edit"), so it needs a register re-size. Not recommended.

### 10.2 Verified effects and refinements (Sonnet, 2026-11-21)

Read in code at `0d8d494` (domain `public_profiles.py` and `player_profiles.py`, commands `character_public_profile.py` and `character_revelations.py`, queries `character_public_profile.py`), against [ACCESS_CONTROL §3](../api/ACCESS_CONTROL.md) and the existing tests named. No policy changes.

| Surface | Whole-character deny (`campaign.view`, `entity_id`) | `canon.edit` deny (`entity_id`) |
|---|---|---|
| Public-profile draft **save** | 404 (the character is not visible), for every caller, owners and delegated GMs included | 403 `public_profile_edit_denied` for a caller who can still read it (reveal authority), otherwise 404. `can_edit` is false |
| Public-profile draft and release **read** | 404 for every source | Unchanged for a reveal holder. A GM without reveal authority has only effective `canon.edit` as a read source, so loses the read (`test_a_canon_edit_deny_on_an_assistant_gm_leaves_them_nothing_to_read`) |
| **Copy** legacy text or the player's profile into the draft | refused | refused (the copy needs effective `canon.edit`) |
| Player's own profile (the GM read, D15; the portal's "profile notes") | 404 | 404 for every GM (`test_a_whole_character_deny_and_a_canon_edit_deny_refuse_the_read_for_any_source`) |
| Text copied from the player's profile into a draft (restricted per field) | n/a (character gone) | **Withheld from the denied caller even with reveal authority**, so a release of a draft that holds such text is refused with `public_profile_field_withheld` for them. Legacy-origin text is judged by the role-only source rule, which per-character denies do not enter |
| **Release** (reveal authority) | 404 | Not stopped (`test_a_release_still_succeeds_for_an_owner_with_a_canon_edit_deny`), except the withheld case in the row above |
| **Reveal** (create and revoke a revelation) | 404 | Not stopped (`test_a_whole_character_deny_is_404_and_a_canon_edit_deny_does_not_stop_a_revelation`); `can_reveal` unchanged |
| Reveal-delegation read (S03) | Not consulted: the delegation is still listed, nothing revoked it | Not consulted |
| Character detail, sheet, inventory, other authoring (**DEF-016**) | 404 on every reader that checks `campaign.view` on the entity | **Unchanged** for an `entity_id` deny. The sheet test that shows a `canon.edit` deny hiding the sheet uses a raw `character_id` row, which the application cannot create |

**Inconsistencies found in the plan's draft wording, and their resolution (the backend is not changed):**
- The hint said the deny "doesn't change what they can see of the character". It does remove two reads: the public-profile read for a GM without reveal authority and the player's own profile. The hint now says so.
- "profile notes" named the wrong thing. The surface is the player's own profile of the character, which a GM reads under D15. The wording says that.
- "Reveal authority is not affected" is true, but a release can still be refused for text copied from the player's profile. The hint now says so.
- BD6–BD8 match the code. BD9 pins the two removed reads, so the hint cannot drift from them.
- The whole-character hint said "everywhere in this campaign". The code supports "wherever access to a character is checked", with the surfaces named in §2.2, not a claim about every page.

**Final copy (labels and hints; the portal uses exactly these for the two known codes):**
- `campaign.view`: label **Everything about this character**. Hint: "Hides this character from them wherever access to a character is checked, including from owners and anyone with reveal authority. It does not remove access they hold to anything else."
- `canon.edit`: label **Editing this character's profiles**. Hint: "Stops them saving this character's public profile or copying text into it, and hides the player's own profile of this character from them. Revealing and releasing stay available, except that someone who can no longer read text copied from the player's profile can't release a draft that contains it. It does not change what they see of the character or other character editing."
- Removal confirmation: whole-character, "They may regain access to {name} from another source, such as a role or relationship."; `canon.edit`, "They may be able to edit {name}'s profiles again."
- The card label for R1: "Denied: everything about {name}" and "Denied: editing {name}'s profiles". Where a second or unknown code is returned the label falls back to the server's `display_name`.

**Acceptance mapping, refined:** O1–O16 and R1–R18 are unchanged. O6, R1 and R3 test the copy above. BD1–BD5 pin the field to the command, BD6–BD8 the S03 × S04 behavior, BD9 the removed reads. The 403 session re-read (D-4) and the focus rule (D-5) are the only shared Access changes. `useAddResourceGrant`, `useAddGroupResourceGrant` and `useRevokeResourceGrant` keep every other status mapping.

**CI failure `44951144761` (investigated inside the slice's verification, not a defect assumed here):** the failing S01 test, `CharacterPublicProfilePage.test.tsx` "Cancel still returns focus to Release", is investigated in §11.3 from its log and by exercising the test. Any fix is a separate commit outside S04, and S04's records keep the finding apart from S04's verdict.

### Plan decisions (recommendations; not blocking)

- **D-1.** The offer is a separate type, **Character (deny only)**, not more permissions under the existing **Character** type. This leaves the existing kind, its auto-select and its allow catalog untouched (O3) and makes the column mapping unambiguous.
- **D-2.** Under A, the server builds the list from `RESOURCE_GRANT_CAPABILITY_CATALOG["entity_id"]`, since the guard exception admits exactly those codes for a character deny, intersected with active capabilities. A named constant may document that equality. The guard itself does not change.
- **D-3.** The new picker has no auto-select and no default (O5). For a deny, a silent first choice is a wrong-target risk. The existing pickers keep theirs.
- **D-4.** A 403 from `useAddResourceGrant`, `useAddGroupResourceGrant` or `useRevokeResourceGrant` re-reads the session in place (`refresh`, falling back to `reload`), so a lost `access.manage` unmounts the page. It narrows nothing and changes no other status.
- **D-5.** After a write's overview re-read, focus moves only if it was displaced to `body`: to the same card's **Direct resource access** heading, or else to the persistent status region. This follows the existing refresh-intent pattern in `CampaignAccessPage`.
- **D-6.** A grant is a character deny only when all hold:
  - its effect is `deny` and its `target_type` is `entity`;
  - its code is in `deniable_character_capabilities`;
  - its `target_id` is in the same response's `assignable_characters`.

  All three come from one server read. A non-null `target_display_name` alone is not enough (G-3; mutation probe in §7.1).
- **D-7.** S04 keeps the existing kinds' error copy. The new kind's unknown-outcome copy is accurate because the key is reused (O11, R11).

### Observations (not S04 scope; for the register owner)

- **O-1.** The existing grant forms say "could not be added. Try again." for a network error or 5xx, when the write may have committed. The retry is safe (same key), but the sentence can be false. This is pre-existing, and not changed here (D-7).
- **O-2.** The explanation renders a character denial as `campaign.view — Entity (Aria)` (G-4). A clearer label needs a target kind or id on `EffectiveAccessDenial`.

---

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Confirm that the register records OD-S04-1 (and OD-S04-2 if the owner chose other than A). Start from the commit that records it, or a verified descendant. Read this plan, [S03 §11.4](p15-c02-s03-reveal-delegations-plan.md#114-independent-implementation-review-of-t01-t02-and-combined-s03-codex-2026-11-21) and the files in §4.
2. **T01:**
   - Under A, implement the backend first. That is the query, the DTO field, BD1–BD8 and the ACCESS_CONTROL note. Under B, only BD6–BD8 are added.
   - Then the portal: the optional type field, `CharacterDenyPicker`, the new kind in both forms (D-1, D-3), the copy (OD-S04-2) and O1–O16.
   - Run §7.1, including the shard runner under A, and one mutation probe per bullet.
   - Commit with the §5 message.
3. **T02:** labels (D-6), the removal confirmation, the copy (D-7), D-4, D-5 and R1–R18. Run §7.1 and commit with the §5 message.
4. Record each task in §11.3: SHA, tests with counts, the shard run's first result and any rerun separately, probes with hashes, and deviations with reasons.
5. **Do not:**
   - change the existing allow catalog, the existing kinds' behavior (other than D-4), or S01–S03;
   - fix DEF-016;
   - add a route;
   - push, merge or touch PR #71;
   - start `copy-ui` or `preview`;
   - mark any browser, AX, persona or owner check complete.

### 11.2 Independent review boundary

- **Range:** the commit that records OD-S04-1, through the T02 records commit. Review T01 and T02 separately, then together.
- **Check the following:**
  - no browser-derived authority or target policy (D-6, OD-S04-1);
  - the allow catalog is preserved (O3, BD2, R17);
  - the column and effect are correct (O7, BD3);
  - no implicit target (O5);
  - replay safety and retry ownership (O11, R11, §8);
  - cleanup on authority loss, restoration and navigation (O14–O16, R14, R15);
  - explanation re-reads, with the remaining denies coming from a response (R5–R8);
  - accurate copy against DEF-016 (OD-S04-2);
  - the S03 × S04 backend proof (BD6–BD8).
- **Not in the review verdict:** C02 merge readiness (§7.2), and every §7.3 event.

### 11.3 Implementation record (Sonnet, 2026-11-21; independent review pending)

**Commits.** Planning baseline (plan with OD-S04-1 = A, OD-S04-2 = A, code-verified effects): `94edf035a2051046493268d6af61beb18989d627`. T01: `3dcd13bb85ca3ddb698ded1575903ca1cb90f9a4`. T02: `daf7a8413f89f36dc434bfc09db44da3cbc6d1d1`. The records commit that adds this section follows T02 and changes only documents.

**Review ranges for the independent reviewer (Luna).** T01: `94edf035a2051046493268d6af61beb18989d627..3dcd13bb85ca3ddb698ded1575903ca1cb90f9a4`. T02: `3dcd13bb85ca3ddb698ded1575903ca1cb90f9a4..daf7a8413f89f36dc434bfc09db44da3cbc6d1d1`. Combined implementation: `94edf035a2051046493268d6af61beb18989d627..daf7a8413f89f36dc434bfc09db44da3cbc6d1d1` (the records commit after `daf7a8413f89f36dc434bfc09db44da3cbc6d1d1` is documents only).

**What was built.**
- T01, backend: `CHARACTER_DENY_CAPABILITY_CODES` (the `entity_id` row of the grant catalog, the only capability test the command applies once a character deny target is admitted), `list_deniable_character_capabilities`, and `deniable_character_capabilities` on `GET …/access-overview`. `grantable_resource_capabilities` and every route, lock, write and authorization rule are unchanged.
- T01, portal: an optional `deniable_character_capabilities` type field, `utils/characterDenies.ts` (words, hints, duplicate filter, the D-6 test), `CharacterDenyFields` and the **Character (deny only)** kind in the member and group forms (nothing chosen for the manager, fixed Deny effect, the confirmation, `entity_id` + `deny`, unknown-outcome and refusal copy with **Try again** and **Refresh access list**), and `failureStatus` on the two add hooks.
- T02: plain-word labels on member and group cards (D-6 classification), the removal confirmation and its copy, `failureStatus` on the revoke hook, `useAccessAuthorityRecheck` (a 403 from any of the three resource-grant write hooks reads the session in place, falling back to reload), the optional `WriteNotice` on `onChanged`, and focus return to the card's grants heading in `CampaignAccessPage` (only if the re-read displaced focus to the body).

**Acceptance coverage.**
| Cases | Where |
|---|---|
| BD1–BD5 | `tests/database/test_api_access_overview.py` (7 new tests; BD3 runs per character, npc and player character and drives the route with every listed code) |
| BD6–BD9 | `tests/database/test_character_denies_and_reveal_authority.py` (4 tests) |
| O1–O16 | `portal/src/pages/CampaignAccessPage.characterDeny.integration.test.tsx` (22), `utils/characterDenies.test.ts`, and the two add-hook `failureStatus` tests |
| R1–R18 | `portal/src/pages/CampaignAccessPage.characterDenyDisplay.integration.test.tsx` (19) and `hooks/useAccessAuthorityRecheck.test.ts` (9, three hooks) |

**Verification, with first runs and reruns kept apart.**
- Backend focused (T01 tree): the four S04 backend files plus the Phase 15 guard file, 78 passed; `ruff format --check`, `ruff check`, `mypy src` clean; `git diff --check` clean.
- **Shard run on T01 (`3dcd13bb85ca3ddb698ded1575903ca1cb90f9a4`), first and only run: PASSED**, 11335 passed, 6 skipped, 11341 collected and executed, 32m14s. No rerun was needed. T02 changes no backend file, so no second shard run was made.
- Portal on the T01 tree: 439 files, 5487 tests passed; lint and build clean.
- **Portal on the T02 tree, four full runs, recorded separately:**
  1. default concurrency: 2 failed (`App.readRecovery.test.tsx` "keeps focus on the retry button while it reads, and on repeated failure"; `EncounterPages.test.tsx` "reports a confirmed start whose re-read fails…");
  2. default concurrency: 1 failed (`ItemDefinitionPages.save.test.tsx` "shows a persistent saved status…");
  3. default concurrency: 1 failed (`App.knowledgeMemberPreview.test.tsx` "resets the character, party and page…", an 8.4 s test);
  4. `--maxWorkers=4`: 441 files, 5517 tests, all passed.
  The two files of run 1 passed together in isolation (45/45). None of the failing tests touches Access code, each failure differed, and no default-concurrency full run passed on the T02 tree. The isolated rerun and run 4 are not presented as default-concurrency passes. The timing sensitivity of the suite under concurrency is pre-existing and unproven to be unrelated beyond that evidence.
- Lint and build clean on the T02 tree; documentation check and `git diff --check` clean.

**Mutation probes (restored; SHA-256 prefixes before and after equal).** Backend: adding `character.view_full` to the deniable codes fails BD3 (`domain/access.py` `14fe03746bc58670`). T01 portal: writing `character_id` fails O7, O9 and O11; auto-selecting the first character fails O4/O5 (`AddResourceGrant.tsx` `2D45E2A47577`, `CharacterDenyFields.tsx` `78E5C17EEA4C`). T02: classifying a denial by display name alone fails R1; dropping the 403 session read fails R13 and R18; dropping the focus return fails R4 (`characterDenies.ts` `B525774CBF30`, `useRevokeResourceGrant.ts` `E01B3163F626`, `CampaignAccessPage.tsx` `BFB2C179B32F`). One probe attempt applied `git checkout` to an uncommitted file and discarded the constant; it was restored from the pre-probe copy and the hash matched.

**Hint copy against the backend (task 4).** Each sentence of the two hints rests on a test: the whole-character deny (404 on character detail, profile, revelations and release for owners and delegates, `test_character_public_profile_grant_denies.py`, BD7); the `canon.edit` deny's save refusal, GM public-profile read loss, player-profile 404 and unchanged character detail (BD6, BD9, DEF-016); release and reveal unaffected (BD6, `test_a_release_still_succeeds_for_an_owner_with_a_canon_edit_deny`); and copied player-profile text withheld from the denied person, so a draft containing it is not releasable by them (`test_player_profile_provenance_restrictions.py::test_edit_release_coverage_noop_clear_and_recopy_of_player_profile_text`: can_release false, 403 `public_profile_field_withheld`, nothing written). DEF-016 keeps its separate open disposition: nothing in S04 widens the deny.

**Deviations from the plan, with reasons.**
1. O14's session re-read and O10's focus clause are implemented and tested in T02, as the plan's §4 and §9 place them; O14 and O10 in T01 assert the message and the announcement.
2. The planned per-component test files are replaced by two page-level integration files over a shared harness (`test/characterDenyHarness.tsx`), which exercise the real forms, hooks and page; the hooks have their own tests.
3. The permission select also starts unchosen (the plan required that for the character only); a denial is never defaulted.
4. The add and revoke hooks gained `failureStatus` (additive; existing `status` shapes unchanged) so the new copy can tell 403 from 404.
5. `onChanged` takes an optional second argument; only the character-denial controls send it.
6. A group card has no member toggle, so its **Refresh access list** returns focus to the status line.
7. BD9 was added to pin the facts the hint states; the plan's draft hint wording was corrected (§10.2).

**CI failure `44951144761` investigated (not an S04 defect, not fixed here).**
- Evidence: the job log shows `CharacterPublicProfilePage.test.tsx` "Cancel still returns focus to Release" failing with focus on `h1#public-profile-heading` where the Release button was expected; the next run on a later head passed.
- Mechanism in code: `usePageArrival` focuses the page heading once, in a passive effect, when the page becomes ready, without checking where focus is. `ConfirmDialog` records `document.activeElement` as the opener when it opens, and on close keeps focus that already sits on something outside the dialog.
- Delayed-heading probe: deferring that focus by one timer tick reproduces the CI symptom exactly (expected `public-profile-release`, received `public-profile-heading`) and fails 8 tests of that file.
- Natural reproduction, which the delayed probe does not prove: an instrumented scratch copy of the test (not committed) recorded the active element when the test found the Release button, then ran 36 times (12 idle, 24 under parallel load). It passed 34 times, and in all 34 the heading already held focus at that point. It failed 2 times, both under load, with the identical symptom, and in both the active element was still the body at that point: the test focused Release and clicked before arrival focus had settled; arrival focus then took focus, the dialog recorded the heading as its opener and Cancel returned there.
- Diagnosis (provisional): the test interacts before page-arrival focus settles. That is established as the trigger. It is not established that product focus cannot override a real interaction: arrival focus does not check whether focus moved since the commit, so a person acting within the gap between the ready commit and the passive-effect flush could have focus taken, though that window is a fraction of a frame and no such case was observed. The candidate fixes (a test that waits for arrival focus to settle by observing it, or an arrival rule that yields to focus already moved by the person) are owner/S01 decisions; neither is made here and no assertion was weakened or sleep added. Recorded for the C02 checkpoint (§7.2).

**Limitations.** Independent review is pending. The persona, browser and assistive-technology checks of §7.3, human acceptance and `actor-a`/owner acceptance are not performed. No default-concurrency full portal run passed on the T02 tree (above). C02 merge readiness is not established by this record.

### 11.3a CI on the S04 head and the profile-copy expiry test (2026-11-21 to 22)

**Run `44979295720`, pull_request, head `225a4afdd5cfe34b4e963f5ae5849032fa87a9d4`.** Both attempts failed; neither is a pass.
- Attempt 1: three jobs failed. Portal tests (`ItemDefinitionPages.save.test.tsx`, "re-sends an unresolved attempt by Save or Retry with the same key, body and version"); shard 4/8 (`test_campaign_owner_caller_expiry.py::test_a_caller_who_expires_during_the_lock_wait_is_refused_and_nothing_is_written[change]`, "expected 1 session(s) waiting on a lock"); shard 6/8 (`test_player_profile_copy_races.py::test_r01_a_role_that_expires_during_the_copys_lock_wait_must_refuse_the_copy`, "expected 1 session(s) blocked by pid 515; 0 were"). The other jobs passed.
- Attempt 2 (the failed jobs re-run, no new commit): portal and shard 4/8 passed; **shard 6/8 failed again with the same test** ("blocked by pid 811; 0 were"). Every other job passed.
- The earlier green backend shards of `fe88842` and `98b0238` do not cover this head. Adding a test file in S04-T01 changed the round-robin file-to-shard assignment (tests/conftest.py deals files in sorted order), so this test ran with different neighbours on shard 6.

**Local evidence, kept separate.** A first local run of shard 6/8 used `-x` and stopped early at the known local-environment failure `tests/unit/test_config.py::test_local_session_allowed_origins_defaults_to_dev_topology_outside_production` (it also fails with the changes stashed), so it never reached the test and says nothing about it. The old test passed in isolation locally (call phase about 3.1 s, equal to its own expiry window). **The CI failure was not reproduced locally with the old test**; the cause below is therefore a diagnosis from the code, consistent with the log, not an observed reproduction.

**Diagnosis (provisional).** The test armed a 3 s role expiry (`UPDATE … expires_at = now() + interval '3 seconds'`) and only then started a thread whose `copy_pp` built and started the whole app (`create_app()` and `TestClient`) before sending the request. If that start-up plus the request's path to the entity lock takes longer than 3 s, the role has lapsed before the request is judged; it is refused early, never waits, and `wait_until_pid_blocks` reports "0 were". The expiry cannot instead be armed after the request blocks: the copy takes the caller's role rows `FOR SHARE` (`commands/_content.py`, `lock_authoring_scope`) before it waits, so an UPDATE of `expires_at` would itself wait behind that lock. A wall-clock deadline is therefore intrinsic; what can be removed is everything that is not the request's own work.

**Correction (test only, `0b349cb015d45bb25e807705d57f7c207e550a98`).** The client is built and entered, and the route warmed with a read, before the expiry is armed (using `clock_timestamp()`); the copying thread reuses that client through an adapter. A missed window now fails with an explicit message that no authorization result was observed. No retry, no longer timeout, no weakened assertion; R01 expiry semantics (the transaction-start rule, the post-wait re-judgement) and production code are unchanged. The residual dependency is the request's own latency to the lock (milliseconds) against 3 s.

**Verification.** The corrected test passed 3 of 3 in isolation. With the `AuthorizationPlan.finalize` judgement loop disabled it fails with `201` and "the copy committed after the role expired" (`domain/authorization.py` SHA-256 prefix `43be8ebb7c760318` before and after restoring). A first probe at the copy command's requirement calls did not fail the test (the final check is in `finalize`) and was discarded. CI-assigned shard 6/8, run locally once without `-x`: 1444 passed, 1 failed, 11m10s; the one failure is the `test_config.py` local-environment test above. Not shown: that the old test fails under CI-like latency here, and that attempt 2's `shard 4/8` and portal failures were flakes beyond their passing on re-run. `test_character_public_profile_concurrency.py`, `test_character_reveal_delegation.py` and `test_campaign_owner_expired_recipient.py` use the same arm-then-start pattern with 3 to 4 s windows; they were not changed (out of scope).


### 11.4 Independent implementation review of T01, T02, combined S04, and expiry-test correction (Luna, 2026-11-21)

**Exact reviewed history.** Planning baseline/T01 base `94edf035a2051046493268d6af61beb18989d627`; T01 `3dcd13bb85ca3ddb698ded1575903ca1cb90f9a4`; T02 `daf7a8413f89f36dc434bfc09db44da3cbc6d1d1`; integration/records head `499e90f24ff7f28933014e89643031a93ac47b74`. The separate expiry-test correction is `225a4afdd5cfe34b4e963f5ae5849032fa87a9d4..0b349cb015d45bb25e807705d57f7c207e550a98`. The integration head contains the full S04 sequence and test correction; no production changes followed T02 within the reviewed integration range. Initial branch/HEAD was `phase15/completion` at the exact integration head, with a clean worktree. No applicable `AGENTS.md` was present.

**Verdicts.** **T01: CHANGES REQUIRED. T02: PASS WITH VERIFICATION LIMITS. Combined S04: CHANGES REQUIRED. Expiry-test correction: PASS WITH VERIFICATION LIMITS (test-only).** One low-severity T01 acceptance defect remains; it does not imply an authorization bypass or a backend policy failure. T02 was reviewed on its exact range and together with T01; no separate T02 defect was found. The S04 review does not close C02 or any persona, browser/AT, human or owner acceptance obligation.

**Finding S04-R1 — definitive character-deny 404 leaves the submit action enabled (application, score 3/10 Low; blocks the explicit O13 acceptance).** In `portal/src/components/AddResourceGrant.tsx` (the submit-button logic around lines 214–219 and 375–382) and `portal/src/components/AddGroupResourceGrant.tsx` (around lines 194–199 and 353–360), `canSubmit` remains true after a character-deny 404. The label becomes “Add,” and the submit button is disabled only for pending or invalid form state. `CharacterDenyFeedback` separately offers **Refresh access list**, but does not disable the same form. A manager can submit the same confirmed, possibly stale member/group and character again before choosing refresh. The backend still applies its existing authority and target checks and can refuse the command; review found no authorization expansion or proven write from a target that remains unavailable. The defect is the promised refusal recovery: O13 says no retry is offered, but the live editor allows another POST, including if the target becomes available again before the user refreshes.

Rubric: supported-path exposure 1 (a manager reaches this only after the constrained 404 flow); impact 1 (a misleadingly available second write and avoidable refusal, with no demonstrated unauthorized write); triggerability 1 (one ordinary click after that special response); detection/recovery 0 (the 404 and refresh are visible); blast radius 0 (one form/attempt). **Correction:** disable submit for the definitive 404 state until the user refreshes or cancels/reopens; preserve the explicit read recovery. Strengthen member and group integration assertions to require the action disabled and prove a second submit sends no POST. Keep ambiguous network/500 same-key retry behavior unchanged. This is Low severity but blocks the scoped O13 contract; no owner risk acceptance is recorded.

**Acceptance review.** T01's server-derived `deniable_character_capabilities` matches the existing entity-deny catalog and command rule, with allow options/catalog and authorization unchanged. Character selection is explicit, limited to current `assignable_characters`, and the request uses `entity_id` plus fixed `deny`; no submitted display text or new authority is introduced. T02's labels and hints match inspected profile, player-profile, release and revelation behavior. DEF-016 remains separate and open. Revocation refreshes the overview and open explanation; source-specific reconciliation preserves overlapping grants/delegations. Existing `access.manage` gates, 403 session recheck, authority-loss cleanup, attempt ownership, route behavior and S01–S03 reviewed behavior remain intact in inspected paths. The seven documented deviations in §11.3 are bounded and do not weaken authorization. S04 mutation-probe records remain intact. The only missed O13 behavior is S04-R1; the test at `CampaignAccessPage.characterDeny.integration.test.tsx` around lines 295–303 checks 404 copy, the read button and absence of a button *named* “Try again,” but never asserts that “Add” is disabled or that a repeat sends nothing.

**Expiry-test correction review (separate A5c test-tooling track).** The change only updates `tests/database/test_player_profile_copy_races.py`. It moves client/app setup and route warmup ahead of arming the expiry, then reuses that client while the request waits on the intended entity lock. It still waits for observed blocking, sleeps through the role expiry while the lock is held, releases the lock, and asserts refusal with no draft/write side effect. This removes unrelated setup time from the deadline race without changing the three-second wait, transaction-start semantics, or production authorization. The before-fix shard logs and the distinction between the two repeated shard-6 failures and the earlier local isolated pass are preserved in §11.3a; a green later run is not used as the sole validation. I independently ran the corrected test once: **1 passed**. The recorded mutation probe disabling `AuthorizationPlan.finalize` causes an unauthorized commit and test failure; the production source hash was restored exactly. Thus the correction is credible, while reproducing the old failure under local CI-like latency remains unverified. The unrelated shard-4/portal failures and the historical run results remain distinct, not retrospectively classified as flakes.

**Independent verification.** From PowerShell, the focused portal selection covering both S04 page integrations, existing access/effective-access behavior, add/revoke hooks, S01 public-profile/revelation behavior, S02/S03 revelation behavior and shared mutation behavior passed: **16 files, 377 tests**. `npm run lint` and `npm run build` passed (Vite reports the existing large-chunk advisory). Focused backend authorization/overview/profile-deny/target-column checks: **63 passed**. Backend formatting, Ruff, and mypy checks passed. The expiry correction test passed separately as above. No full local suite was rerun: the recorded T02 default-concurrency failures and reduced-concurrency pass remain separate historical events, and no redundant full shard was needed for this frontend finding/test-only correction.

**CI.** Run `44985253144` completed successfully for exact PR head `499e90f24ff7f28933014e89643031a93ac47b74`; portal tests/lint/build, all eight PostgreSQL shards, migrations and Foundry checks passed. Checkout logs identify synthetic PR merge checkout `ddfc75415ad7d4b17058b84af3b4dd9dc86ec9cb`, merging the PR head into base `bf23c7648601eb1b3ad479078f2762fe13fd460b`. This establishes CI on the exact PR head plus its synthetic base merge, not an actual PR merge and not closure of S04-R1.

**Earlier Cancel-focus failure.** The investigation in §11.3 is preserved as provisional. Its test trigger—interacting while active focus is still `body`, before the page-arrival passive focus has settled—was observed in the two natural failures and explains the CI symptom. That does not establish that a person cannot have focus stolen in the narrow interval, nor establish a product failure in supported browser use. The delayed-focus mutation is not natural-user evidence. S04 does not change the relevant S01 focus path. Keep this inherited concern separate; do not call the earlier failure conclusively test-only or a demonstrated product defect.

**Remaining actions.** Correct S04-R1 and re-review the bounded correction. T01 and combined S04 are not review passes yet; T02 is reviewed with limits. S04 persona, browser/AT, human and owner checks remain pending, as do the separately governed final C02 integration and merge-readiness decisions. S04 does not resolve DEF-016. The separate expiry-test correction is reviewed; A5c's existing independent implementation-review status is unchanged. Documentation and register edits for this review are intentionally uncommitted.

### 11.5 S04-R1 correction (2026-11-22): corrected, pending independent confirmation

**Baseline** `499e90f24ff7f28933014e89643031a93ac47b74`; **code commit** `cc8f0692f4451d69712384290d3c7e159e928bb2` (portal only: `AddResourceGrant.tsx`, `AddGroupResourceGrant.tsx`, the O13 integration test). The §11.4 review text and its verdicts are unchanged; T02's PASS WITH VERIFICATION LIMITS and the expiry-test correction's pass are not reopened. DEF-016 and the provisional Cancel-focus investigation (§11.3) are untouched.

**Change.** In both forms, a character deny whose last outcome was a definitive 404 (`status` denied with `failureStatus` 404) is an *refused attempt*: `canSubmit` is false, so the Add button is disabled **and** the form's submit handler returns before `onMutationStart` or `submit`. Hiding a button alone would not stop Enter in a field or a programmatic submit; the guard is in the handler. Changing the character or permission does not unlock it. What clears it: Cancel (which resets the hook) and reopening, which starts the normal empty selection; or **Refresh access list**, whose list re-read unmounts every card (`AccessOverviewBoundary`), so the form comes back closed with nothing carried. A failed re-read shows "Access information unavailable" and no form, so a failed refresh cannot unlock submission. The 403 recheck, the 409 refresh offer, the ambiguous (network/5xx) "Try again" with the same body and Idempotency-Key, per-body key reuse, and generic (non-character-deny) forms are unchanged. No backend, API or hook change.

**Tests** (`CampaignAccessPage.characterDeny.integration.test.tsx`, 22 to 32): the two O13 tests now also assert Add is disabled; new, for a member and a group each: Add disabled and a click, a form submit, and a submit after changing the selections send no second POST; a successful refresh gives a fresh form whose new attempt posts with a new key; a failed refresh leaves no form and sends nothing; Cancel then reopen discards the refusal and follows empty-selection rules; a 500 still retries with the same key and body.

**Before the correction.** Run against the unmodified components, 6 of the 32 tests failed (the two strengthened O13 tests, and the member and group variants of the disabled/no-second-POST and the successful-refresh tests, which assert the disabled state first); the failed-refresh, Cancel/reopen and 500-retry tests passed, as they guard behavior that was already correct. After the correction 32 of 32 pass.

**Verification** (PowerShell, local): the affected form/hook/S04 selection (`CampaignAccessPage*`, add/revoke resource-grant components and hooks, `useAccess*`, `characterDenies`): 18 files, 165 tests passed; `eslint` on the changed files and `tsc -b` clean; `npm run build` succeeded (the existing chunk-size warning only); `git diff --check` clean. No backend shard run (frontend-only; no concrete backend concern). A full portal run was not repeated for this change. **CI:** see the work register for the run on the final head.

**Re-review range:** `499e90f24ff7f28933014e89643031a93ac47b74..cc8f0692f4451d69712384290d3c7e159e928bb2` (code); records commit follows. Status: **S04-R1 corrected, pending independent confirmation.** T01 and combined S04 are not review passes until that confirmation. Persona, browser/AT, human and owner checks remain pending.

### 11.6 Independent confirmation of S04-R1 (Luna, 2026-11-22)

**Exact range and checkout.** Baseline `499e90f24ff7f28933014e89643031a93ac47b74`; code `cc8f0692f4451d69712384290d3c7e159e928bb2`; final records/head `7f965c313d1c5a09e298b643e36c084783b04850`. The correction is limited to both grant form components and their page integration test. The subsequent record changes are documentation only; the head is on `phase15/completion`, and the initial worktree was clean. No applicable `AGENTS.md` was found. **S04-R1: CLOSED. T01: PASS WITH VERIFICATION LIMITS. Combined S04: PASS WITH VERIFICATION LIMITS.** T02 retains its §11.4 verdict; the separate profile-copy expiry-test correction remains PASS WITH VERIFICATION LIMITS. DEF-016 and the provisional Cancel-focus investigation remain separate.

**Correction review.** In each form, `attemptRefused` is true only for the character-deny form after `status.kind === "denied"` and `failureStatus === 404`. It feeds `canSubmit`, and the form submit handler returns before `onMutationStart` or the hook if `canSubmit` is false. Thus neither a click on disabled Add, Enter/form submission, nor changing character/permission can resend that refused attempt. The forms remain editable enough to inspect/change their fields, but the refusal cannot be cleared by those edits. The Refresh access list action starts the authoritative overview read; `AccessOverviewBoundary` replaces and unmounts the cards while loading. On success the editor is closed with empty selections and a deliberate new attempt obtains a fresh key. On failed read the unavailable boundary renders no editor. Cancel resets the refusal and closes the form; reopening follows the existing unselected-character/permission and confirmation rules. The prior refused values are not restored to the new form.

The new page-level cases exercise both member and group variants: disabled Add, click plus direct form submit, selection changes followed by another form submit, successful and failed refreshes, and Cancel/reopen. Successful re-read tests assert the deliberate new attempt has a different key. The Cancel/reopen case verifies fields and refusal copy are reset and requires fresh user selection/confirmation. The add hooks retain their existing per-payload key reservation behavior; this correction does not change it. A deliberate same-payload submission after Cancel may reuse that payload's reservation, but the old selection is not restored and no retry control or automatic resend remains. The 500 tests still prove a same-body/same-key retry; the earlier network-error test still covers ambiguous network failure. This distinction matches the intended refusal versus unknown-outcome paths.

**Before-fix evidence.** The recorded pre-correction run against the unchanged components failed 6 of the 32 tests: both strengthened O13 assertions and the member/group disabled-submit and successful-refresh cases. Those failures first assert Add is disabled, so they demonstrate the original behavior rather than merely testing a label. The failed-refresh, Cancel/reopen and 500 retry cases passed before the change and remain regression coverage. After correction the implementer recorded 32/32; independent focused verification below reproduced the final integration/hook set.

**Lifecycle/regression assessment.** Production changes are limited to the two `canSubmit` expressions and explanatory comments; no hook, route, authority, navigation, or response lifecycle changed. Because the attempt lock applies only when the pseudo-kind is character deny and the definitive status is 404, ordinary allows, 403 authority recheck, 409 refresh recovery, and ambiguous network/5xx same-key retries retain their existing paths. Existing S04 authority-loss, campaign navigation, abort/late-response, allow-grant, and S01–S03 integration tests passed in the focused run. No new late-response path was introduced.

**Independent verification.** Using PowerShell from `portal/`, the focused set of S04 page integrations, access-group/member and role regressions, access overview/session hooks, resource-grant hooks, and character-deny utility tests passed: **18 files, 165 tests**. The correction's recorded before-fix evidence and §11.5 test results were inspected. No backend shard or full portal suite was repeated: the change is frontend-only, and no backend concern arose. The separate expiry-test correction and S04 T02 were not changed or reopened.

**CI.** Run `45001046629` completed successfully for exact PR head `7f965c313d1c5a09e298b643e36c084783b04850`. Completed workflow checkout logs show each relevant job fetched and checked out the full synthetic merge SHA `1d8e3d956b9333184fba835263c7b5ec0f34076d`, merging that head into base `bf23c7648601eb1b3ad479078f2762fe13fd460b`. This is evidence for the exact head and its synthetic merge checkout, not an actual PR merge. The current merge ref alone was not used to infer the tested SHA.

**Remaining limits.** Persona, browser/AT, human and owner acceptance remain pending; these are not established by jsdom tests or CI. The earlier S01 Cancel-focus failure remains provisional as recorded in §11.3. C02 merge readiness remains a separate checkpoint judgment. No production corrections were made; this confirmation and register update are documentation-only and uncommitted.
