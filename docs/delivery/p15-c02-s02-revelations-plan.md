# D/P15-C02-S02 implementation plan: list, create and revoke revelations

**Status:** Opus plan prepared 2026-11-20. Owner decisions recorded 2026-11-21 (§10.1): **OD-1 = option A** (read-only `can_reveal` on the revelations list) and **OD-2 = retain C02's S01 to S04 checkpoint scope** (PR #71 stays draft; no split). T01 and T02 are implemented ([Section 11.3](#113-implementation-record)); independent review pending. Work-register row: [D/P15-C02-S02](work-register.md#p15-c02-s02), tasks [T01](work-register.md#p15-c02-s02-t01) and [T02](work-register.md#p15-c02-s02-t02). Parent checkpoint: [D/P15-C02](work-register.md#p15-c02).

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

**Base and commits** (branch `phase15/completion`; planning baseline = implementation-review baseline `a92fb89c1f57911a748d1d59723e5e15186c414f`, which records OD-1 = A and OD-2 = retain scope):
- T01 `ab72f72df0cc6f59c408946a89dbd5d526b4ae99`: the list.
- T02 `2619f02c9dcedf936732f4f2c860147d8d548b36`: `can_reveal` (backend, B1 to B3), create and revoke, behavior documentation.
- Records commit: the commit that carries this section (documentation only).

**Authorization check (OD-1).** Create and revoke use one authority rule (`_reveal_precheck`, then `_lock_caller_and_campaign` and `_judge_caller`, all `resolve_reveal_authority`), so one `can_reveal` governs both. They differ only in state preconditions (release, active character, active target), which are not authorization and are handled by 409 messages. No authorization mismatch was found. `can_reveal` is the second value `_readable` already returns, so it adds no rule, query or lock.

**What changed.**
- Backend: `queries/character_revelations.py` returns `can_reveal`; ACCESS_CONTROL section 3w; `tests/database/test_character_revelations.py` B1 to B3 (owner and delegated GM true; a canon.edit editor and a GM whose delegation was revoked false; the key set is exactly `character_id`, `can_reveal`, `revelations`; true for an unreleased and an archived character; a whole-character deny is still 404 with no flag).
- Portal: `types/characterRevelations.ts`, `api/characterRevelations.ts`, `components/characters/CharacterRevelationsSection.tsx` and three test files. The page mounts the section after `Loaded` (not inside it, so the list survives `Loaded` rebuilds) while the page read is held, with `hasRelease` and `readPage` props. Member and group targets use the existing overview read, mounted only for `access.manage` and only after one of those audiences is chosen. No new target-list route, and no change to `access.manage`.
- S01 tests: no S01 assertion was weakened. Two test-data changes were needed because the page now makes one more request: `setup()` registers a default revelations list route (and the character-switch case registers `ch2`), and R11 now allows the section's `GET` of the list while still forbidding any revelation write, access-overview or effective-access request. The 58 S01 page tests pass.
- Deviation from section 4: V1 and V9 are in `pages/CharacterPublicProfilePage.revelations.test.tsx`, not in the S01 test file, so the S01 file's cases stay as reviewed.

**Acceptance map.** T01: V1 and V9 in `CharacterPublicProfilePage.revelations.test.tsx`; V2 to V8 and V10 in `CharacterRevelationsSection.test.tsx`. T02, all in `CharacterRevelationsSection.write.test.tsx`: V11 to V13 offer rule; V14 and V15 form and targets; V16 to V23 create outcomes; V24 to V28 revoke, including one of two overlapping revelations; V29 requests; V30 two late-response cases. Page-level T02 cases in `CharacterPublicProfilePage.revelations.test.tsx`: a revealer with a withheld draft field and `can_release` false still reveals and revokes; an editor without reveal authority edits but sees no reveal or revoke; an archived character offers revoke and refuses create by state; no release offers no Reveal. B1 to B3: the backend tests above.

**Commands and results** (first runs).
- T01: focused page 58, section 8, page-revelations 4: 70 passed. Full portal `npm test`: 434 files, 5364 tests passed. Lint, `tsc -b`, build passed.
- T02: focused section list 8, section write 29, page-revelations 8, S01 page 58: all passed. Full portal `npm test`: 435 files, 5397 tests passed (the earlier S01 load-timeout failures did not recur in these runs). Lint, `tsc -b`, build (existing large-chunk warning) passed.
- Backend: `uv run pytest` on the three `test_character_revelations*.py` files (main, keyed, http matrix): 80 passed. `ruff format --check`, `ruff check`, `mypy src`: passed. Sharded runner (`scripts/run_sharded_tests.py`, four shards, on the T02 tree): 11313 passed, 6 skipped, 11319 collected, RESULT PASSED, 30 min 37 s.
- `scripts/check_documentation.py` and `git diff --check`: passed.

**Mutation probes (restored; SHA-256 before and after are identical).**
- T01: the section never treats a 404 as gone (`gone = false`): 3 tests failed (section V6 and both page V9 cases). Section SHA-256 `fec2d6fbae705fe757284d721b1f972d4a1c74be8f0daa7cb7ffc23b1215c71c`.
- T02: `canReveal` forced true whenever a list is read: 5 tests failed (V12 and the page-level editor case, among others). Section SHA-256 `5bd18a039f1bd2f4e2b4855876ca16ba12eda66c3e05c5ee835611e97fddd637`.
- The B1 to B3 tests assert a key that did not exist before the change; no separate backend probe was run.

**Limits and not done.**
- Browser, zoom, screen-reader and assistive-technology checks (radio group, error summary, dialog focus, announcements, snapshot disclosure); persona and human checks; `actor-a`, owner acceptance and final integrated-head evidence: none performed, none claimed.
- Member and group targets stay limited to `access.manage` holders (G-2); a delegated GM without it can reveal campaign-wide only. The reveal-scoped target-list follow-up was not started.
- CI: PR #71's earlier green run belongs to head `97f75b6` only. The new head's CI is reported in the report for this task, not in this record.
- S03, S04, `copy-ui`, `preview` and the target-list follow-up were not started.

**Luna review ranges.** Whole slice `a92fb89c1f57911a748d1d59723e5e15186c414f..<records head>`; T01 `a92fb89..ab72f72`; T02 `ab72f72..2619f02`; the records commit is documentation only.

### 11.4 Independent implementation review (Codex)

**Boundary and repository state.** Reviewed T01 `a92fb89c1f57911a748d1d59723e5e15186c414f..ab72f72df0cc6f59c408946a89dbd5d526b4ae99`, T02 `ab72f72df0cc6f59c408946a89dbd5d526b4ae99..2619f02c9dcedf936732f4f2c860147d8d548b36`, and combined implementation plus records through `74fe6ecb96d0df92664e24901810e0591e2f1345`. All objects resolve and the commits are in the reported ancestry. Branch `phase15/completion`; HEAD was `74fe6ecb96d0df92664e24901810e0591e2f1345`; worktree was clean before review edits. No applicable `AGENTS.md` was present. No production files were changed.

**Verdict.** T01: **CHANGES REQUIRED**. T02: **CHANGES REQUIRED**. Combined S02: **CHANGES REQUIRED**. The list/read audience and `can_reveal` policy align with the contracts, and the existing test map is meaningful, but the findings below fail the scoped stale-content, target-offer and focus behavior. Findings use `docs/delivery/grading.md`; the scores are exposure + impact + triggerability + detection/recovery + blast radius.

**T01 finding R-S02-1 — authoritative list denial leaves the previously read profile visible (5/10, Medium; blocks T01).** In `portal/src/components/characters/CharacterRevelationsSection.tsx` lines 137–149, a list 404 hides only the revelations section and asks the parent to refetch. The list query calls the same `_readable` policy as the draft in `src/dnd_ai/queries/character_revelations.py` lines 20–32 and `src/dnd_ai/queries/character_public_profile.py` lines 434–446: a 404 means the D8 profile is unavailable (including whole-character denial). While the parent GET is pending, and if it returns a recoverable 5xx, `PublicProfile` in `portal/src/pages/CharacterPublicProfilePage.tsx` lines 239–242 keeps and renders its previous `view`; a stale notice does not remove protected draft/release content. This is reproducible when a previously readable page's revelations GET returns 404 and the resulting page refetch returns 500. Expected: immediately clear the page's protected view after this authoritative denial; actual: only the list is removed and the old profile remains visible through the failed refresh. Exposure 1 (a constrained authorization transition/read race), impact 2 (continued presentation after a denial), triggerability 1 (routine navigation or a refresh during that transition), detection/recovery 1 (the list's unavailable message does not disclose that the rest of the page is stale after denial), blast radius 0 (one character/page). Correction: propagate the authoritative loss signal to the page boundary and synchronously drop the page view, breadcrumb and child state; only a subsequent successful authorized page read should restore it. Add an integration regression with list 404 followed by a failed page read, asserting no protected page content remains during or after that failure. The current V9 tests cover list 404 followed by page 404 and a mock list 404 followed by successful page read; they do not cover the failed re-read window.

**T02 finding R-S02-2 — an old member/group selection remains submittable after `access.manage` is lost (5/10, Medium; blocks T02).** In `CharacterRevelationsSection.tsx` lines 141, 282–303 and 296–327, `canPickTargets` removes member/group radio options and the picker when the applied bootstrap loses `access.manage`, but does not clear `kind`, `targetId` or `targetName`, and `submit()` does not revalidate `canPickTargets`. A manager can select a target, then lose `access.manage` while retaining `can_reveal`, and submit the still-open form; the request contains the hidden old target. The write route correctly rechecks reveal authority, but deliberately does not require `access.manage`; that server policy does not restore the portal's D-2/G-2 offer condition. Expected: remove or invalidate targeted selection and prevent a targeted write as soon as the applied capability is absent; actual: hidden stale selection is sent. Exposure 1 (a mid-form capability change), impact 2 (a profile reveal can be created for a target after the target-selection capability was lost), triggerability 1 (ordinary session refresh/revocation), detection/recovery 1 (the selected audience is no longer visible in the form, so the write can be surprising), blast radius 0 (one reveal). Correction: clear targeted kind/ID/name when `canPickTargets` becomes false and guard submit against a targeted kind without the current capability. Add a production-component regression that selects a member/group, applies a bootstrap without `access.manage`, then proves submit cannot issue the targeted POST or an overview read.

**T02 finding R-S02-3 — failed post-write read leaves focus on body instead of a usable recovery/status target (2/10, Low; nonblocking alone, but recorded against the promised focus behavior).** In `CharacterRevelationsSection.tsx` lines 261–268, successful mutation handling closes/removes the form and later refocuses only when `activeElement` is body/null. After a confirmed write whose list re-read fails, the replacement Reveal button exists but is disabled by `writesHeld`; `.focus()` on that disabled button does not move focus, and the effect does not then try the section heading or failure notice. A focused regression probe expected the heading fallback and observed `document.body`. Expected: focus a connected, focusable status/heading fallback when the primary target is unavailable; actual: focus remains at body. Exposure 1 (confirmed write plus recoverable read failure), impact 1 (keyboard user loses place at an error/recovery state), triggerability 1 (supported failure path), detection/recovery 0 (visible failure and the user can tab back), blast radius 0. Correction: choose a focusable enabled target before calling `.focus()`, with the section heading or recovery status as fallback, and test the failed-read case. Existing move-away handling is correct: a different connected focused element is left alone. This does not reopen S01 F2.

**Acceptance review.** The backend `can_reveal` value derives from the same D8/read authority helper used by create and revoke; it remains independent of release, archive and target eligibility. The backend tests cover owner/delegated/revoked/editor, whole-character deny, unreleased and archived cases. T01 V1–V10 and T02 V11–V30 have assertions in the page, list and write test files; B1–B3 are covered in `test_character_revelations.py`. Reads preserve server membership/order/snapshot data; labels distinguish live/ended rows and end reasons, and render neither IDs nor submitted reason text. Create/revoke require reasons, map duplicate outcomes to success, use same-key/same-body retries and new keys for edited bodies, hold writes after confirmed-read failure, and do not resend confirmed mutations. 403/404 recovery, active-only target options, overlapping revelation revocation, dialogs, announcements and late mutation scope are exercised. One real boundary detail is that backend 404 from the list is authoritative for the same D8 page read; V9's successful-re-read fixture does not establish safe cleanup when that re-read fails.

S01 integration was checked in the focused run: its 58 page tests passed, including withheld-value behavior and release interactions; the changed fixture registers the additive GET and still disallows revelation writes, access-overview and effective-access requests. The review found no changed release snapshot behavior, no release-triggered revelation write, and no regression of the prior F1/F2/F1-R1 conclusions. S01's earlier full-suite timeout records remain historical and are not replaced by this review.

**Independent verification (PowerShell).**
- Portal focus: from `portal/`, `npm test -- src/components/characters/CharacterRevelationsSection.test.tsx src/components/characters/CharacterRevelationsSection.write.test.tsx src/pages/CharacterPublicProfilePage.revelations.test.tsx src/pages/CharacterPublicProfilePage.test.tsx` — 4 files, 103 tests passed. This includes the 58 S01 page tests. `npm run lint` passed; `npm run build` passed with the existing large-chunk warning. A full portal run was not repeated locally.
- Backend focus: `uv run pytest tests/database/test_character_revelations.py tests/database/test_character_revelations_keyed.py tests/database/test_character_revelations_http_matrix.py` — 80 passed, one Starlette/httpx deprecation warning. `uv run ruff format --check src/dnd_ai/queries/character_revelations.py tests/database/test_character_revelations.py`, matching `ruff check`, and `uv run mypy src` passed. The first style invocation used the incorrect `src/dnd_ai/api/queries/` path and failed before checking the changed source; the corrected query path is `src/dnd_ai/queries/` and all checks passed.
- `uv run python scripts/check_documentation.py` and `git diff --check` passed both before and after the review edits.
- `uv run python scripts/run_sharded_tests.py` — independent four-shard run passed: 11,313 passed, 6 skipped, 11,319 collected and executed; all four shards exited 0 in 29m34s. Logs are under `.tmp/shards/run-20261120-214753-29860`. The implementation's recorded 11,313-pass run remains distinct from this independent run.
- Inspected CI run `44858620938`: completed success, event `pull_request`, PR head SHA `74fe6ecb96d0df92664e24901810e0591e2f1345`. Workflow logs show checkout of synthetic merge ref `refs/remotes/pull/71/merge` at `c40e2cffd305d5661d6ce02ec6b2cfdd92506fbc`. This is current-head PR CI evidence for the then-current merge tree, not proof of an isolated checkout of the PR head. Earlier-head CI was not reused.

The implementer's T01 and T02 mutation probes were inspected: forcing the list to remain after 404 failed three V6/V9 tests; forcing `canReveal` true failed five editor/offer tests. Their restored source hashes are retained in §11.3. Targeted independent tests reproduced the stale-target send and disabled-focus fallback gap; temporary test changes were restored, and the reviewed worktree was clean before this record edit. No new backend mutation probe was needed because the authority/query cases have direct database assertions and passed the focused run.

**Outstanding review limitations and next action.** No real browser, zoom, screen-reader/AT, human, owner, actor-a or final integrated-head browser/AX evidence was performed or claimed. PR #71 remains unmerged and its draft state was not changed. Keep those obligations separate. Sonnet correction should be bounded to R-S02-1 through R-S02-3 and their regressions, then re-review the correction; do not begin S03/S04 or `copy-ui`/`preview`.

### 11.6 Independent re-review of R-S02-1 to R-S02-3 (Codex)

**Boundary and state.** Reviewed `74fe6ecb96d0df92664e24901810e0591e2f1345..7c34358c50fdaa9db7817571b1a2463355c9ec77`; code commit `722333c93c37a15409023a245f432f182022aa7c`; records/head `7c34358c50fdaa9db7817571b1a2463355c9ec77`. The commits are in ancestry on `phase15/completion`. HEAD was `7c34358c50fdaa9db7817571b1a2463355c9ec77`, and the worktree was clean before temporary test probes and review documentation. No applicable `AGENTS.md` was present. Temporary test edits were restored to the exact HEAD blobs. No production code was changed.

**Separate verdicts.** T01: **PASS WITH VERIFICATION LIMITS; R-S02-1 closes for the persistent stale-content behavior.** T02: **CHANGES REQUIRED; R-S02-2's selection/submit behavior is fixed, but the retry-attempt disposal requirement is incomplete; R-S02-3 works for an in-place failed re-read but not when the page masks and unmounts the section.** Combined S02: **CHANGES REQUIRED** until the two T02 findings below are corrected and independently re-reviewed.

**R-S02-1 disposition.** The page masks `keptView` whenever `readDenied` is true, clears its refusal, and only lifts that mask after a successful page refetch. A failed or superseded read cannot expose the old `useKept` value; supersession is retried once, then the masked state offers a manual read retry. The section hides the denied list and is unmounted while the page is masked, so its target picker and read state cannot repopulate that page. A create/revoke POST 404 remains on the write-refusal path and does not set `readDenied`; the integration case keeps the page and describes the unavailable audience. The denial loop guard prevents repeated automatic parent reads; the user can retry manually.

Rewritten V9 is fail-closed, not a relaxation: when a later list read denies after a successful page read, the later denial masks the page; it does not restore the old `useKept` data. The reported brief interval after `readDenied` is lifted follows a successful page GET that began after the earlier denial, so the displayed page data is freshly authorized at that read. The child then makes a new list read; if that newer read denies, masking resumes. I found no stale child response that can lift the parent mask. A temporary layout-phase jsdom probe did not capture a pre-mask frame, and no real-browser paint or screen-reader test was performed; I do not treat the reported freshly-read interval as an exposure finding. Breadcrumb denial is passed to the existing label hook, which forgets through its passive effect; the focused suite did not seed/verify a previously cached character label during that transition, so immediate browser-frame timing remains a verification limit.

**T02 finding R-S02-4 — a targeted unresolved attempt's body and key survive the capability-loss reset (3/10, Low; correction-contract gap).** `CharacterRevelationsSection.tsx` calls `createMutation.reset()` when access.manage is lost after an ambiguous targeted-create failure. In `useAuthoringMutation`, `reset()` resets only the visible snapshot; it does not clear `unresolvedRef` or `reservationRef`. I added a temporary PowerShell/Vitest probe: after a targeted POST returned a network error, access.manage was removed and restored, then the user reselected the same member and submitted the same reason. The second POST reused the first `Idempotency-Key`; an assertion requiring a fresh attempt failed. Exposure 1 (requires capability loss and restoration on the same open form), impact 1 (retains and can replay an old target/body context, though the user must select and submit again and the key preserves idempotency), triggerability 1 (special sequence), detection/recovery 0 (the old attempt is not shown as a Retry action and no duplicate is created), blast radius 0. This does not bypass the current access.manage guard, silently restore the target, widen the audience or create duplicate records. It does fail the correction's explicit requirement to clear targeted retry bodies/keys and pending intent. Correction: provide a way to discard this scope's unresolved attempt/key when access.manage is lost, without changing other mutation scopes; test that restoring access and resubmitting the same visible form values starts a new keyed attempt.

The original R-S02-2 behavior otherwise closes: render-time state reset clears targeted kind/id/name and target error; the target picker unmounts, so no new overview reads start; `submit` guards the current capability; the option is not restored on capability return; and no campaign-wide audience is selected silently. Campaign-wide actions remain available. A POST already dispatched while access.manage was present may finish; no new POST is dispatched after the applied loss. The tests exercise actual session bootstrap refresh and relevant request counts, but do not assert key disposal (the temporary probe above covers that gap).

**T02 finding R-S02-5 — focus is lost when an authoritative denial masks the page (3/10, Low; blocks the promised focus handoff).** The section's corrected `useLayoutEffect` works while the section remains mounted: it chooses an enabled Reveal button or the section heading, and it leaves a different focused control alone. It cannot run its fallback after the parent switches to `view === null` and unmounts the section. I added a temporary page-level probe for a focused Reveal submit, a confirmed create, a revelations-list 404, and a held parent read. The masking assertion succeeded, but `document.activeElement` was `document.body`, not the Public profile heading or another meaningful control. The page does not establish a focus destination on this denial/mask branch. Exposure 1 (keyboard user during the constrained confirmed-write/authority-loss path), impact 1 (loss of place and no focused explanation/recovery control), triggerability 1 (a supported denied re-read), detection/recovery 0 (the unavailable notice is visible and the user can Tab), blast radius 0. Correction: coordinate focus at the page boundary when it masks/unmounts the section, preserving focus moved to a connected control and otherwise moving to a connected, enabled page alert/retry or heading. Add an integration test; isolated section focus tests alone cannot prove this lifecycle.

**Before-fix evidence and acceptance assertions.** The §11.5 record says eight tests failed with production files reverted: three target-loss cases, two section focus cases, the R-S02-1 integration regression, rewritten V9, and V6. I do not count V6 as behavioral evidence: it depends on the changed callback prop interface. The other seven cases target behavioral outcomes; the page assertions specifically distinguish the retained-content behavior and the latest-denial loop guard. The current V9 tests preserve the original intent that a list denial causes a parent read, and add a stricter fail-closed state when a subsequent child read denies; they do not establish a visible pass through the inconsistent-response interval. The full suite history in §11.5 remains three separate failed runs and a fourth passing run; I did not repeat it. S01's 58 page tests passed in the focused run, and the corrected page did not alter S01 field disposal, immutable release rendering, or its focus handoff.

**Independent verification (PowerShell).**
- From `portal/`: `npm test -- src/components/characters/CharacterRevelationsSection.test.tsx src/components/characters/CharacterRevelationsSection.write.test.tsx src/pages/CharacterPublicProfilePage.revelations.test.tsx src/pages/CharacterPublicProfilePage.test.tsx` — 4 files, 111 passed, including S01's 58 page tests. `npm run lint` passed. `npm run build` passed with the existing large-chunk warning.
- I did not repeat the three failed full-suite runs, the fourth passing full-suite run, or the backend shards. The four recorded full-suite events in §11.5 remain separate; no isolated test is substituted for them.
- Inspected CI run `44867034227`: completed success for PR head `7c34358c50fdaa9db7817571b1a2463355c9ec77`. Completed workflow logs show all observed jobs fetched and checked out synthetic merge ref `refs/remotes/pull/71/merge` at full SHA `6d0295117957739ddb88ff29b81c9dcc42202af5`. This verifies CI on the synthetic merge containing this PR head, not a checkout of the PR head alone.
- The valid temporary R-S02-4 probe failed its `not.toBe(oldKey)` assertion because the key was reused. Its first exploratory invocation did not run because `pickMember` was local to a test block; the corrected probe did run. The R-S02-5 page probe failed its expected-heading-focus assertion: actual focus was `body`. Both temporary test files were restored; their current blobs match HEAD (`CharacterRevelationsSection.write.test.tsx` `69d1ce34aae66c971e557c810e54a8fec7e0e094`; `CharacterPublicProfilePage.revelations.test.tsx` `9679cdec7c87c4bd55a2f7edf3f857d393a8e678`). The separate layout-phase mask probe was inconclusive under jsdom/React act and is not presented as browser paint evidence.
- `uv run python scripts/check_documentation.py` and `git diff --check` passed after this review entry was written. No backend run was warranted for this frontend-only correction.

**Limits and next action.** No browser, zoom, screen-reader/AT, persona, human, `actor-a`, owner or final integrated-head browser/AX evidence was performed or claimed. PR #71 remains draft and unmerged. A bounded Sonnet correction should clear the unresolved targeted mutation attempt/key on applied access.manage loss, add the page-level focus handoff for masking/unmount, and add the corresponding integration regressions; preserve R-S02-1, all S01 behavior and the three-failures/one-pass full-suite history. Then re-review the correction. Do not start S03/S04 or consumers.


### 11.5 Correction of R-S02-1 to R-S02-3 (Sonnet; independent re-review pending)

**Baseline and range.** Baseline `74fe6ecb96d0df92664e24901810e0591e2f1345`. The correction commit and the records head are reported in the report for this task (a record cannot name its own commit). Re-review range: `74fe6ecb96d0df92664e24901810e0591e2f1345..<correction head>`. The review verdicts in Section 11.4 and the S01 passes are unchanged. All three findings are marked **corrected, pending independent re-review**; none is marked passed. No backend, DTO, S01 behavior, C01, S03/S04, `copy-ui` or preview change.

**R-S02-1 (page content after a list 404).** `CharacterRevelationsSection` now reports a list 404/403 through a new required prop `onReadDenied` (the existing `readPage`, used for authority or release changes after a refused write, is unchanged). `CharacterPublicProfilePage` sets `readDenied` at once: the page's view, refusal notice, form, release and breadcrumb name are masked from that render, whatever the kept view or a later failed read says, and it re-reads the page. Only a successful read of the page lifts the mask (a failed or recoverable-error read leaves it closed with a **Try again** notice that asks for the next read). A replaced ("superseded") read is retried once more. A denial straight after a read that lifted one is not read again by itself (the list and the page would otherwise answer each other forever); the person asks. A write's own 404 is unchanged: it explains the audience is gone, re-reads the list and leaves the page.

**R-S02-2 (stale target after `access.manage` loss).** When the applied capability is lost, the section clears a member/group choice (the audience becomes "no choice", never a wider one), the selected id and name, the target form error and a retry of a failed targeted create, and the picker (with its overview read) unmounts. `submit` also refuses a targeted kind without the capability held now. The old selection is not restored when the right returns. Campaign-wide actions depend only on `can_reveal` and are unchanged; the server's authorization is not widened.

**R-S02-3 (focus after a confirmed write and a failed re-read).** The post-write focus effect now takes Reveal only if `canTakeFocus` says it can (it is disabled while a failed read holds writes) and otherwise the Revelations heading; focus already on another meaningful control is left alone. It covers create and revoke. S01's `createFocusHandoff` is untouched.

**Tests added or changed.** `CharacterRevelationsSection.write.test.tsx`: Host now also renders a "Refresh session" button that applies a supplied bootstrap (and is a non-section control for the focus case); `setup` takes `onRefresh`; six new cases (R-S02-2: selection cleared and no targeted POST or overview read with campaign-wide still working; not restored when the right returns; no retry of a failed targeted create. R-S02-3: create and revoke fall back to the heading; focus moved to another control survives a failed and a good re-read). `CharacterPublicProfilePage.revelations.test.tsx`: the V9 case is rewritten for the new behavior (a list 404 with a page that then reads fine reads the page once and stays closed until asked again) and two cases added (list 404 then a held then failed page read leaves no protected content during or after and a later good read restores it; a write's own 404 leaves the page). The other section test files only pass the new prop.

**Failing before the correction (production files reverted, tests kept).** 8 tests failed: the three R-S02-2 cases, the two R-S02-3 cases, the R-S02-1 regression and the rewritten V9 case, plus V6 (it needs the renamed prop). They pass with the correction.

**Verification.** Focused run (section list 8, section write 35, page revelations 10, S01 page 58): 111 passed. `npm run lint`, `tsc -b` and `npm run build` (existing large-chunk warning) passed. Full `npm test`: 435 files, 5405 tests passed on the fourth run. The first three full runs each had one or two unrelated tests exceed their 8 s wait under load (`CharacterRelationshipsSection`, `QuestCompletionSections`, `AuditHistory`, a different one each time), each passing when its file was run alone, so those runs are recorded as failed and the clean fourth run is a rerun, not a replacement. Documentation and diff checks: see the report for this task. No backend behavior changed, so no backend run was made or claimed; the 11313-pass sharded run in Section 11.3 remains the backend evidence for the code it ran on. The tests run in the PowerShell tool: the Bash tool's environment in this session made Vitest fail to start ("failed to find the current suite") for any file.

**Limits.** No browser, zoom, screen-reader or assistive-technology check; no persona, human, `actor-a`, owner or final integrated-head evidence. The brief unmasked frame between a lifted denial and a second one is a scripted-test observation only. Member/group targets remain limited to `access.manage` (G-2).


### 11.7 Correction of R-S02-4 and R-S02-5 (Sonnet; independent re-review pending)

**Baseline and range.** Baseline `7c34358c50fdaa9db7817571b1a2463355c9ec77`. The correction commit and the records head are reported in the report for this task (a record cannot name its own commit). Re-review range: `7c34358c50fdaa9db7817571b1a2463355c9ec77..<records head>`. Both findings are marked **corrected, pending independent re-review**; neither is marked passed. T01's pass with verification limits, the R-S02-1 closure, the Section 11.4 and 11.6 review text and the 11.5 correction record are unchanged. Frontend only: no backend, DTO, S01 behavior, S03/S04 or consumer change.

**R-S02-4 (targeted retry state).** `useAuthoringMutation` gains `discard()`: it forgets this scope's unresolved attempt (body and request) and its reserved idempotency key, and returns to idle unless a request is in flight (that one is left to finish; if it then fails unresolved, the section's effect discards it again). Other scopes' refs are untouched (it checks the scope key). The section calls it when the applied session loses `access.manage` after a failed targeted create, and when the Retry affordance is used in that state. Retries while the right is held are unchanged (same body, same key). Restoring the right and choosing the same member and reason again sends a new attempt under a new key. The discarded attempt is not called unsent: its server outcome may be unknown, and the code and the hook comment say only that it is no longer this form's to repeat.

**R-S02-5 (focus across the mask).** The page records, from its focus events, whether focus was last inside the Revelations section (a blur of a control that is still connected clears it; a control removed with the section leaves the note). When the authoritative denial masks the page, a layout effect gives focus to the page heading only if the note says the section held it and focus is on nothing (body or null); focus moved to another connected control is left alone, as is focus that was never in the section. The page component is keyed on campaign and character, so the note never outlives its character: a late answer for the character left cannot act on the next. S01's `createFocusHandoff` is untouched.

**Tests added.** Hook: `discard` forgets this scope's attempt and key, leaves another scope's attempt (and its key on retry) alone, and a retry before it reuses the key. Section: the R-S02-4 sequence with request keys (network failure, same-key Retry, capability lost, Retry gone, capability restored, the same member and reason reselected: third POST has the same body and a different `Idempotency-Key`). Page, `focus across the masking`: a confirmed create and a confirmed revoke each followed by a list denial put focus on the page heading; focus moved to another connected control meanwhile is kept; focus never in the section is not taken; after navigation to another character a late answer for the first leaves focus and the second page alone.

**Failing before the correction (the three production files reverted, tests kept).** 4 tests failed: the hook `discard` test, the R-S02-4 section test (the second POST reused the first key) and the two page focus cases (confirmed create, confirmed revoke: focus on body). The other three page cases are guards that also pass without the correction.

**Verification.** Focused run (section list 8, section write 36, page revelations 15, S01 page 58, hook 25): 142 passed. `npm run lint`, `tsc -b` and `npm run build` (existing large-chunk warning) passed. Full `npm test`: the first run failed one unrelated test (`App.characterShell`, "gives the defaults after a direct entry and carries no task into the section links", at 200 ms; the file passes alone, 35/35); the rerun was clean, 435 files and 5412 tests. These are two separate results: one failed run and one clean rerun. Documentation and diff checks: see the report for this task. Tests were run in PowerShell. No backend behavior changed, so no backend or shard run was made or claimed.

**Limits.** No browser, zoom, screen-reader or assistive-technology check; real focus-on-removal behavior in browsers (jsdom does not fire blur for a removed element) is a scripted-test assumption. No persona, human, `actor-a`, owner or final integrated-head evidence. Member and group targets remain limited to `access.manage` (G-2).
