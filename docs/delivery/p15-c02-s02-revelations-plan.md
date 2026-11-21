# D/P15-C02-S02 implementation plan: list, create and revoke revelations

**Status:** Opus plan prepared 2026-11-20. Owner decisions recorded 2026-11-21 (§10.1): **OD-1 = option A** (read-only `can_reveal` on the revelations list) and **OD-2 = retain C02's S01 to S04 checkpoint scope** (PR #71 stays draft; no split). T01 and T02 are ready for Sonnet. Work-register row: [D/P15-C02-S02](work-register.md#p15-c02-s02), tasks [T01](work-register.md#p15-c02-s02-t01) and [T02](work-register.md#p15-c02-s02-t02). Parent checkpoint: [D/P15-C02](work-register.md#p15-c02).

**Baseline.** This plan was read at `97f75b6ff22d9447e26c34ffadfd8f31b195ad93` ("docs: record P15-C02-S01 F1-R1 independent confirmation; S01 passes with verification limits").
- That commit is the head of `phase15/completion` and equals `origin/phase15/completion`. The worktree was clean, and no repository-path `AGENTS.md` exists.
- That head is also the head of **PR #71**: open, draft, base `main`, titled "CI evidence only". Its CI run `44835164789` (`pull_request`) passed on `97f75b6`, verified with `gh pr checks 71` and `gh run list`.
- This plan does not change PR #71.
- S01's review records are preserved unchanged ([S01 plan §11.4 to §11.8](p15-c02-s01-draft-release-plan.md#118-f1-r1-independent-confirmation)). That includes the historical local full-suite failures: §11.5 (5350/5351, `App.knowledgeClaim.test.tsx` timeout) and §11.7 (5351/5352, `terminalStates.test.tsx`). Their isolated reruns do not establish a full-suite pass.

**How each statement was established.** By reading source, documents and git/GitHub metadata at the baseline. No application, test or probe was run. No application, test, schema or backend file changed.

**Contract sources.**
- [ACCESS_CONTROL §3w](../api/ACCESS_CONTROL.md#3w-character-revelations-p03-a-a3a): revelations.
- [ACCESS_CONTROL §3v](../api/ACCESS_CONTROL.md#3v-character-public-profile-p03-a-a2a): the D8 read rule and reveal authority.
- `src/dnd_ai/api/character_revelations.py`, `commands/character_revelations.py`, `queries/character_revelations.py`, and migration `145_character_revelations`.
- The [A3 design](shared-characters.md#10-a3-design-audience-revelations-2026-11-07).
- The [S01 plan](p15-c02-s01-draft-release-plan.md) and its page.
- The register's [execution stages and review gates](work-register.md#execution-stages-and-review-gates), and the [grading rubric](grading.md).

---

## 1. Selection and readiness

### 1.1 S02 to S04 prerequisites

| Slice | Maintained prerequisite | Backend contract present | Eligible |
|---|---|---|---|
| S02 List, create and revoke revelations | "Checkpoint entry criteria; no additional slice-specific gate" | Yes (§3w; three routes) | Yes |
| S03 Manage reveal-authority delegations | Same | Yes (owner-only delegation routes, A1) | Yes |
| S04 Manage approved character-scoped denies | Same | Yes (`POST /resource-grants` with `entity_id` deny, A2a-R) | Yes |

The checkpoint entry criteria are `a4` merged and `r01` owner accepted. They were confirmed in [S01 plan §1](p15-c02-s01-draft-release-plan.md#1-entry-readiness). The only change since is S01 itself, which is reviewed. No slice names another as a prerequisite, and `a5c`, `copy-ui` and `preview` are not prerequisites of any of them.

S02's criterion "loss of delegation" can be tested without S03's UI: tests mock the API's refusal, and delegations exist through the API.

### 1.2 Why S02

The documented dependencies make S02, S03 and S04 equally eligible. The register's tie-break governs: "For equally eligible work, the adopted sequence places the active handoff first, then groups independent work by workflow in the published order. That tie-break is scheduling discretion" ([execution stages](work-register.md#execution-stages-and-review-gates)).

The active handoff is S01's Public profile page, and S02 continues that same workflow:
- a revelation needs a release (`409 public_profile_not_released`), which S01's reviewed page now produces;
- the list has the same D8 audience as that page;
- S01's release confirmation already tells the GM that "players see it only after you reveal the character".

S03 and S04 remain eligible and can be planned in parallel.

**Verdict.** S02 is eligible. T01 can start now. T02 can be fully implemented only after OD-1 is answered. Its other cases do not depend on OD-1 and are specified below.

### 1.3 Does C02 merge only with S01 to S04 together?

**Yes, as maintained.** These requirements govern:

1. **Register, [execution stages and review gates](work-register.md#execution-stages-and-review-gates):** "number schedulable checkpoint PRs within their release, slices within each PR and commits within each slice". Also: "In each table the PR row supplies purpose, inherited entry criteria and merge/operational gates. A slice row adds its own entry criteria, task commits and acceptance case." And: "Merge requires all included slice reviews, the PR acceptance cases and CI on the integration head." The introduction repeats the last rule: "A checkpoint PR is ready to merge only after all included slices are independently reviewed, PR acceptance cases pass, and CI passes on the integration head."
2. **The slices C02 includes are its child rows,** S01 to S04 (register rows 1.2.1 to 1.2.4.2; the [hierarchy review](hierarchy-review-2026-11-19.md) adopted them as the children of the C02 implementation PR, with the former S02 split into S02, S03 and S04).
3. **Consumers name C02 as a whole.** [actor-a](work-register.md#actor-a) and [p15-integration](work-register.md#p15-integration) require "P15-C02 merged".

So "all included slices" means S01 to S04. C02's rows contain no staged-merge provision. Compare P15-C20's criteria, which state their own: "The PR can start with G1 while G2/G3 work proceeds. Merge after all included slices pass." A smaller PR, for example S01 alone, is not provided for. It is not a merge exception that this plan can grant.

**The only maintained route to a smaller checkpoint is re-sizing.** The register says: "If a condition is resolved later, insert its newly sized PRs before the work or release gate that consumes them and revise the current register and crosswalk before work begins." Splitting C02 into two checkpoint PRs would therefore be a register and crosswalk revision decided by the owner, with new IDs and the consumers updated. It is recorded as optional owner decision **OD-2** (§10).

PR #71 stays a draft CI-evidence PR. Its passing CI is checkpoint-head evidence for that head only. A later head, including documentation commits, needs its own run before any merge.

---

## 2. Verified current behavior

### 2.1 Backend (complete; S02 changes none of it unless OD-1 chooses option A)

The routes are under `/campaigns/{campaign_id}/characters/{character_id}/revelations`.

| Route | Gate | Body | Result |
|---|---|---|---|
| `GET` | `campaign.view`, then the D8 read rule (effective character-scoped `canon.edit` or reveal authority; no whole-character deny); else 404 | — | `{character_id, revelations: [...]}`, newest first |
| `POST` | `campaign.view`, then reveal authority and no whole-character deny, in a dependency before the body. The command locks, re-judges at a fresh instant, then reserves or replays the idempotency key | `{audience_kind, target_campaign_membership_id?, target_access_group_id?, reason}`. `audience_kind` is one of `member`, `access_group`, `campaign_current`, `campaign_current_and_future`. The target must match the kind; `reason` is 1–1000 characters; extra fields are 422 | `201 {character_revelation_id, created: true}`, or `200 created: false` for a natural retry |
| `POST …/{id}/revoke` | As create | `{reason}` (1–1000 characters) | `200 {character_revelation_id, revoked}`; `revoked: false` when the revelation was already closed |

**List entry.** Each entry contains:
- `character_revelation_id`, `audience_kind`;
- `target_campaign_membership_id`, `target_member_name`, `target_access_group_id`, `target_access_group_name`;
- `created_by_membership_id`, `created_by_name`;
- `authority_source` (`owner` | `delegation`), `created_at`;
- `live`, `ended_at`, `end_reason`, where `end_reason` is one of `revoked`, `target_membership_ended` or `access_group_deactivated` (migration 145).

For `campaign_current` only, an entry also has `audience_size` and `snapshot_members [{campaign_membership_id, display_name, added_at, removed_at, removal_reason}]`; `removal_reason` is `membership_ended`. The reason text is **never** returned, whether in the list, a receipt or audit.

**Refusals.**

| Status | Code | When |
|---|---|---|
| 403 | `character_reveal_required` | No reveal authority. Says nothing about the character |
| 404 | (none) | Whole-character deny, a character outside the world or not canon, a target outside the campaign, or a revelation id of another character or that does not exist. These are deliberately indistinguishable |
| 409 | `public_profile_not_released` | Create with no release |
| 409 | `public_profile_character_not_active` | Create for an archived character |
| 409 | `revelation_target_not_active` | Ended membership or deactivated group |
| 409 | `campaign_archived` | Archived campaign |
| 409 | (non-disclosing) | A key reused for another payload, character or route |
| 422 | (validation) | Shape |

A caller who lost authority is refused rather than handed a stored receipt.

**Effect.** A live revelation confers only `character.discover` and `character.view_public_profile` on its audience. Revoking one leaves every other source intact. Players learn of a change on their next request.

### 2.2 Reveal authority and targets: what the client can learn

- **Reveal authority** belongs to a live built-in owner, or to a delegation bound to a live built-in `gm` assignment (§3v; `domain/reveal_authority.py`).
- **No response tells a list reader whether they hold reveal authority** in a form that fits revelations:
  - The revelations list has no `can_*` flag.
  - The public-profile read's `can_release` (S01) means reveal authority **and** an active character **and** no withheld draft field **and** a readable identity preview when one is needed. It is therefore false for some callers who may create or revoke revelations, for example when a draft field is withheld from them.
  - Revoke has no active-character check, so `can_release` is false for an archived character even though revoke is allowed.
  - This is gap **G-1**.
- **Member and access-group targets** are listed only by `GET /campaigns/{id}/access-overview` (`members[].campaign_membership_id`, `display_name`, `status_code`; `access_groups[].access_group_id`, `name`, `status_code`), which needs `access.manage`.
  - Migration 086 seeds the built-in `gm` role with `campaign.view`, `canon.edit`, `character.view_full` and `character.view_knowledge`, and never `access.manage`.
  - The campaign owner holds `access.manage` (migration 080).
  - So a **delegated GM without `access.manage` cannot be offered member or group targets** from any existing read. Campaign-wide audiences need no target. This is gap **G-2**.

### 2.3 Portal at the baseline

- **No portal code calls `…/revelations`** (`grep` in `portal/src`).
- **S01's page** (`pages/CharacterPublicProfilePage.tsx`, 919 lines) is the D8-audience page at `characters/:characterId/public-profile`.
  - It is built from `useAuthoringResource` and `useKept`.
  - Its mutations use `useAuthoringMutation` (scope keys `public-profile-save:` and `public-profile-release:`), with per-scope keys and retry.
  - Refusals are handled by `RefusalNotice` and the `PermissionLost` / `retainedChanges` contract.
  - It renders `LatestRelease` and `ReleaseHistory`, plus a focus handoff that F2 corrected.
- **C01's Access page** (`pages/CampaignAccessPage.tsx`, `hooks/useAccessOverview.ts`) reads the overview and renders each member's read-only **Revealed characters**. Nothing in S02 changes it.
- **The "next request" revocation contract holds:** nothing polls or pushes.

---

## 3. Outcome, scope and exclusions

### 3.1 User outcome

On a character's **Public profile** page, a new **Revelations** section serves anyone who may read the page:
- live revelations: who can see the profile, through which audience, revealed by whom and when, and under which authority;
- ended revelations, with when and why they ended.

A GM with reveal authority can also:
- reveal the released profile to one member, one access group, the campaign's current members, or current and future members, with a required private reason;
- revoke a live revelation, with a reason.

An editor without reveal authority can read the list but is offered no create or revoke action. Each refusal is explained without disclosing anything. Players see nothing new on this page. Their access changes on their next request, as before.

### 3.2 In scope

- **T01: list.**
  - Types and API for the GET.
  - `CharacterRevelationsSection`, mounted on the S01 page only while the page's own read is ready.
  - Live and ended groups; audience labels; for `campaign_current`, the audience size and the snapshot members with their removal labels; end-reason labels; authority-source labels.
  - A 404 drops the content, then the page re-reads. Read failure is handled with retry.
  - No mutation controls.
- **T02: create and revoke.**
  - Types and API for both POSTs, the create form (audience kind, target, reason) and the revoke confirmation (reason).
  - Idempotent feedback: `created: false` and `revoked: false`. Refusals and the authority-loss, foreign-target and multiple-source tests.
  - The OD-1 offer rule and the G-2 target rule.
- **Docs:** [portal-behavior §5.5](../reference/portal-behavior.md#55-character-workspace) (one paragraph) and a §3w "Portal:" sentence.

### 3.3 Exclusions

- **Other work, not started here:**
  - Delegation management (S03) and denies (S04).
  - `copy-ui`, `preview`, player-profile work, and any change to S01's draft or release behavior or records.
  - Any change to C01's Access page, overview hook or effective-access panel.
- **Constraints on this slice:**
  - No backend, migration, route-manifest or Foundry change, except the single OD-1 option A addition if the owner chooses it.
  - No client-side authorization. The portal never decides reveal authority from roles, ownership or delegation records, and never computes a member's effective access.
  - No new member or group lookup route; G-2 has its own disposition.
  - No polling, push or timers.
  - The reason text is never rendered after submission, because the server never returns it. Only the person's own unsent typing may be shown back.

---

## 4. Affected files and interfaces

| File | T01 | T02 |
|---|---|---|
| `portal/src/types/characterRevelations.ts` (new) | List types: exactly the §2.1 keys | Request bodies and receipts |
| `portal/src/api/characterRevelations.ts` (new) | `revelationsPath` | `createCharacterRevelation`, `revokeCharacterRevelation`, with `MutationContext` like `api/characterPublicProfile.ts` |
| `portal/src/components/characters/CharacterRevelationsSection.tsx` (new) | List rendering, its own `useAuthoringResource` and `useKept` | Create form, revoke dialog, mutations |
| `portal/src/components/characters/CharacterRevelationsSection.test.tsx` (new) | V1–V10 | V11–V30 |
| `portal/src/pages/CharacterPublicProfilePage.tsx` | Mount the section inside `Loaded` after `ReleaseHistory`, passing `campaignId`, `characterId`, the page's `refetch`, and (T02) the offer input chosen by OD-1. No other change | — |
| `portal/src/pages/CharacterPublicProfilePage.test.tsx` | One integration case: when the page read becomes 404, the section's content is gone (V9) | — |
| `src/dnd_ai/queries/character_revelations.py`, `tests/database/test_character_revelations.py` (B1–B3 added there), ACCESS_CONTROL §3w | — | **OD-1 = A (approved).** One read-only `can_reveal` boolean on the list response (§10.1) |

S01's existing behavior and tests must not change. The page edit is additive, and S01's 58 page tests must still pass unchanged.

---

## 5. Task commits

| Commit | Message | Cases |
|---|---|---|
| T01 | `P15-C02-S02-T01: list live and ended revelations under the D8 read rule` | V1–V10 |
| T02 | `P15-C02-S02-T02: create and revoke revelations under current reveal authority with idempotent feedback` | V11–V30 (plus B1–B3 if OD-1 = A) |

Each commit passes §7 on its own and ends with the attribution lines. If OD-1 = A, the backend boolean is the first part of T02, in the same commit, so that no head exposes a flag that no client reads or a control with nothing behind it.

---

## 6. Acceptance cases

Portal cases use jsdom with a mocked fetch, as the S01 tests do. "Sent" means the fetch log.

### 6.1 T01: list (V1–V10)

| # | Case | Expected |
|---|---|---|
| V1 | The page read is ready | The section sends exactly one `GET …/revelations` after the page read succeeds. It sends none while the page is loading, denied or unavailable |
| V2 | Empty list | "This character hasn't been revealed to anyone." |
| V3 | Live and ended entries | Two groups, **Visible to** and **Ended**, each newest first. Each row shows the audience label, the creator name, the date and the source ("Owner" or "Delegated GM"). Ended rows also show the end date and the end-reason label ("Revoked", "Membership ended", "Group deactivated") |
| V4 | Audience labels | `member` shows the target member name. `access_group` shows "Group: {name}". `campaign_current` shows "Campaign members at the time ({audience_size})" with a disclosure listing `snapshot_members`; a removed member is marked "Left the campaign". `campaign_current_and_future` shows "All campaign members, including future ones" |
| V5 | Ids | No id or reason is rendered. The keys are only used for React keys and requests |
| V6 | GET 404 | The section drops all content and asks the page to re-read. If the page read is also 404, S01's unavailable state replaces everything (see V9) |
| V7 | GET network error or 5xx | `StaleReadNotice` with Retry. If an earlier list was kept, it stays and is marked out of date. The page's draft and release areas are unaffected |
| V8 | Scope change | Moving to another character or campaign discards a late list response. No row from character A appears under character B |
| V9 | Integration on the page | The page read changes to 404. Neither the section nor any of its names remains in the DOM |
| V10 | Other surfaces | No `…/revelations` request on the character sheet, the public tier, the summary tier or the Access page |

### 6.2 T02: create and revoke (V11–V30)

The **offer rule** decides when controls appear. Under OD-1 = A, they appear when the list read returns `can_reveal: true`. Under OD-1 = B, they appear when the page's `can_release` is true. Either way it is a server value, and never a client decision.

| # | Case | Expected |
|---|---|---|
| V11 | Offer rule true | A **Reveal** button and, on each live row, **Revoke**. Ended rows have no action |
| V12 | Offer rule false (an editor without reveal authority) | List only, and no reveal or revoke control. There is no inferred reason, but one neutral line: "You can't reveal or revoke this character." |
| V13 | No release (`latest_release` null on the page read) | Reveal is not offered. Text: "Release the profile before revealing it." Revoke on existing rows follows V11 |
| V14 | The form, campaign-wide kinds | Radio choices, with no target field. The reason is required (1–1000 characters, counted, with an error summary) |
| V15 | The form, member and group kinds (G-2) | Offered only when the session holds `access.manage` (`useCampaignCapability`). Targets come from the existing access-overview read: members with status `active`, and groups with status `active`, by display name. Without `access.manage` these two kinds are absent, with: "To reveal to one member or group, ask someone who manages campaign access." |
| V16 | Create 201 | The list re-reads, then announces "Revealed to {audience}." The reason field clears. Focus moves to the new row's heading or the Reveal button (S01 focus-handoff pattern) |
| V17 | Create 200 `created: false` | Re-read, then announce "That audience can already see this profile." Not an error |
| V18 | Create 403 `character_reveal_required` (lost delegation or owner role) | Message: "You no longer have authority to reveal this character." The section and page re-read, controls follow the new server values, and the typed reason is shown back read-only |
| V19 | Create 404 (foreign target, or a character now hidden) | The list re-reads. If it succeeds, show "That audience is no longer available," refresh the overview options, and keep the reason. If the list read is also 404, drop everything, as in V6 |
| V20 | Create 409 `revelation_target_not_active` | "That member or group is no longer active." Refresh the overview options and re-read |
| V21 | Create 409 `public_profile_not_released`, `public_profile_character_not_active` or `campaign_archived` | A specific neutral message for each, then re-read the page and the section |
| V22 | Create 422 | The error summary. Nothing else changes |
| V23 | Network or 5xx | `retry` re-sends the same body under the same key. An edited body is a new key. A confirmed write whose re-read fails shows the stale notice and is never re-sent |
| V24 | Revoke confirm dialog | Names the audience. Requires a reason. Cancel sends nothing and returns focus to the row's Revoke |
| V25 | Revoke 200 `revoked: true` | Re-read; the row moves to **Ended** with "Revoked". Announce "Revocation saved." |
| V26 | Revoke 200 `revoked: false` | Re-read, then announce "That revelation had already ended." |
| V27 | Revoke 403 or 404 | As in V18 and V19. A 404 for a revelation of another character is handled by the same re-read rule |
| V28 | Revoke one of multiple sources | Two live revelations reach the same member, through `member` and `campaign_current`. Revoking one leaves the other live in the re-read list. The portal makes no claim about the member's resulting access |
| V29 | No other requests | Create and revoke send no request to `/access-overview` beyond the V15/V20 option refresh, and none to `/effective-access`, the character detail or the bootstrap |
| V30 | Superseded responses | A pending create or revoke, then a move to another character, discards the response: no announcement and no row under the other character (scope keys `revelation-create:{campaign}:{character}` and `revelation-revoke:{campaign}:{character}:{id}`) |

### 6.3 Backend cases (only if OD-1 = A; database tests)

| # | Case | Expected |
|---|---|---|
| B1 | Owner, and delegated GM | `can_reveal: true` |
| B2 | An editor with effective `canon.edit` and no reveal authority; a delegated GM after the delegation or the `gm` role ends | `can_reveal: false` |
| B3 | A whole-character deny | Still 404, with no flag. An archived character keeps `can_reveal` reflecting authority only, because revoke is allowed. The create form's V13/V21 handling covers create |

---

## 7. Verification

### 7.1 Automated checks (per commit, by Sonnet; again by Luna)

- **From `portal/` in PowerShell:** `npm test` (with counts), `npm run lint` and `npm run build`. Also run `npx vitest run src/components/characters/CharacterRevelationsSection.test.tsx src/pages/CharacterPublicProfilePage.test.tsx` and report its counts separately. S01's 58 page tests must remain.
- **From the repository root:** `uv run python scripts/check_documentation.py` and `git diff --check`.
- **If OD-1 = A:**
  - `uv run pytest tests/database/test_character_revelations.py tests/database/test_character_revelations_keyed.py tests/database/test_character_revelations_http_matrix.py`;
  - `ruff format --check`, `ruff check` and `mypy src`;
  - the shard runner `uv run python scripts/run_sharded_tests.py`, because a backend response changes.
- **Mutation probes** (at least one per commit, restored, with SHA-256 recorded before and after):
  - T01: render the section before the page read is ready, or keep the kept list after a 404. V1 or V9 must fail.
  - T02: show the controls when the offer value is false, or resend the old key with an edited body. V12 or V23 must fail.
- **Recording runs:** report first runs and reruns separately. A full-suite failure is recorded as it happened. An isolated rerun is not a suite pass, which follows S01's records.

### 7.2 Checkpoint gate (C02)

C02 merges only per §1.3: S01 to S04 each independently reviewed, the PR acceptance cases passing, and CI on the integration head. This plan claims no merge readiness.

### 7.3 Separate events (not this slice's review verdict, and not C02 merge gates)

- **Persona browser checks** at the final integrated head, under [browser](work-register.md#browser):
  - the owner reveals to a member, then revokes;
  - a delegated GM reveals campaign-wide, then loses the delegation and is refused;
  - an editor without reveal authority reads only;
  - the player sees the public tier appear after a reveal and disappear after a revoke, each on the next request.
- **AT checks** under [ax](work-register.md#ax) and [b16](work-register.md#b16):
  - radio group and target labelling;
  - reason error summary;
  - dialog focus trap and return;
  - announcements;
  - the snapshot disclosure;
  - reflow at 320 CSS px and actual zoom.
- **Owner acceptance** at [actor-a](work-register.md#actor-a) and [p15-owner](work-register.md#p15-owner).

None of these is performed, accepted or waived here.

---

## 8. Authorization, disclosure, concurrency and cleanup

- **Authorization.** The section mounts only inside S01's ready page, so its audience is the D8 audience. The controls follow the OD-1 offer value, and member and group targets follow G-2. The server re-checks every write at a fresh instant.
- **Disclosure.**
  - Render only names the list already carries.
  - Never render ids or reasons from the server.
  - The four 404 causes are never told apart. The authoritative re-read decides between "audience gone" and "character gone".
  - Error text comes only from mapped codes.
- **Stale responses.** Every read and mutation is scoped by campaign and character. A late answer for another scope is discarded. Each mutation re-reads the list, so the GM never acts on a row the server has already closed. A revoke of a closed revelation answers `revoked: false`, and the person is told.
- **Authority loss.** A 403 withdraws the controls after the re-read. A 404 drops the section and has the page re-read, which can drop the whole page into S01's unavailable state. Losing `access.manage` withdraws the member and group options on the next overview read.
- **Protected-state cleanup.**
  - On a 404, discard the kept list, the snapshot member names and the overview options from component state.
  - On an option refresh that no longer contains the selected target, clear the target.
  - Show back only what the person typed (the reason) and the audience kind, never target names, after a confirmed loss.
- **Idempotency.** Same body means same key, and a changed body means a new key. `created: false` and `revoked: false` are successes with their own wording.

---

## 9. Intermediate states

- **After T01:** a read-only list on the page. Nothing changes for any audience.
- **After T02:** the full slice.
- **Under OD-1 = A,** the backend flag and its only consumer arrive in the same commit.
- **Neither task** changes S01's behavior, C01's Access page, or any audience read.

---

## 10. Decisions

### 10.1 Owner decisions recorded (2026-11-21)

- **OD-1: approved, option A.** A read-only boolean `can_reveal` is added to the `GET …/revelations` response, computed from the existing reveal-authority check (`resolve_reveal_authority(...) != "none"`, the value `_readable` already returns). This authorizes the bounded backend and DTO change, B1 to B3, §3w documentation and the backend verification of §7.1. It adds no authorization rule, table, lock or route.
- **OD-2: retain C02's S01 to S04 scope.** No checkpoint split and no register re-size. PR #71 remains a draft CI-evidence PR; its earlier green run belongs to head `97f75b6` only, and every later head needs its own run.
- **Authorization check made when recording OD-1** (by reading `api/character_revelations.py`, `commands/character_revelations.py`, `queries/character_revelations.py`): create and revoke use **the same** route dependency (`_reveal_precheck` → `require_may_release`: `resolve_reveal_authority != "none"`, then no whole-character deny, then the R01 `reveal_held_requirement`) and the same locked and fresh re-judgement (`_lock_caller_and_campaign`, `_judge_caller`). The authority rules do not differ, so one `can_reveal` governs both. They differ only in **state preconditions**, which are not authorization: create also needs a release (409 `public_profile_not_released`), an active character (409 `public_profile_character_not_active`) and an active target (409 `revelation_target_not_active`); revoke needs none of these and answers `revoked: false` for a closed revelation. The portal therefore offers Reveal from `can_reveal` and a release, and Revoke from `can_reveal` alone. No mismatch in authority was found.
- **Member and group targets stay limited (G-2).** Offered only with `access.manage` from the existing overview read. `access.manage` is not widened, no target is shown to anyone without it, and no target-list API is added; a reveal-scoped target-options read remains a separate follow-up, not started here.

### OD-1 (as proposed; decided above): how the portal learns that create and revoke are available

**Option A (recommended).** Add one read-only boolean, `can_reveal`, to the `GET …/revelations` response.
- **What it computes:** `resolve_reveal_authority(...) != "none"`, at read time, for the caller. No new authorization, table, lock or route; the list is already 404 under a whole-character deny.
- **The work:** one database test file (B1–B3) and one §3w sentence.
- **What it gives:** a correct, server-authoritative offer rule.
- **Cost:** it expands this checkpoint by a small backend change in T02, with backend checks and a shard run.

**Option B.** Reuse the page's `can_release`, with no backend change.
- **Cost:** it fails closed and under-offers in two cases:
  - a reveal holder with a withheld draft field, or without an identity-preview tier, sees no Reveal or Revoke;
  - nobody can revoke an archived character's live revelation in the portal, even though the API allows it.
- The register must record these as accepted limitations, and acceptance must exercise them.

**Option C (not recommended).** Show the controls to every list reader and rely on `403`.
- **Cost:** it offers write options no server value grants, contrary to [Phase 15 exit criterion](roadmap.md#159-phase-15-exit-criteria) "All portal write options come from server-authoritative catalogs and capabilities". It also contradicts S02's own criterion that "an editor without reveal authority may list but cannot create/revoke".

**Consequence of each.** A gives correct behavior plus small backend scope. B gives no backend change plus documented under-offering. C is not admissible under the exit criterion. T01 does not depend on this choice.

### OD-2 (optional owner decision): a smaller C02 checkpoint

The register gives no partial merge (§1.3). If the owner wants S01 merged before S02 to S04, the maintained route is to re-size: split C02 into two checkpoint PRs in the register and crosswalk, with new IDs, and update `actor-a` and `p15-integration` to name both, before the work continues. If the owner does not decide, C02 merges with S01 to S04 together. Nothing in this plan assumes a split.

### Plan decisions (recommendations; not blocking)

| ID | Decision | Recommendation |
|---|---|---|
| D-1 | Placement | A section on S01's Public profile page, not a separate route. Same audience; reveal follows release. |
| D-2 | G-2 targets | Member and group kinds only when the session holds `access.manage`, with targets from the existing overview read. Delegated GMs without `access.manage` reveal campaign-wide only. A reveal-scoped target-options read is a **follow-up candidate**, not part of S02. |
| D-3 | Wording | As quoted in §6. The owner may reword without changing the cases. |

### Gaps

- **G-1:** no revelation-fit reveal-authority value reaches the client. Disposition: OD-1.
- **G-2:** member and group targets are listable only under `access.manage`. Disposition: D-2 plus the follow-up candidate.

No other DTO field is proposed.

---

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Start on `phase15/completion` at the commit that records this plan. Record that SHA as the base, and record `git status --short`. Preserve unrelated work. Do not push, change PR #71, or merge.
2. Re-check §2.1 and §2.2 at the base. If anything differs, stop and report.
3. **T01** (needs no decision): implement §4's T01 column, with V1–V10. Run §7.1 and commit.
4. **T02:** OD-1 is recorded as option A (§10.1).
   - With A, add the backend boolean and B1–B3 first, in the same commit.
   - With B, use `can_release` and add the two limitations to §11.3 and to the register.
   - Implement V11–V30, run §7.1 and commit.
5. **Rules.**
   - Reuse S01's hooks, notices and focus handoff.
   - Make no S01 behavior or test change; additive mounting only.
   - Never infer authority or compute effective access.
   - Never render reasons or ids from the server.
   - No polling.
   - No C01 file change.
   - Existing classes only, unless a reflow defect requires CSS.
6. Append §11.3 with:
   - the base and the commit SHAs;
   - the commands, with counts, first runs and reruns separate;
   - the probes with SHA-256;
   - any deviation and its reason.

   Set the S02, T01 and T02 register cells to "Implemented; Luna review pending".

### 11.2 Luna independent review boundary

- **Range.** Base = the commit that records this plan. Head = T02, or the last correcting commit. Review the slice whole, and each commit on its own.
- **Required evidence.**
  1. The types equal §2.1, plus `can_reveal` if OD-1 = A.
  2. By reading, the section mounts only within S01's ready page, and no other surface requests `…/revelations`.
  3. The offer rule uses only the OD-1 server value, and the targets use only the G-2 rule.
  4. The 404, 403 and supersession cleanup in §8.
  5. Run §7.1, and map V1–V30 (and B1–B3) to tests.
  6. At least one independent mutation probe per commit, restored, with SHA-256 recorded.
  7. The §3.3 exclusions were not entered, and S01's tests are unchanged.
- **Verdict.** Use the [rubric](grading.md#severity-and-checkpoint-disposition). Keep new findings distinct from S01's closed F1, F2 and F1-R1 and from C01's inherited observations. §7.3 events are not part of the verdict.

### 11.3 Implementation record

Pending. Sonnet appends it here.
