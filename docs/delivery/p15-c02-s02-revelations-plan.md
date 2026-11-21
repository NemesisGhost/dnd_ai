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

### 11.8 Independent re-review of R-S02-4 and R-S02-5 (Codex, 2026-11-21)

**Boundary and state.** Reviewed `7c34358c50fdaa9db7817571b1a2463355c9ec77..61bf877874b079aac75d552b9176c8a674f8b06e`; correction code commit `96f7265654fc93b4f14045ba3bd80179d2d45091`. The branch was `phase15/completion`, HEAD was `61bf877874b079aac75d552b9176c8a674f8b06e`, and the worktree was clean before this record edit. The supplied base, code commit and head resolve in the repository and have the reported ancestry. No `AGENTS.md` was present. No production code was changed. The original review and §11.7 correction evidence remain intact.

**R-S02-4 — still open; CHANGES REQUIRED (4/10, Medium, application).** The normal sequence tested in §11.7 works: an already-failed targeted create is discarded on applied `access.manage` loss, same-attempt retries while authorized retain the same key, and a later deliberate selection starts with a new key. The correction does not cover capability loss while the write is pending if authority returns before that write fails. `discard()` clears `unresolvedRef` and `reservationRef` at loss time but deliberately leaves an in-flight request. When that request later returns a server/network failure, `start()` unconditionally rebuilds `unresolvedRef`; the section effect discards only when `!canPickTargets` is still true. Thus a restored manager sees a Retry for the old targeted body without reselecting that member. A temporary test held the POST, applied a bootstrap without `access.manage`, restored `access.manage`, then returned HTTP 500. After waiting for the truthful “Something went wrong on our side” state, the assertion that Retry remained absent failed because Retry was present. The temporary test was removed byte-for-byte (test-file SHA-256 before and after: `66D6D2FE2912A9526CC864878A7AE0B2A55C3BFD0BD4589A7397707BE1F8B1BB`).

Score factors: exposure 1 (authenticated manager, capability loss/restoration during a pending request), impact 1 (an old targeted create can be replayed after the target selection was withdrawn; the request remains idempotent and does not establish a duplicate), triggerability 1 (special but ordinary session/request timing), detection/recovery 1 (the generic unknown-outcome Retry does not identify its old target and is available without a fresh target selection), blast radius 0 (one attempt). The outcome remains unknown; clearing local retry state must not be described as proof that the server did not commit. The issue does not confer authority while `access.manage` is absent, but violates the explicit disposal contract and can replay after restoration. It blocks T02 acceptance at the stated R-S02-4 criterion. **Bounded correction:** remember a scope-specific discard-on-settlement intent when target authority is lost during a pending targeted create; when that request settles, do not make its body/key retryable even if authority has since returned. Keep the unknown outcome truthful, keep same-attempt retries unchanged when authority never drops, and prevent the stale completion from affecting a new attempt. Add the exact loss → restore → delayed failure regression, then verify same-body reselection gets a fresh key and unaffected mutation scopes remain intact.

**R-S02-5 — closed for implementation, with browser verification limits (2/10, Low).** The page-level focus marker is attached to the parent containing the Revelations section; the native `ConfirmDialog` is rendered inline in that subtree, so both create controls and revoke-dialog controls reach the parent focus handler. When denial masks the page, the layout effect focuses the connected, programmatically focusable page heading only if focus had been in Revelations and is now body/null. It leaves a connected control the user moved to alone. The page is keyed by campaign and character, so old intent does not transfer to the next record. The added tests exercise confirmed create and revoke, heading fallback, move-away preservation, focus that was not in the section, and late completion after navigation. The relevant standard is [portal-style §10a](../reference/portal-style.md#10a-authoring-forms-dialogs-and-badges-phase-14): preserve eligible dialog/focus ownership and keep async feedback separate from focus.

I inspected the jsdom limitation rather than treating its results as browser proof. A standalone Integrated Browser DOM probe showed removal of a focused descendant left focus at `body` and produced no recorded blur/focusout event in that probe, which is the path the page marker is designed to handle. No portal/backend listener was available and no authenticated application tab existed, so I could not exercise real create/revoke denial flows in the application or verify every browser's native event ordering. I found no demonstrated focus defect in the correction; those app-level browser and all AT checks remain pending, not passed. The §11.7 pre-fix evidence is meaningful for the two page behaviors: both create and revoke denial tests observed focus on body before the page handoff. The hook test that failed because `discard()` did not yet exist is API-presence evidence only; the previous section test that reused the old key and this re-review's delayed-failure probe are the behavioral evidence for R-S02-4.

**Carried dispositions.** T01 remains **PASS WITH VERIFICATION LIMITS** and R-S02-1 remains closed. S01's prior implementation review and focus behavior are unchanged. T02: **CHANGES REQUIRED** because R-S02-4 remains open; R-S02-5 is closed with browser/AT limits. Combined S02: **CHANGES REQUIRED**. The correction does not close the slice.

**Independent verification.** From PowerShell in `portal/`, `npm test -- src/components/characters/CharacterRevelationsSection.test.tsx src/components/characters/CharacterRevelationsSection.write.test.tsx src/pages/CharacterPublicProfilePage.revelations.test.tsx src/pages/CharacterPublicProfilePage.test.tsx src/hooks/useAuthoringMutation.test.tsx`: 5 files, 142/142 passed. `npm run lint`: passed. `npm run build`: passed with the existing large-chunk warning. The temporary R-S02-4 probe failed as expected and was restored; this is a separate targeted regression result, not part of the 142-test run. I did not repeat the full portal suite or backend shards; preserve the §11.7 failed full run and its later successful rerun as separate events. Documentation and diff checks are recorded after this entry is added.

**CI.** `gh run view 44924999908` reports completed success for PR head `61bf877874b079aac75d552b9176c8a674f8b06e`. The completed workflow logs show checkout of `refs/remotes/pull/71/merge` at `71b4d14affdc4a101b08a7964668df5144738ba1`, merging that head into base `bf23c7648601eb1b3ad479078f2762fe13fd460b`. This is CI evidence for the synthetic merge checkout containing the exact PR head, not an isolated checkout of the PR head. It does not close browser/AX, human, owner, or final integrated-head obligations. PR #71 remains draft and unmerged.

### 11.10 Independent confirmation of the R-S02-4 correction (Codex, 2026-11-21)

**Boundary and state.** Reviewed `61bf877874b079aac75d552b9176c8a674f8b06e..c4d5856fe4b3e785eeb9b9b9f1ca9e07855150f3`; code commit `6f0c8170f5a282c9a8f13dc5deee28b7c3880ea4`. Base and code are ancestors of the records head. Branch `phase15/completion`; HEAD `c4d5856fe4b3e785eeb9b9b9f1ca9e07855150f3`; worktree clean before this record update. No applicable `AGENTS.md` was present. The prior §11.8 finding and §11.9 correction evidence remain intact. No production or test source was changed during this review.

**Disposition: R-S02-4 remains open; T02 and combined S02 are CHANGES REQUIRED.** The main delayed-failure correction works: the section calls `discard()` when applied `access.manage` loss occurs during a targeted create; a later HTTP 500 after authority restoration is not offered as Retry; reselection sends the same body with a fresh key. Same-attempt retry retains its key when authority stays available. A discarded request confirmed by the server remains a confirmed success with its receipt; definitive refusals still use their refusal status. Unrelated hook instances are isolated because each owns separate refs, and no other production caller invokes `discard()`.

There are two remaining contract gaps under R-S02-4:

1. **The withdrawn unknown outcome is silent.** After a discarded network/500 response, `useAuthoringMutation` sets status to `idle`; `CharacterRevelationsSection` renders no status or announcement. The hook does not say the write failed or succeeded, so the idle state is semantically neutral, but the user receives no command feedback that the audience may already have received access. The list is not re-read on this generic server/network path. The correction's test explicitly asserts that no unknown-outcome message is shown. Plan V23 requires feedback for network/5xx outcomes. Removing the retry action is appropriate after this target attempt was withdrawn, but suppressing all outcome messaging does not satisfy the feedback contract. A user can select an audience again and start a new-key create without knowing whether the earlier request took effect. Track: application. Score **4/10, Medium**: exposure 1 (authenticated GM and a targeted request spanning capability loss), impact 1 (uncertain command result and possible repeated create), triggerability 1 (special but routine session/network timing), detection/recovery 1 (no notice or automatic read tells the user the result), blast radius 0 (one character/attempt). This blocks V23/R-S02-4 acceptance. Preserve unknown status, omit Retry for the withdrawn body, and provide a truthful notice plus a safe read/check path before another create.

2. **The late-settlement identity guard is incomplete if a same-scope reset starts a replacement attempt.** The new branch checks `discardedRef` by attempt number, but then unconditionally clears same-scope `unresolvedRef` and writes `IDLE`; it does not verify that this settlement still owns the active snapshot. A temporary hook probe called the public `reset()` while a withdrawn request remained pending, started a new same-scope request, then failed the old request. The old failure changed the newer request's visible status from `pending` to `idle`. The assertion failed; the temporary test was restored byte-for-byte (SHA-256 before/after `A12BEAE89FD161B496D5DC907D35B5E04B41F92F8474265CCD19FD4C05F93B02`). The current S02 component passes `reset` through `useConfirmedRefresh`, which calls it only for a confirmed/read-back episode, so I found no normal S02 user path that resets during a pending create. I therefore treat this as an exposed shared-hook lifecycle/API gap rather than a second independently scored product trigger; nevertheless the correction's unconditional claim that attempt identity prevents a late settlement from corrupting newer attempts is not established. Make settlement state writes conditional on current attempt ownership, or disallow/reset pending attempts without allowing a replacement send. Test this exact overlap and retain cross-scope isolation. `useAuthoringMutation` consumers that do not call `discard()` do not enter the new branch, and the changed behavior is otherwise confined to the Revelations caller.

**Before-fix evidence.** §11.9's two failing tests are behavioral, not API-presence failures: the section's held POST → capability loss → restoration → HTTP 500 test observed Retry, and the hook's in-flight discard test observed a retryable error. This review's rerun passes the corrected no-Retry assertions but also confirms they omit a user-visible unknown-outcome notice. The reset-overlap probe above exposes the limit of the attempt-identity assertion in §11.9.

**Bounded correction.** Keep the lost target attempt non-retryable after authority loss, while exposing a truthful, accessible unknown-outcome state that does not imply failure or success, offers no replay of the withdrawn body, and guides the user to re-read current revelations before making a new attempt. Ensure late settlements update only state owned by that same attempt/scope, and cannot erase a replacement attempt. Preserve confirmed receipts, definitive refusal messages, same-key authorized retries, new keys after deliberate reselection, and unrelated mutation consumers. Add assertions for the unknown notice/no Retry/list-read recovery and for late discarded settlement after a replacement same-scope attempt.

**Verification.** From PowerShell in `portal/`, `npm test -- src/components/characters/CharacterRevelationsSection.test.tsx src/components/characters/CharacterRevelationsSection.write.test.tsx src/pages/CharacterPublicProfilePage.revelations.test.tsx src/pages/CharacterPublicProfilePage.test.tsx src/hooks/useAuthoringMutation.test.tsx`: 5 files, 145/145 passed. The temporary reset-overlap regression probe failed its pending-state assertion and was restored byte-for-byte. I did not rerun lint/build, the full portal suite, or backend shards; none was needed for this focused confirmation. Preserve the prior full-suite failure and rerun separately as recorded in §11.9. `uv run python scripts/check_documentation.py` and `git diff --check` are recorded after this review entry.

**CI.** `gh run view 44930345138` reports completed success on exact PR head `c4d5856fe4b3e785eeb9b9b9f1ca9e07855150f3`. Completed workflow logs show checkout of `refs/remotes/pull/71/merge` at full SHA `7b013745444355ffaa5d076a8cbe106c005dc0be`, merging the head into base `bf23c7648601eb1b3ad479078f2762fe13fd460b`. This verifies the synthetic merge checkout containing the PR head, not an isolated PR-head checkout. Browser/AT, human, owner and final integrated-head obligations remain pending; PR #71 remains draft and unmerged.

**Carried dispositions.** T01 remains **PASS WITH VERIFICATION LIMITS**; R-S02-1 remains closed; R-S02-5 remains closed for implementation with browser/AT limits; S01's reviewed behavior is unchanged. T02 and combined S02 remain **CHANGES REQUIRED** because R-S02-4 is not fully closed.


### 11.9 Correction of the R-S02-4 pending-attempt race (Sonnet; independent confirmation pending)

**Baseline and range.** Baseline `61bf877874b079aac75d552b9176c8a674f8b06e`. The correction commit and the records head are reported in the report for this task (a record cannot name its own commit). Confirmation range: `61bf877874b079aac75d552b9176c8a674f8b06e..<records head>`. R-S02-4 is marked **corrected, pending independent confirmation**, not passed. R-S02-5's implementation closure, T01's pass with verification limits, the R-S02-1 closure, S01's review and the Section 11.4, 11.6, 11.7 and 11.8 texts are unchanged. Frontend only: no backend, DTO, S01 behavior, S03/S04 or consumer change.

**Cause (Section 11.8).** `discard()` cleared the unresolved attempt and reserved key at loss time but left an in-flight request alone; when that request later failed, `start()` rebuilt the unresolved attempt, and the section's effect discarded it only while `access.manage` was still absent, so a restored manager saw Retry for the old target.

**Correction.** `useAuthoringMutation` numbers every send (`attemptSeqRef`) and records the one in flight with its scope (`inFlightRef`). `discard()` now also marks the in-flight attempt of the current scope as withdrawn (`discardedRef`). When that attempt later fails with a lost answer (network or server error), its body and key are not kept (the reservation is cleared only if it is still that attempt's key, the unresolved attempt only for that scope), no error status is shown (so no Retry and no "something went wrong" text that offers to repeat it), and the hook returns to idle. A definitive refusal still shows as before, and a confirmed answer for a withdrawn attempt is still a confirmed write (its onSuccess and status run as normal). The attempt number is unique to one send, so a late settlement cannot act on a newer attempt or on another scope, and the mark is cleared when that attempt settles. The section calls `discard()` on applied `access.manage` loss for a targeted create that is failed or still pending (it previously did so only after failure), so restoration before settlement cannot undo it. With authority never lost, retries are unchanged (same body, same key). Nothing says the withdrawn attempt was rejected: its outcome stays unknown, the comments and this record say only that it is no longer the form's to repeat, and no message claims the server did or did not apply it.

**Tests added.** Section, the reviewer's sequence: member chosen, POST held, applied loss, restoration, HTTP 500 settles: no Retry and no unknown-outcome message, Reveal enabled, one POST only; the same member and reason chosen again sends the same body under a different `Idempotency-Key`. Hook isolation: a discard during flight leaves the status pending; the later lost answer is idle with nothing retryable; a newer attempt of the same body gets a new key and its own failure is an ordinary error with a same-key Retry; another scope's pending attempt is untouched and still confirms; a discarded attempt that is confirmed is a success with its receipt (two cases).

**Failing before the correction (the two production files reverted, tests kept).** 2 tests failed: the section sequence (Retry present after the 500) and the hook in-flight case. Both are behavioral (`discard()` already existed).

**Verification.** Focused run (section list 8, section write 37, page revelations 15, S01 page 58, hook 27): 145 passed. `npm run lint`, `tsc -b` and `npm run build` passed. Full `npm test`: 435 files, 5415 tests passed on the first run. Documentation and diff checks: see the report for this task. Tests were run in PowerShell. No backend behavior changed, so no backend or shard run was made or claimed.

**Limits.** No browser, zoom, screen-reader or assistive-technology check; no persona, human, `actor-a`, owner or final integrated-head evidence. Member and group targets remain limited to `access.manage` (G-2).


### 11.11 Correction of the R-S02-4 contract gaps (Sonnet; independent confirmation pending)

**Baseline and range.** Baseline `c4d5856fe4b3e785eeb9b9b9f1ca9e07855150f3` (resolved from Git and verified as the full SHA before work began). The correction commit and the records head are reported in the report for this task (a record cannot name its own commit). Confirmation range: `c4d5856fe4b3e785eeb9b9b9f1ca9e07855150f3..<records head>`. R-S02-4 is marked **corrected, pending independent confirmation**, not passed. R-S02-5's closure, T01's pass with verification limits, the R-S02-1 closure, S01's review and Sections 11.4 to 11.10 are unchanged. Frontend only: no backend, DTO, S01 behavior, S03/S04 or consumer change.

**Correction of an earlier claim.** Section 11.9 said the attempt number meant a late settlement could not act on a newer attempt. That was stronger than what was implemented (Section 11.10 reproduced a same-scope `reset()` followed by a replacement send, after which the old failure changed the replacement to idle). The guarantee now implemented is narrower and stated here exactly: one owner attempt (`ownerRef`) holds the visible state. A settlement of any other attempt writes no status, receipt or unresolved attempt; a confirmed one still spends its own key (the reservation is cleared only if it is still that key) and runs its `onSuccess`. Another scope is a different hook instance with its own refs, so there is no cross-scope sharing to guard. The hook comments and `portal-behavior.md` were corrected to match.

**Gap 1 (silent unknown outcome).** A withdrawn attempt (discarded while in flight) whose answer is lost with a network or server error is reported by the hook as `status: error` with `withdrawn: true`; nothing of it is kept (no body, key or retry). The section shows an alert, with no target named: "We could not confirm whether your last reveal was applied. It may have been created. That attempt can't be sent again from this form." It offers **Check current revelations** (an authorized read of the list only, never a create) and **Dismiss**. After a successful read it adds that the list may or may not include the result of that attempt and should be compared before revealing again; after a failed read it says that says nothing about whether the attempt was applied. It claims nothing the contract does not support: the list has no way to tie an entry to that command. A fresh submission is permitted and is a new attempt under a new key; it clears the notice. Ordinary same-key retries (authority never lost), confirmed-write feedback and definitive refusals are unchanged.

**Gap 2 (reset overlap).** Every settlement is guarded by `ownerRef`, as above. After discard, public `reset()` and a replacement send, the older request (failing, failing as withdrawn, or confirmed) leaves the replacement pending, with no old error, receipt or withdrawn flag, until its own response settles it.

**Tests added or changed.** Section (the reviewer's sequence, extended): held targeted POST, applied loss, restoration, HTTP 500: the unknown-outcome alert appears, names no target and claims neither failure nor success, no Retry, one POST; Check current revelations reads the list only; the message after a good read and after a failed read; recovery by a good read; a deliberate reselection sends the same body under a new key. Hook: the in-flight discard case now expects `error` with `withdrawn` true and `withdrawn` false for the newer attempt; a new reset-overlap case covers an older ordinary failure, an older withdrawn failure and an older confirmation, each leaving the replacement pending with no receipt until its own answer; earlier cases for the other scope (untouched) and a confirmed withdrawn attempt (still a success) remain.

**Failing before the correction (the two production files reverted, tests kept).** 3 tests failed: the section sequence, the hook in-flight case and the new reset-overlap case.

**Verification.** Focused run (section list 8, section write 37, page revelations 15, S01 page 58, hook 28): 146 passed. `npm run lint`, `tsc -b` and `npm run build` passed. Because the hook is shared, the full `npm test` was run: the first run failed one unrelated test (`CampaignLayout.contextTransition`, "default A revoked while B becomes the new default…"; its file passes alone, 50/50); the rerun was clean, 435 files and 5416 tests. These are one failed run and one clean rerun, recorded separately. Documentation and diff checks: see the report for this task. Tests were run in PowerShell. No backend behavior changed, so no backend or shard run was made or claimed.

**Limits.** No browser, zoom, screen-reader or assistive-technology check (the alert's announcement is untested beyond its `alert` role); no persona, human, `actor-a`, owner or final integrated-head evidence. Member and group targets remain limited to `access.manage` (G-2).

### 11.12 Independent confirmation of R-S02-4 (Codex, 2026-11-21)

**Boundary and state.** Reviewed `c4d5856fe4b3e785eeb9b9b9f1ca9e07855150f3..055f29bac1984825ad50f49d40ff8cb2c1f43fc9`; code commit `6ebc57737607e2046937e4ebb9ca08fd6039993b`. Base and code are ancestors of the records head. Branch `phase15/completion`; HEAD `055f29bac1984825ad50f49d40ff8cb2c1f43fc9`; worktree clean before this record edit. No applicable `AGENTS.md` was present. §11.10 and §11.11 are retained as review/correction history. No source files were changed in this review.

**Disposition: R-S02-4 remains open; T02 and combined S02 are CHANGES REQUIRED.** The pending-request case is corrected: loss of `access.manage` while targeted create is pending calls `discard`; a later network/500 loss becomes a target-free withdrawn error with no Retry, and a later explicit selection uses a fresh key. Ordinary authorized Retry retains its original key. The new check button calls only the existing revelations-list `refetch`; the tests observe a GET and no extra POST, and both successful and failed reads explicitly say they do not establish the command's result. Dismiss uses `reset`; a subsequent submission creates a new attempt. Hook instance refs isolate unrelated instances. The first attempt to run the focused suite returned only the Vitest startup banner at the 30-second tool window; the separate completed rerun passed, as recorded below.

**R-S02-4a — an already-lost targeted outcome is erased without withdrawn feedback (4/10, Medium; application; blocks V23/R-S02-4).** A supported sequence remains: submit a targeted create while `access.manage` is present; receive a network/5xx error (the hook retains an unresolved body/key and displays the ordinary unknown-outcome Retry); then apply a session refresh that removes `access.manage`. The section calls `discard()` for an error, but `discard()` only marks `inFlightRef`; for an already-settled unresolved attempt it clears the retry refs and changes the snapshot to idle without setting `withdrawn`. The old error/Retry disappears and the new target-free unknown-outcome alert and read-only Check action never appear. A temporary PowerShell/Vitest probe exercised this sequence and failed its expected-alert assertion. The initial probe used a helper local to a different `describe` and stopped with `ReferenceError`; it was restored and rerun with explicit form setup. The behavioral rerun failed because no alert existed. The test file was restored byte-for-byte (SHA-256 before and after: `2741A2CE1CD0C64BD37FF9FD8B9EAA00E7C54676A5B83E141E0A94B9B625C9F3`).

Score factors: exposure 1 (authenticated manager, targeted request has an ambiguous error before the applied capability refresh), impact 1 (the user loses the only warning/read path and may create again with a fresh key without knowing whether the first took effect), triggerability 1 (special but supported session/network ordering), detection/recovery 1 (the warning vanishes with no replacement notice or automatic read), blast radius 0 (one character/attempt). This does not bypass server authority or prove duplicate creation, but it fails the required command-feedback behavior. **Bounded correction:** when discarding an existing unresolved network/server attempt because target authority is withdrawn, clear its body/key while retaining a target-free `withdrawn` unknown-outcome state; render the same no-Retry alert and read-only check as for a pending attempt. Keep definitive refusals and confirmed responses distinct. Add the already-failed → authority-loss regression plus dismissal and fresh-key assertions.

**R-S02-4b — a superseded confirmed callback can still run current form effects (3/10, Low; shared-hook lifecycle; acceptance gap).** `useAuthoringMutation` checks `ownerRef` before publishing an old failure, and checks it after the confirmed callback before publishing status/receipt. However, on confirmation it calls `onSuccessRef.current(result, body)` before checking whether the attempt still owns the current state. The hook test's reset/replacement/old-confirmation case supplies no `onSuccess` callback, so it verifies only status and receipt. In this S02 consumer, `onSuccess` closes the reveal form, clears its reason/target/refusal, sets the created message, re-reads, announces, and schedules focus. If an old confirmation settles after a same-scope reset/replacement, those current component effects can close or clear the replacement form and announce/refocus for the wrong episode even though the hook later preserves the replacement status. The current Revelations UI only exposes Reset/Dismiss after a withdrawn failure has settled, so this reset-while-pending overlap is not a demonstrated ordinary S02 user path; the public hook API and the correction's own reset/replacement tests make it an exercised lifecycle the claimed guarantee must handle. Exposure 1 (caller resets a pending write and starts another in the same hook), impact 1 (bounded replacement form/feedback/focus corruption), triggerability 1 (explicit lifecycle ordering), detection/recovery 0 (visible and recoverable), blast radius 0 (one hook instance). This is not a new unrelated-consumer runtime regression, but the item-6 callback-isolation criterion is not established. **Bounded correction:** make confirmed completion callbacks attempt-aware. A stale confirmed attempt may perform only the necessary read-only reconciliation for its own still-current scope; it must not run current form reset, success announcement, receipt/status, or focus effects. Alternatively split authoritative read-back from owner-only UI effects. Test an old confirmed response after reset/replacement with a stateful callback and assert the replacement's form values/open state, focus, announcement, receipt, retry state and scope remain its own.

**Other requested checks.** The withdrawn pending-error notice is target-free and does not call the server result success/failure. The read-only action uses the same revelations endpoint and the existing page/list read policy; it sends no target data or mutation. The successful-read wording says the list may or may not include the attempt; failed-read wording says it proves nothing. The current tests cover read success/failure and a fresh-key create after a good check, but do not directly click **Dismiss** before the fresh submission; source tracing shows Reset clears `withdrawn`, and the capability-loss render has already cleared the targeted choice, so a deliberate re-selection is required. Same-key authorized retry remains covered by the existing tests. No other production caller invokes `discard()`. The new withdrawn branch therefore does not alter those callers; the shared `ownerRef` guard is exercised by the hook test, but callback side effects are not.

**Before-fix evidence.** §11.11 records three behavioral failures with production changes reverted: the delayed section failure, in-flight hook discard, and reset-overlap state test. Those test existing behavior, not absence of an API. The re-review adds a separate valid behavioral failure for the already-failed-then-capability-loss path; its first helper-scope mistake is not counted as defect evidence. The owner/callback gap is established by the actual invocation order and component side effects; the correction's hook test does not supply a callback.

**Verification.** From PowerShell in `portal/`, `npm test -- src/components/characters/CharacterRevelationsSection.test.tsx src/components/characters/CharacterRevelationsSection.write.test.tsx src/pages/CharacterPublicProfilePage.revelations.test.tsx src/pages/CharacterPublicProfilePage.test.tsx src/hooks/useAuthoringMutation.test.tsx`: 5 files, 146/146 passed on the completed invocation. A first invocation produced only the startup banner at the 30-second tool window; the completed rerun is reported separately and is not a full-suite run. The targeted already-failed outcome probe failed its expected alert assertion and was restored byte-for-byte. I did not rerun lint/build or backend shards. Preserve §11.11's full portal failure (`CampaignLayout.contextTransition`, with the distinct 50/50 file rerun) and separate clean full-suite rerun (435 files, 5416 tests); this review did not repeat either run. `uv run python scripts/check_documentation.py` and `git diff --check` are recorded after this entry.

**CI.** `gh run view 44936832084` reports completed success for exact PR head `055f29bac1984825ad50f49d40ff8cb2c1f43fc9`. Completed workflow logs show checkout of `refs/remotes/pull/71/merge` at full SHA `5b0df92564219f56948146274fe0f1c7f67efbaa`, merging the head into base `bf23c7648601eb1b3ad479078f2762fe13fd460b`. This is CI evidence for the synthetic merge checkout containing the exact PR head, not an isolated PR-head checkout.

**Carried dispositions.** T01 remains **PASS WITH VERIFICATION LIMITS**; R-S02-1 and R-S02-5 remain closed for implementation; S01's reviewed behavior is unchanged. T02 and combined S02 remain **CHANGES REQUIRED** for R-S02-4a and the owner-aware callback criterion in R-S02-4b. Browser/AT, human, owner and final integrated-head obligations remain pending; PR #71 remains draft and unmerged.

### 11.13 Correction of R-S02-4a and R-S02-4b (Sonnet; independent confirmation pending)

**Baseline and range.** Baseline `055f29bac1984825ad50f49d40ff8cb2c1f43fc9` (resolved from Git and verified as the full SHA before work began). The correction commit and the records head are reported in the report for this task (a record cannot name its own commit). Confirmation range: `055f29bac1984825ad50f49d40ff8cb2c1f43fc9..<records head>`. R-S02-4a and R-S02-4b are marked **corrected, pending independent confirmation**, not passed. T01's pass with verification limits, the R-S02-1 and R-S02-5 closures, S01's review and Sections 11.4 to 11.12 are unchanged. Frontend only: no backend, DTO, S01 behavior, S03/S04 or consumer change.

**R-S02-4a (already-failed attempt, then capability loss).** `discard()` now treats an unresolved attempt that has already settled as a network or server error the same way as one that settles later: its body and key are cleared, but the error stays, marked `withdrawn`, instead of becoming idle. The section therefore keeps the target-free "could not confirm" alert and the read-only **Check current revelations**, and shows no Retry, whether authority is lost before the answer arrives (Sections 11.9 and 11.11) or after the failure. Restoration of `access.manage` does not bring Retry back. A definitive refusal has no unresolved attempt and is not turned into an unknown outcome. `discard()` leaves an already withdrawn error as it is. **Dismiss** (`reset`) clears the alert, and a deliberate fresh submission is a new attempt under a new key with no replay of the discarded body.

**R-S02-4b (stale confirmed callback).** Before this correction a confirmed attempt that no longer owned the hook's state still called `onSuccess` before the ownership check. Now such an attempt still spends its own key (the reservation is cleared only if it is still that key), but `onSuccess` is not called. The hook offers an optional `onSupersededSuccess(result, body)` for read-only reconciliation only; it must not touch the current form, announce, or move focus. The section supplies one for create that only re-reads the revelations list. The replacement's form, announcement, focus, receipt, retry state and scope stay its own.

**State transitions inspected.** Pending, ambiguous failure, definitive refusal and confirmation, each against authority loss before and after settlement, reset and replacement, and scope change. Ambiguous failure then loss: withdrawn error (new). Loss then ambiguous failure: withdrawn error (Section 11.11). Definitive refusal then loss: idle, as before. Confirmed in flight then loss: a confirmed write, as before (the owner still runs `onSuccess`). Stale confirmation after replacement: reconciliation only (new). Stale failure after replacement: ignored (Section 11.11). Scope change: a new hook scope and snapshot, unchanged. Revoke is unchanged: it has no `discard` caller and no replacement path in the UI.

**Tests added or changed.** Section: an already-failed targeted create (Retry showing), loss, restoration: the alert stays, no target is named, no Retry, Check performs only a GET, Dismiss, then a fresh submission has the same body under a new `Idempotency-Key`. Hook: discard of an already-failed attempt gives a withdrawn error (the existing discard test was updated from idle), repeated discard changes nothing, there is no retry, `reset` clears it and the next send has a new key; a discarded definitive refusal is not withdrawn; an older confirmation after reset and replacement, with real `onSuccess` and `onSupersededSuccess` callbacks, runs only the reconciliation, leaves the replacement pending with no receipt, and the replacement's own confirmation then runs `onSuccess` once. The existing pending, loss, restoration, failure sequence, authorized same-key Retry and other-scope cases remain and pass.

**Failing before the correction (the two production files reverted, tests kept).** 4 tests failed: the section already-failed sequence, the stale confirmation callback case, the new already-failed discard case and the updated discard test.

**Verification.** Focused run (section list 8, section write 38, page revelations 15, S01 page 58, hook 31): 150 passed. `npm run lint`, `tsc -b` and `npm run build` passed. Because the hook is shared, the full `npm test` was run several times: two runs each failed one unrelated test in `App.knowledgeMemberPreview.test.tsx` ("Tom can see this."; that file passes alone, 39/39, four times, once with this correction stashed); one further run was not read for failures; the last run was clean: 435 files, 5420 tests. These are recorded as failed runs and a separate clean rerun. Tests were run in PowerShell. No backend behavior changed, so no backend or shard run was made or claimed.

**Limits.** No browser, zoom, screen-reader or assistive-technology check (the alert's announcement is untested beyond its `alert` role); no persona, human, `actor-a`, owner or final integrated-head evidence. The stale-confirmation path is a hook lifecycle guarantee, not a path the current Revelations UI exposes. Member and group targets remain limited to `access.manage` (G-2).

### 11.14 Independent confirmation of R-S02-4a and R-S02-4b (Codex, 2026-11-21)

**Boundary and state.** Reviewed `055f29bac1984825ad50f49d40ff8cb2c1f43fc9..fe888424e3bfd430f90a7f8e83a33de26db4e249`; code commit `50ca57745943c0656328f3138fd14b2e59b0471b`. The base and code are ancestors of the records head. Branch `phase15/completion`; HEAD `fe888424e3bfd430f90a7f8e83a33de26db4e249`; worktree was clean before this entry. No applicable `AGENTS.md` was present. The review inspected the original findings in §11.12, correction evidence in §11.13, V23, the hook, the revelations section, its resource read, and shared hook call sites. No production files were changed.

**Disposition: R-S02-4a and R-S02-4b are resolved; T02 and combined S02 are PASS WITH VERIFICATION LIMITS.** The earlier findings and all historical run records remain intact. T01 remains PASS WITH VERIFICATION LIMITS; R-S02-1 and R-S02-5 remain closed; S01 is unaffected.

**R-S02-4a — resolved.** `discard()` now distinguishes an already-failed unresolved network/server attempt from a definitive refusal: it removes the body and reserved key, retains the unknown-outcome error as `withdrawn`, and makes `retry()` a no-op. The section renders the target-free unknown-outcome alert and read-only Check action. Restoring `access.manage` does not recover Retry or the old target. The regression test covers ambiguous failure → capability loss → restoration, confirms Check performs a GET without another POST, then Dismiss and deliberate reselection submit the same body under a different key. The earlier pending-loss-restoration-failure coverage remains. Definitive refusal remains a known error, and ordinary authorized retry still uses the same unresolved body/key. The transition behavior agrees with V23: no replay after authority withdrawal, truthful unknown outcome, and a fresh key for a deliberate new attempt.

**R-S02-4b — resolved for the supported S02 lifecycle.** A confirmed attempt whose number no longer owns hook state spends its own reservation and returns before invoking `onSuccess`; it therefore cannot perform that callback's form clearing, success announcement, focus scheduling, or receipt/status publication. The only production `onSupersededSuccess` caller is `CharacterRevelationsSection`, and its callback only calls the existing revelations-list `refetch()`. That read applies to the section's current path through `useAuthoringResource`, whose later read supersedes/aborts an earlier one. Campaign/character navigation remounts `PublicProfile` with a campaign/character key; the old section's mutation controller is aborted on unmount, and the new section has independent hook state and a new resource path. Thus the actual callback cannot be selected from or reconcile into another character's current section. The hook regression verifies an old confirmation after reset/replacement invokes no `onSuccess`, invokes only the reconciliation callback, leaves the replacement pending with no receipt, and lets the replacement's own confirmation run `onSuccess` once.

The optional callback's read-only nature is a documented caller contract, not enforced by TypeScript. The actual sole caller satisfies it. Other shared-hook callers do not supply it and none uses `discard()`; the new option is source-compatible and the withdrawn-error behavior is confined to `discard()`. Superseded old confirmations intentionally no longer run owner UI effects for any hook consumer. Existing consumer reset/cancel controls are tied to their own reset/replacement workflows; no additional production consumer or behavior change was found in the inspected call sites. This correction does not change server requests, authorization, or revoke behavior.

**Before-fix evidence.** §11.13 reports four behavioral failures with the two production files reverted: the section's already-failed sequence, the stale-confirmation callback assertion, the already-failed discard hook case, and the updated discard case. These cover behavior, not merely API presence. The present review inspected those tests and the transition analysis. No additional mutation probe was needed to establish the corrected transitions.

**Verification.** From PowerShell in `portal/`, the focused command `npm test -- src/hooks/useAuthoringMutation.test.tsx src/components/characters/CharacterRevelationsSection.test.tsx src/components/characters/CharacterRevelationsSection.write.test.tsx src/pages/CharacterPublicProfilePage.revelations.test.tsx src/pages/CharacterPublicProfilePage.test.tsx` passed: 5 files, 150/150 tests. This independently covers the hook, S02 section/page and S01 page behavior. Lint, typecheck and build are implementer-reported in §11.13, not rerun here. No backend behavior changed; backend shards were not repeated.

The previously unread full-suite run from §11.13 has no retained test output available in the workspace artifacts inspected for this review, so its result remains **unknown**; it is not counted as a pass. Preserve separately the two full-suite runs that failed in `App.knowledgeMemberPreview.test.tsx`, the isolated 39/39 reruns, that unread run, and the later clean 435-file/5420-test run. None is substituted for the focused review run.

**CI.** `gh run view 44946172550` reports completed success for exact PR head `fe888424e3bfd430f90a7f8e83a33de26db4e249`. Completed workflow logs show checkout of `refs/remotes/pull/71/merge` at full synthetic merge SHA `0c5d6ece2117f28ab7b70cdd9b491511c2ddb2e1`, merging the reviewed head into base `bf23c7648601eb1b3ad479078f2762fe13fd460b`. This is successful CI for the synthetic merge checkout containing the exact PR head, not an isolated-head checkout.

**Limits and carried obligations.** No browser, zoom, screen-reader or assistive-technology verification was performed; the target-free alert is covered by role/content tests, not actual screen-reader announcement evidence. Human, persona, `actor-a`, owner acceptance, and final integrated-head browser/AX obligations remain pending. PR #71 remains draft and unmerged. The clean full-suite rerun is implementer evidence; the unread run remains unknown.
