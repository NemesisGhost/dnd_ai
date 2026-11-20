# D/P15-C01-S02 implementation plan: explain effective access

**Status:** Opus plan prepared 2026-11-19; T01 implemented 2026-11-19, Luna review pending (see the [implementation record](#113-implementation-record)). Work-register row: [D/P15-C01-S02](work-register.md#p15-c01-s02), task [T01](work-register.md#p15-c01-s02-t01). Parent PR: [D/P15-C01](work-register.md#p15-c01).

**Baseline.** Read at `cdfdf21b8efa91172372906bd676cfb2636d5c4c` ("P15-C01-S01: validate workspace breadcrumb names") on `phase15/completion`. The working tree held only Luna's uncommitted S01 final review record ([S01 plan §11.8](p15-c01-s01-public-tier-plan.md#118-l-1-final-independent-review-luna-2026-11-19)) and its register status cells. Both are preserved. While this plan was being written, those two edits were committed outside this session as `d6615b93d1aaa0e7fba8b08f84c224df178e6e41` ("docs: record P15-C01-S01 final review"). That commit is documentation only, so the implementation head the plan was read against is still `cdfdf21`. No repository-path `AGENTS.md` exists.

**What establishes each statement.** Source reading at that baseline. No probe was run, and no application, test, schema or backend file changed. Statements marked "by reading" were not executed.

**Contract sources.** [ACCESS_CONTROL §3q](../api/ACCESS_CONTROL.md#3q-effective-access-explanation-delivered-checkpoint-13) (the explanation, including its revelation paragraph), the A3b record in [shared-characters](shared-characters.md#a3b-implementation-record-2026-11-09) ("The portal does not render either yet (A6)"), the A6 row of that design's slice table, [portal behavior §8.3 and §9](../reference/portal-behavior.md#83-effective-access-explanation), the [S01 plan](p15-c01-s01-public-tier-plan.md) and the [grading rubric](grading.md).

---

## 1. Verified current behavior

### 1.1 Which audience receives source information

| Caller | What the backend exposes about *why* | Where |
|---|---|---|
| `access.manage` holder (campaign owner; any custom role holding it) | Every capability a selected member holds, each with its sources: `role`, `character_relationship`, `resource_grant`, `access_group`, `revelation`. It also lists active denials. A source is `{kind, label, target_display_name}`. | `GET /campaigns/{id}/members/{membership_id}/effective-access` (`api/access_overview.py`, `queries/effective_access.py`) |
| Same | Per member: `roles`, `character_relationships`, `grants` (allow and deny), and since A3b **`revelations`** `[{character_id, character_display_name, audience_kind_code, audience_kind_display_name}]` | `GET /campaigns/{id}/access-overview` (`RevelationSummaryResponse`) |
| Any other member (player, observer) | **No source information.** The character read gives only `view_tier` and `sections`. The bootstrap gives campaign-wide `roles`, `capabilities` and `character_perspectives`. None of these says which source grants a tier for a given character. | `GET /campaigns/{id}/characters/{id}`, `GET /auth/session` |

Properties of the explanation, by reading the resolver:

- It applies the same "currently true" filters as `resolve_access_context`, so it never lists a source the resolver would not honour. Revelations come from `LIVE_REVELATIONS_FOR_MEMBERSHIP_SQL`, the resolver's own query.
- A revelation is listed under both `character.discover` and `character.view_public_profile`. Its `label` is the audience-kind display name (`Member`, `Access group`, `Campaign, current members`, `Campaign, current and future members`), and `target_display_name` is the character's canonical name. It never carries the revelation id, reason, creator, group name or other audience. Two revelations are two entries.
- Characters are identified **only by canonical name**. The explanation carries no `character_id`.
- Denials are separate (`capability_code`, `target_type`, `target_display_name`). A source is still listed when a deny overrides it for one target.
- An unknown or ended membership, or a caller without `access.manage`, gets the same non-disclosing 404 or 403.

### 1.2 The portal at the baseline

| File | Behavior |
|---|---|
| [`types/effectiveAccess.ts`](../../portal/src/types/effectiveAccess.ts) | Mirrors the explanation DTO. The `kind` comment omits `"revelation"`. |
| [`components/EffectiveAccessPanel.tsx`](../../portal/src/components/EffectiveAccessPanel.tsx) | `SOURCE_KIND_LABELS` maps four kinds and has no `revelation` entry. By reading, a revelation therefore renders through the `humanizeCode` fallback as "Revelation: Access group (Mira)", which works by accident rather than by contract. Each row's disclosure owns its own `isOpen` state, and `EffectiveAccessContent` mounts (and fetches) only while that row is open. Denials render the raw `capability_code`. |
| [`hooks/useEffectiveAccess.ts`](../../portal/src/hooks/useEffectiveAccess.ts) | Snapshot keyed on campaign, membership and request version. Superseded or aborted answers are ignored, 401 triggers session `reload()`, 403/404 becomes `unavailable`, and anything else becomes a retryable `error`. `no-store`. |
| [`types/accessOverview.ts`](../../portal/src/types/accessOverview.ts) `CampaignAccessMember` | **No `revelations` field.** `api/accessOverview.ts` casts the JSON, so the server's `revelations` arrive but are never typed or rendered. |
| [`pages/AccessPage.tsx`](../../portal/src/pages/AccessPage.tsx) | Each member card has Roles, Character access, Direct resource access (deny grants included, with display names), then `EffectiveAccessPanel`. Nothing about revelations. |
| [`pages/CampaignAccessPage.tsx`](../../portal/src/pages/CampaignAccessPage.tsx), [`hooks/useAccessOverview.ts`](../../portal/src/hooks/useAccessOverview.ts), `AccessOverviewBoundary` | Every mutation's `onChanged` sets the campaign-scoped live-region announcement and calls the overview `retry()`. The retry moves the boundary to `loading` (no retained overview), which unmounts `AccessPage`, so **every open explanation closes and its data is dropped**. Reopening re-fetches. There is no refresh control in the success state. |
| [`components/CharactersBrowser.tsx`](../../portal/src/components/CharactersBrowser.tsx), [`hooks/useWorldEntities.ts`](../../portal/src/hooks/useWorldEntities.ts) | The player list. Its state is per mount: returning from a detail page remounts and re-reads. A same-campaign filter or page change shows the previous page as `refreshing`, which is the same caller's last authorized answer. A campaign change clears it. Card `summary` is the server's D5-c projection. |
| S01 surfaces (`CharacterBoundary`, `CharacterDetailPage`, `CharacterSheetRoutePage`, `WorldRecordWorkspace`) | Tier-only wording: "Only this character's public profile is available to you." at the public tier and "The full sheet is not available to you." at summary. **No source wording anywhere on player surfaces** (`grep` for "Revelation", "revealed", "shared with you" in `portal/src/pages` and `components/characters` finds none outside the Access and authoring code). |

### 1.3 Reconciliation as it stands

- **Access page, a change made on the page.** The list and every explanation are consistent afterwards, because each open explanation is unmounted and must be reopened. Reopening is a fresh read. Nothing stale can be shown, but the explanation the GM was looking at closes on every change.
- **Access page, a change made elsewhere** (the HTTP API, which is the only revelation writer until [D/P15-C02-S02](work-register.md#p15-c02-s02), or another tab). Explanations opened afterwards are newer than the member list above them, so they can disagree, for example a list showing a relationship the explanation no longer cites. The page offers only a full browser reload to bring the list current.
- **Player list and detail.** Each read stands alone. A detail read after revocation shows S01's tier or the non-disclosing unavailable page. Back remounts the list and re-reads it. No polling or push exists, and none is introduced.

### 1.4 Transitions (verified by reading, unchanged by this slice)

- `RouteSessionProvider` remounts per campaign.
- `CampaignLayout` keys the outlet on campaign and selected perspective, so the Access page and every hook under it remount.
- A 401 reloads the session.
- Both access hooks drop superseded and aborted answers.
- Losing `access.manage` turns the next overview read into 403, so the boundary shows `unavailable` and no member or explanation content remains.

### 1.5 Contract gaps (exact)

- **G-1. No caller-scoped explanation for a non-`access.manage` caller.** No route tells a player which source admits them to a character. The only signal is the tier, and the client must not infer a source from it: the public tier means "revelation only" today, but that is a resolver rule the client would be recreating. Under the boundaries for this slice, nothing about sources is shown to such a caller. *Smallest disposition:* record it as a follow-up candidate, not part of D/P15-C01. If the owner wants it, it needs its own backend design first: a caller-scoped read filtered under §8.3 ("must not reveal a hidden intermediary"), deciding whether a player may see a grant's free-text `reason`, a group's name, or an audience kind. No DTO field is proposed here.
- **G-2. Explanation sources name characters, not ids.** The client cannot reliably match an explanation source to an overview row (duplicate canonical names are possible). *Disposition:* no backend change. S02 does not correlate the two reads. It keeps them consistent by refreshing them together (§2), not by matching.

Neither gap blocks the supported outcome in §2.

### 1.6 Inherited observations (not new slice obligations)

- **O-1.** Explanation denials render the raw `capability_code`, and a whole-character deny shows `target_type` `entity` ("campaign.view — Entity (Mira)"). Deny display and reconciliation belong to [D/P15-C02-S04-T02](work-register.md#p15-c02-s04). Informational (0) and left unchanged here.
- **O-2.** The overview and explanation name characters regardless of the access manager's own character denies (for example a self-deny). This is existing backend behavior of the administrative audience, which already enumerates every assignable character. S02 adds no new name source: the overview's `revelations` names are the same canonical names that `assignable_characters` already carries. Informational (0); S04's self-deny cases are the place to revisit it.
- **O-3.** After any overview reload, keyboard focus is not returned to the control that triggered it. This is existing behavior for every Access mutation; the live-region announcement is the existing mitigation. It is recorded for [ax](work-register.md#ax). S02 adds no new focus mechanism (§11.1 rule).
- **O-4.** The disclosure heading "Why {member} can see this" does not change when a denial is listed. It is existing copy, unchanged here.

## 2. Supported outcome

After T01:

1. **Revelation sources are explained by contract.** The explanation labels `revelation` sources explicitly ("Revelation"), alongside the four existing kinds. Each source renders as `<kind label>: <label> (<target_display_name>)`, with no other field. An unknown future kind still renders through the humanized fallback.
2. **The member list shows revealed characters.** Each member card gains a read-only **Revealed characters** section listing `character_display_name — audience_kind_display_name` per entry, in server order. Duplicates are not merged and the section has no controls. It renders no `character_id` or audience-kind code. When the list is empty it shows "No revealed characters."
3. **List and explanation refresh together.** An open explanation is never older than the member list it sits in:
   - The open/closed state of each member's explanation is held above the overview boundary, scoped to the campaign, so it survives an overview reload.
   - Every overview reload, whether from a mutation on the page or from the new **Refresh access** control, unmounts each open explanation during `loading` and remounts it after the new overview succeeds. That forces a fresh explanation read.
   - An explanation whose member is absent from the new overview is not rendered, and its open state is pruned.
   - A campaign change or a perspective remount starts with every explanation closed.
4. **Independent sources survive visibly.** When one source is revoked and another still admits the member, the refreshed list and the refreshed explanation both show the survivor and neither shows the revoked source.
5. **Player surfaces stay source-free.** No player page renders any source kind, label or count, at any tier or across tier changes. S01's tier wording and normalized rendering are unchanged.

## 3. Scope, exclusions and prerequisites

**Prerequisites (met at baseline).**

- D/P15-C01 entry criteria: [a4](work-register.md#a4) merged and [r01](work-register.md#r01) owner accepted.
- No additional slice gate.
- S01 passed independent review at `cdfdf21`, and S02 builds on that head. S02 does not depend on S01's unfinished browser, ax or owner obligations.
- [a5c](work-register.md#a5c) is a separate review-only obligation and does not gate S02.

**In scope (T01, `portal/` and `docs/` only).** These are listed in §4.

**Excluded (owner in parentheses).**

- Revelation list, create and revoke controls ([D/P15-C02-S02](work-register.md#p15-c02-s02)).
- Reveal delegation ([S03](work-register.md#p15-c02-s03)).
- Deny management and deny display wording, O-1 ([S04](work-register.md#p15-c02-s04)).
- The copy UI ([copy-ui](work-register.md#copy-ui)), the audience preview ([preview](work-register.md#preview)) and any player-profile editing ([profile-authority](work-register.md#profile-authority)).
- Any player-facing source explanation (G-1).
- Polling, push, focus-restoration machinery (O-3), and any backend, schema, OpenAPI or Foundry change.
- Links from revealed-character entries to the character.

**Stop rule.** If the overview or explanation response at the base does not match §1.1, Sonnet stops and reports the request, the exact body and the blocked outcome, without changing backend code. Mismatches include absent `revelations` and a different revelation label shape.

## 4. Affected files and interfaces

**Types.**

- `portal/src/types/accessOverview.ts`: add `AccessRevelationSummary {character_id, character_display_name, audience_kind_code, audience_kind_display_name}` and `revelations?: AccessRevelationSummary[]` on `CampaignAccessMember`.
  - It is optional only so that existing fixtures compile. The A3b server always sends it, and an absent value renders as empty.
  - `character_id` and `audience_kind_code` are typed for keys only, never as text, following the file's existing `target_id`/`user_id` comments.
- `portal/src/types/effectiveAccess.ts`: add `"revelation"` to the `kind` comment.

**Rendering.**

- `components/EffectiveAccessPanel.tsx`:
  - `SOURCE_KIND_LABELS.revelation = "Revelation"`.
  - The panel becomes **controlled**: `isOpen` and `onToggle` props replace the local state. The unmount-on-close data rule is kept.
  - Inside the open content's success state there is a **Refresh access** button, which calls a new `onRefresh` prop. The button is absent in the loading, unavailable and error states; the error state keeps its existing Retry, which re-reads the explanation only.
- `pages/AccessPage.tsx`:
  - A **Revealed characters** `h3` section after Direct resource access, with no controls.
  - It passes the open state and `onToggle` from props into `EffectiveAccessPanel`.
  - It wires `onRefresh` to `onChanged("Access information refreshed.")`, the existing announcement-and-retry path.
- `pages/CampaignAccessPage.tsx`:
  - Owns `openExplanations: {campaignId, ids: ReadonlySet<string>}`, derived as empty when the campaign does not match. This is the same scoping pattern as `announcement`.
  - Passes it down, and prunes ids absent from the latest overview on each successful render (derived, not by effect, where practical).

**Documentation in the same commit.**

- `docs/api/ACCESS_CONTROL.md` §3q "Portal:" paragraph:
  - revelation sources are labelled "Revelation";
  - the overview's `revelations` render as a read-only **Revealed characters** list;
  - open explanations survive an overview reload by re-reading, and **Refresh access** reloads both.
  - It also states that a non-`access.manage` caller receives no source information (G-1).
- `docs/reference/portal-behavior.md` §8.3, one short paragraph:
  - the delivered explanation surface is the access manager's;
  - players see tier wording only;
  - list and explanation are refreshed together on the next request, with no live updates.
- This plan's implementation record (§11.3).

**Test files.**

- Extend `components/EffectiveAccessPanel.test.tsx`, `pages/AccessPage.test.tsx`, `pages/CampaignAccessPage.test.tsx` and `api/accessOverview.test.ts` (only if fixtures there need the field).
- Add `pages/CampaignAccessPage.effectiveAccess.integration.test.tsx` for the reconciliation cases.
- Add the player-side cases to `App.characterRecord.test.tsx`.
- Existing assertions may change only where a test drove the panel's former local state, or where a fixture gains `revelations`. Report any other changed existing assertion as a finding.

## 5. Task commits

The adopted sizing is kept: **one task commit, T01**, "Render authorized source labels and reconcile list/detail after revocation".

The label, the list section and the refresh-together rule are one reviewable behavior. Splitting the controlled panel from the refresh wiring would leave a commit in which an overview reload either loses or retains explanations inconsistently. Splitting labels from reconciliation would leave the revelation list visible with no proof that it agrees with the explanation after revocation.

## 6. Acceptance cases

Mocked servers return exact §1.1 shapes. Each case checks both the DOM and the request log. "Markers" are distinctive values in keys the DTO does not define (`character_revelation_id`, `reason`, `created_by`, `group_name`), placed in an otherwise valid body.

| # | Case | Expected |
|---|---|---|
| E1 | Explanation with revelation sources (two revelations of different kinds for Mira) | Under both conferred capabilities: "Revelation: Access group (Mira)" and "Revelation: Member (Mira)" as two entries each. The label comes from `SOURCE_KIND_LABELS`: removing the fallback must not change the text (unit) |
| E2 | Unknown future kind `"future_source"` | Renders "Future Source: …" without throwing |
| E3 | Marker keys in explanation sources and overview revelations | No marker renders. No `character_id` or `audience_kind_code` text renders |
| E4 | Overview member with revelations / with `[]` / with the key absent | List shows `Mira — Access group` entries in server order, with duplicates kept / "No revealed characters." / same as `[]`. No button or link inside the section |
| E5 | **Independent-source survival, change made on the page.** Mira holds a viewer relationship and an access-group revelation, and her explanation is open. Revoke the relationship through the existing control | One revoke request, then overview GET, then explanation GET, which is issued only after the overview succeeds. Afterwards: Character access no longer lists Mira; Revealed characters still lists Mira; the reopened explanation shows only Revelation sources for Mira; "Character access removed." is announced; the disclosure is still open |
| E6 | **Independent-source survival, change made elsewhere.** Mira has a relationship and a revelation; the server state changes so the revelation is revoked; Refresh access | Overview and explanation re-read in that order. Revealed characters is empty, the relationship remains in both, and "Access information refreshed." is announced |
| E7 | Last source revoked | No Mira entry in either read. If the member then holds no capability, the existing "holds no capability" text shows |
| E8 | Revelation plus a whole-character deny on the same member | Explanation shows the revelation sources and the existing denial line. Overview shows the deny under Direct resource access. No new wording (O-1, O-4) |
| E9 | Stale content during reload | While the overview is `loading` after a mutation or a refresh, no explanation text or source label from before is in the DOM |
| E10 | Superseded explanation read: the explanation GET from before a refresh resolves after the refresh's reads | Its answer never renders |
| E11 | Member removed elsewhere, then Refresh access | The card is gone and no explanation renders for it. Opening another member's explanation works normally, and the pruned id does not reopen if the member reappears in a later read |
| E12 | Caller loses `access.manage` (overview 403 on refresh) | The existing unavailable presentation shows, with no member, revelation or explanation content |
| E13 | 401 on overview or explanation | Session reload is invoked and no access content renders |
| E14 | Campaign change with explanations open | The new campaign shows every explanation closed, and no explanation GET is sent for it until one is opened |
| E15 | Multiple rows open | Each row's explanation is independent. Closing one unmounts only that one, and its content leaves the DOM |
| E16 | **Player non-disclosure across tiers.** A revelation-only player goes public → summary (grant added) → public (grant revoked) → unavailable (revelation revoked), using Try again between reads | Each read renders S01's tier only. No "Revelation", "Access group", "Member", "shared", "revealed" or source count text appears at any step. No request goes to `/effective-access` or `/access-overview` |
| E17 | **Player list/detail after revocation.** List shows Mira (revealed). Open Mira; the revelation is revoked server-side; Try again; then Back | Detail shows the non-disclosing unavailable page with the breadcrumb label dropped. Back re-reads the list, and the card is absent from the new answer. The list's URL state is kept |
| E18 | Player list card after a tier change (D5-c) | After a grant is added, a fresh list read shows the server's live summary on the card; after it is revoked, the released summary. The client never chooses which |
| E19 | Existing Access and character suites | Pass, with changes only as allowed in §4 |

## 7. Verification

**Automated, required for the T01 commit.**

- From `portal/` in PowerShell (Vitest does not run from Git Bash here, per S01): `npm test`, `npm run lint`, `npm run build`.
- From the root: `uv run python scripts/check_documentation.py` and `git diff --check`.

No backend file changes, so `ruff`, `mypy`, `alembic check` and the shard runner are not required. A change outside `portal/` and `docs/` is out of scope: stop and report.

Report first runs and reruns separately. Record focused files, total counts and any flaky rerun with its output. Include **one mutation probe**: make `CampaignAccessPage` stop carrying open state across reload, or render the explanation before the overview succeeds. E5 or E9 must fail. Restore the file and record SHA-256 before and after.

**Proportionality.** `tests/database/test_api_effective_access.py`, `test_api_access_overview.py` and the A3b revelation-discovery suite already prove which sources exist and when they disappear. The portal tests prove only that each answer is rendered as itself, that the two reads are refreshed together, and that player surfaces stay source-free. They do not re-derive authorization.

## 8. Browser, accessibility and owner obligations (separate events)

None of these is claimed by T01 or its review.

1. **[browser](work-register.md#browser)** at the integrated head, on namespaced throwaway fixtures with ports 8001/5174, never the owner's servers or campaign. Revelations and grants are created and revoked through the HTTP API.
   - **GM persona:** E5 through the UI; E6 by revoking a revelation through the API, then Refresh access; E8 with a whole-character deny.
   - **Player persona:** E16 and E17 with hard refreshes.
   - Record status codes, network order (overview before explanation) and rendered text.
2. **[ax](work-register.md#ax).**
   - `aria-expanded` is correct after a reload.
   - The Revealed characters `h3` is in reading order.
   - Announcements are spoken for both a mutation and Refresh access.
   - Record O-3 focus behavior after reload as observed.
   - Narrow viewport and zoom reflow of the new section.
3. **Owner.** Scoped acceptance stays at [actor-a](work-register.md#actor-a), after D/P15-C01 and D/P15-C02 merge.

## 9. Intermediate states and read recovery

- **One commit, so there is no intermediate repository state.** Before T01, the overview's `revelations` are unrendered and every explanation closes on reload. After T01 both are rendered and kept consistent.
- **No writes are added.** Refresh access is a read. Existing mutations are unchanged, so no idempotency concern arises.
- **Read recovery.**
  - An explanation error keeps its existing Retry, which re-reads the explanation only.
  - An overview error keeps the boundary's existing retry.
  - Neither retains content from an earlier read.
  - The window between the overview read and the explanation read is accepted under the "next request" contract and is not reconciled further (G-2).

## 10. Decisions

None blocks Sonnet if the recommendation is taken. D-1 is the one the owner should explicitly confirm.

- **D-1. Audience of "explain effective access."** The backend explains sources only to `access.manage` holders (§1.1).
  - *Recommendation:* S02 delivers the access manager's explanation (revelation labels, revealed-characters list, refresh-together). Player surfaces keep S01's tier wording and show no sources.
  - The player-self explanation is recorded as gap G-1 and goes to a follow-up candidate outside D/P15-C01.
  - Choosing otherwise requires a backend design and a new register item, not a change to this slice.
- **D-2. Reconciliation mechanism.**
  - *Recommendation:* hold open state above the overview boundary, and add one **Refresh access** read control routed through the existing announcement-and-retry path.
  - *Alternative:* keep today's close-on-reload behavior and add no refresh. That is also never stale, but it cannot show survival without a manual reopen, and it leaves out-of-page changes reconcilable only by a full browser reload.
- **D-3. Copy.** *Recommendation:*
  - section **Revealed characters**;
  - entry `Mira — Access group`;
  - empty text "No revealed characters.";
  - source kind **Revelation**;
  - control **Refresh access**;
  - announcement "Access information refreshed."

  All of this is copy only and reversible.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Start on `phase15/completion` at the commit that records this plan. Record that SHA as the base and record `git status --short`. Preserve unrelated work.
2. Re-check §1.1 and §1.2 against the source at the base (the DTOs in `api/access_overview.py`, the four portal files). If an assumption fails, stop and report.
3. Implement §4 as one commit, in this order:
   1. types;
   2. the panel label and controlled props, with tests E1–E3 and E15;
   3. the Revealed characters section (E4);
   4. lifted open state and Refresh access (E5–E14);
   5. player cases E16–E18;
   6. the two doc paragraphs.
4. **Rules.**
   - Never render a field outside `kind`, `label` and `target_display_name` for a source, or outside the two display names for a revelation entry.
   - Never derive, infer or count sources on a player surface.
   - Never correlate explanation sources with overview rows.
   - Never keep explanation content mounted while the overview is loading.
   - Add no polling, timers, push, focus machinery, links or controls beyond Refresh access.
   - Do not touch S01's normalizer, tier rendering or breadcrumb publishers.
   - Do not change backend, Foundry or migration files.
   - Use existing class names and components. Add no CSS unless a reflow defect requires it.
5. Run §7, keeping first runs and reruns separate. Commit as `P15-C01-S02-T01: explain revelation sources and refresh access together`, followed by the attribution lines. Do not push.
6. Append to §11.3: the base SHA, the T01 head (read with `git log --grep`), the commands with results and counts, the mutation probe, any deviation from §4 with its reason, and any changed existing assertion. Update the S02 and T01 register status cells to "Implemented; Luna review pending".

### 11.2 Luna independent review

- **Boundary.** Base = the commit that records this plan (the parent of T01). Head = T01, or the last correcting commit. Review the whole range.
- **Required evidence.**
  1. Confirm the new types equal `RevelationSummaryResponse` and `EffectiveAccessSourceResponse` at the head, and that no other field is rendered.
  2. Confirm by reading that no player surface renders a source and that no player route requests `/effective-access` or `/access-overview`.
  3. Confirm that an explanation never renders while the overview is loading, and that its GET follows the overview's success.
  4. Run `npm test`, `npm run lint`, `npm run build`, the doc check and `git diff --check`, reporting first runs and reruns separately.
  5. Map E1–E19 to tests, with at least one independent mutation probe (for example, keep explanations mounted during loading, or drop the `revelation` label entry while asserting the exact text). Restore it and record SHA-256.
  6. Check that the §3 exclusions were not entered, and that S01 files changed only where §4 names them.
- **Verdict.** Use the [rubric](grading.md#severity-and-checkpoint-disposition), grading each finding separately. Distinguish new findings from O-1 to O-4 and G-1/G-2, which are inherited or recorded here. §8 events are not part of this verdict.

### 11.3 Implementation record

Recorded by Sonnet, 2026-11-19. Real-browser, accessibility, integrated-head CI, checkpoint-merge and owner events (§8) are not claimed here.

**Base, plan commit and head.**

- Pre-implementation base: `d6615b93d1aaa0e7fba8b08f84c224df178e6e41` ("docs: record P15-C01-S01 final review"), on `phase15/completion`. S01's reviewed production head is `cdfdf21`; `d6615b9` is documentation only. Before work, `git status --short` showed only this plan (untracked) and the register edits (modified). Both were preserved and are in the T01 commit. No `AGENTS.md`.
- **This plan had no commit of its own.** It is committed together with T01 in one commit titled `P15-C01-S02-T01: explain revelation sources and refresh access together`; read it with `git log --oneline -1 --grep "P15-C01-S02-T01"`. Its SHA is not written inside itself and is reported in the handoff. There is no separate plan commit.
- **Luna review range:** base `d6615b93d1aaa0e7fba8b08f84c224df178e6e41`, head = the T01 commit (or the last correcting commit). That range contains the plan, the register changes and the implementation. Nothing was pushed.

**Source assumptions (§1, stop rule).** Re-read at the base: `RevelationSummaryResponse` (`character_id`, `character_display_name`, `audience_kind_code`, `audience_kind_display_name`) and `EffectiveAccessSourceResponse` (`kind`, `label`, `target_display_name`) in `src/dnd_ai/api/access_overview.py` equal the portal types; the overview carries `revelations` for every member. The stop rule was not triggered. Scope choices were taken as the plan recommends: the explanation is shown to `access.manage` holders only (not equated with the GM role), "Revealed characters", "Revelation" and "Refresh access". G-1 and G-2 keep their dispositions; no backend change.

**What was implemented (`portal/` and `docs/` only).**

- Types: `AccessRevelationSummary`; `revelations?` on `CampaignAccessMember` (optional only for older fixtures; absent renders as none); the `kind` comment names `revelation`.
- `EffectiveAccessPanel`: `SOURCE_KIND_LABELS.revelation = "Revelation"`; the panel is controlled (`isOpen`, `onToggle`, `onRefresh`) and exposes `data-explain-toggle={membershipId}`; a **Refresh access** button appears only beside a loaded explanation (not in loading, unavailable or error; error keeps Retry, which re-reads only the explanation).
- `AccessPage`: a read-only **Revealed characters** section (`Mira — Access group`, server order, duplicates kept, no control, no id or code; "No revealed characters." when empty or absent). Member cards are controlled `<details>` so an expanded card survives a reload (see deviation 2).
- New `hooks/useAccessDisclosure.ts`: open cards and open explanations held as sets of membership ids, scoped to the campaign (another campaign reads as empty); only ids, never access data.
- `CampaignAccessPage`: owns the disclosure above the boundary; `OverviewSettled`, rendered only inside a successful overview, prunes ids absent from the new list and confirms a pending refresh; `handleRefreshAccess` and `handleRefreshSettled`.
- Docs: ACCESS_CONTROL §3q "Portal (P15-C01-S02)" paragraph (including G-1), portal-behavior §8.3 paragraph, the register rows, and this record.

**How refresh correctness is met (by construction, then by test).**

- A reload moves the boundary to `loading`, which unmounts every explanation (`EffectiveAccessContent`); its fetch is aborted by the existing hook cleanup. An explanation can therefore never be older than the list beside it, and each open explanation is read again only after the list read succeeded (E5, E6, E9 assert the request order).
- Superseded and aborted answers are dropped by the existing hooks (`controller.signal.aborted`, request-version snapshot). A late answer from before a reload (E10) and a late answer for an explanation that was closed (E15) never render.
- No old content is retained anywhere, so no stale-state notice is needed: while the list loads the page says "Loading access"; a failed list shows the boundary's error or unavailable page with no member, revelation or explanation content (E12, E13).
- **Refresh is announced only after the list has been read again.** `Access list refreshed.` is set when the overview succeeds, not when the button is pressed, so a failed list read is never announced as refreshed. An explanation that then fails shows its own error with Retry and nothing from before; the announcement says only that the list was refreshed, which is true. Retry re-reads the explanation only (partial-failure test).
- A member absent from the new list is pruned (card and explanation ids), so they do not reopen if they reappear (E11).
- Campaign changes: the disclosure reads as empty for another campaign (E14); `CampaignLayout`'s existing keyed remount still applies.
- **Focus.** The Refresh control is unmounted by the reload, so on success focus returns to that member's explanation toggle, or to the status line (now `tabIndex={-1}`) if the member is gone. This is only for Refresh access; mutations keep the existing O-3 behavior. If the list read fails, the boundary's own error page replaces the content and focus is on the page body, not on a stale element.
- Not promised: same-snapshot consistency between the two reads, and no inference of source identity from display names (the portal never correlates an explanation source with an overview row).

**Deviations from §4 (each with its reason).**

1. **Announcement copy and timing.** §2/§6 and D-3 give "Access information refreshed." announced through the existing announce-and-retry path, i.e. at the click. The owner instruction for this task requires that a failed read is not presented as refreshed, so the text is `Access list refreshed.` and it is announced only after the list read succeeds. The mutation announcements are unchanged.
2. **Member cards are controlled `<details>`.** The plan keeps explanation state above the boundary but did not say that the member card containing the explanation is itself closed by the reload (an uncontrolled `<details>` remounts closed), which would hide an "open" explanation. The card's open state is held beside it in the same hook. This also keeps cards open across mutation reloads, which is a visible behavior change for all Access changes.
3. **Focus return and `tabIndex={-1}` on the status line** (Refresh access only), required by the instruction that refresh not leave focus on an unmounted control; §11.1 had said no focus machinery.
4. **`AccessPage` props** `disclosure` and `onRefreshAccess` are optional; absent, it keeps its own disclosure and announces through `onChanged`. Production always passes them. This keeps the existing `AccessPage` tests unchanged.
5. **New files** beyond §4's list: `hooks/useAccessDisclosure.ts` (the held state) and the player cases were added to `App.characterRecord.test.tsx` as planned.

**Existing assertions changed.** `EffectiveAccessPanel.test.tsx` is rewritten to drive the now-controlled panel through a small stateful harness (this is the allowed "test drove the panel's former local state" change); its four original assertions are unchanged. No other existing assertion was changed. `AccessPage.test.tsx` and `App.characterRecord.test.tsx` only gained cases.

**Acceptance coverage.**

| Case | Where |
|---|---|
| E1, E2, E3 | `EffectiveAccessPanel.test.tsx` (label "Revelation" twice per capability; unknown kind; marker keys), `AccessPage.test.tsx` (overview markers) |
| E4 | `AccessPage.test.tsx` "Revealed characters" (entries, empty, absent key, no control or link) |
| E5, E9 | `CampaignAccessPage.effectiveAccess.integration.test.tsx`: revoke while an explanation is open; no explanation text and no explanation read while the list loads; order revoke → list → explanation; card and disclosure still open; announcement |
| E6, E7 | same file: change made elsewhere, Refresh access, list before explanation, announcement only after the list, focus on the toggle, then the last source gone |
| E8 | same file: revelation beside a whole-character deny, existing wording |
| E10 | same file: an explanation answered after a list reload is never rendered |
| E11 | same file: member removed elsewhere, then reappearing; no read and no reopening |
| E12 | same file: 403 on refresh (no content, no announcement); 500 then retry (announced only on success) |
| E13 | same file: 401 on an explanation and on the overview each reload the session and render no content |
| E14 | same file: another campaign starts closed and sends no explanation read |
| E15 | `EffectiveAccessPanel.test.tsx` (independent rows) and the integration file (closing prevents a late answer from restoring it) |
| E16, E17, E18 | `App.characterRecord.test.tsx` "player surfaces stay source-free": public → summary → public → unavailable with no source words and no request to `/effective-access` or `/access-overview`; list/detail after revocation; list card summary after a tier change |
| E19 | the full existing suite |
| partial failure (owner instruction) | integration file: explanation fails after a successful list, Retry re-reads only the explanation |

**Annotation added after the real-browser run (O-5).** The E5/E9 row above was verified in jsdom with a session whose `reload()` does nothing; it therefore did not exercise the session reload that remounts the Access page in the real app, and E5's "disclosure still open" and "announced" clauses did not hold there for a mutation. See §11.7 and §11.8. This record is otherwise unchanged.

**Verification (portal/ PowerShell; root for the last two).**

| Run | Result |
|---|---|
| Focused during work | `EffectiveAccessPanel`, `AccessPage`: 92 passed. First integration run: 4 of 11 failed, all test-side (a card looked up before the reload had rendered it; the card not opened as a person does). Fixed in the tests; rerun 11, then 12 passed after the 401 split. `App.characterRecord`: 47 passed |
| Mutation probe | AccessPage ignores the held disclosure (`heldDisclosure ?? ownDisclosure` → `ownDisclosure`): 6 of 12 integration tests failed (E5/E9, E6/E7, E10, E11, E12 retry, partial failure). `AccessPage.tsx` SHA-256 before and after `D5837DFDDDDC9BA050B9A6B97A2988FA03F023E920A10FEDC9CD8F2A7DDE0573`; restored |
| `npm test`, first run | 428 files, 5269 tests, all passed |
| `npm run lint`, first run | failed: one unused helper in the new integration test (`idx`) |
| `npm run build`, first run | failed on the same unused helper (TS6133) |
| Fix and rerun | `npm run lint` passed; `npm run build` passed (existing chunk-size warning); the integration file passed again (12) |
| `uv run python scripts/check_documentation.py` | passed |
| `git diff --check` | clean (run before the commit; see the handoff for the staged check) |

After the fix, `npm test` was run again in full: 428 files, 5269 tests, all passed (second full run). `git diff --check` was also clean on the final working tree and on the staged diff before the commit.

**Remaining limitations.**

- `humanizeCode("revelation")` already yields "Revelation", so the explicit `SOURCE_KIND_LABELS.revelation` entry is the contract but is not distinguishable by output; E1 asserts the text, and the probe above is on the refresh behavior instead.
- The two reads remain independent observations (G-2); an explanation can disagree with the list for the moment between them.
- A reload still moves focus to the page body for mutations (O-3), and after a failed list read.
- No player-side source explanation exists (G-1). O-1 to O-4 are unchanged and stay recorded separately.
- Browser, accessibility, integrated-head CI, checkpoint merge and owner acceptance remain pending. C02 and A5c were not started.

### 11.4 Luna independent review — focus return correction required (2026-11-19)

**Boundary and repository state.** Reviewed the complete `d6615b93d1aaa0e7fba8b08f84c224df178e6e41..f295c25807f18188acacc73050fd4673faabd305` range on `phase15/completion`. The plan and implementation are in the same head commit; no separate plan commit exists. At review start, `HEAD` was `f295c25807f18188acacc73050fd4673faabd305`, and the worktree was clean (`phase15/completion...origin/phase15/completion [ahead 5]`). No repository `AGENTS.md` exists. No production files were changed. The mutation probe below was restored byte-for-byte. This review record and the two S02 register status edits are the only review changes and remain uncommitted.

**Verdict: CHANGES REQUIRED.** The authorized projection and coordinated list/detail refresh meet the reviewed requirements in this range, but the newly added refresh focus restoration violates the explicit delayed-completion focus requirement. S02/T01 do not pass independent implementation review yet. This is separate from inherited O-3: O-3 concerns existing Access mutation and failed-read reloads; this defect is introduced by the new successful **Refresh access** path, which always reclaims focus.

**Finding S02-R1 — delayed refresh steals focus (Low, score 3/10; blocks this slice's stated acceptance until corrected).** [CampaignAccessPage.tsx](../../portal/src/pages/CampaignAccessPage.tsx#L149) `handleRefreshSettled` unconditionally focuses the requesting member toggle or the status paragraph after the successful overview read. The access tab navigation remains mounted while the overview is loading, so a manager can move focus to another control or route-navigation link during a delayed read; when it settles, focus is pulled back to the old row/status paragraph. The E6 test in `CampaignAccessPage.effectiveAccess.integration.test.tsx` confirms focus returns when the user has not moved, but has no delayed-completion case in which the user moves focus elsewhere. **Expected:** restore focus only when focus remains displaced by the refresh's removed control (or otherwise has no meaningful current destination); do not override a user's subsequent focus move. **Actual:** every successful pending refresh focuses the old member toggle/fallback regardless of current focus. **Exposure:** 1, a constrained manager refresh path with a delayed response and intervening focus move. **Impact:** 1, a bounded keyboard-navigation disruption; no access data or command authority is affected. **Triggerability:** 1, requires that timing and user action. **Detection/recovery:** 0, visible and readily recoverable by moving focus again. **Blast radius:** 0, one manager's current page. Total 3/10, Low under [grading.md](grading.md#severity-and-checkpoint-disposition). The implementation still fails this slice's explicit acceptance despite Low product severity. **Correction:** retain the success-only, campaign/member-scoped focus return, but skip it when a connected, meaningful element has gained focus since the refresh began; add an integration test holding the overview response, moving focus to another persistent control, resolving the response and asserting focus stays there. Keep the existing E6 focus-return case for the no-intervening-move path.

**Other reviewed behavior and acceptance coverage.** The route and `AccessTabNav` use effective `access.manage` capability gates, not a GM role comparison. `EffectiveAccessPanel` renders only the contracted source fields (`kind`, `label`, nullable `target_display_name`) in response order; the revealed-character list renders only display names and audience display labels, preserving duplicates/order and adding no inferred source match. Player character paths neither request manager endpoints nor expose source labels/counts (App E16–E18). The real `AuthenticatedSessionBoundary` replaces protected children while session reload is loading; campaign changes derive empty disclosure state, and overview 403/unavailable clears protected content. Explanation errors have an explanation-only retry; overview failure does not mount stale explanations. Abort/version ownership, close/unmount, authoritative successful-list pruning, campaign scoping, and E10/E11/E14/E15 cover stale answers, removal/reappearance, campaign change and close behavior. The fake server exercises the real page, boundary, panel, hooks and API clients; its independent GETs intentionally do not claim a single database snapshot (G-2). E1–E4 cover labels/projection and the read-only list, E5–E9 cover refresh ordering, loading and partial outcomes, E10–E15 cover stale/removed/authority/session/campaign/close transitions, E16–E18 cover player non-disclosure and tier transitions, and E19 plus the focused/full suites cover existing Access and character routes. The optional `AccessPage` props are supplied by its production caller; standalone tests intentionally exercise the local fallback. Persistent card expansion is documented and its controlled native `<details>` retains button toggling. The explicit Revelation label matching the generic humanizer is only a coverage characteristic. G-1/G-2 and inherited O-1–O-4 remain separately recorded and unchanged.

**Verification (documented PowerShell invocation).** Focused affected tests: `npm test -- src/components/EffectiveAccessPanel.test.tsx src/pages/AccessPage.test.tsx src/pages/CampaignAccessPage.test.tsx src/pages/CampaignAccessPage.effectiveAccess.integration.test.tsx src/App.characterRecord.test.tsx` — 5 files, 158 tests passed. Full `npm test` — 428 files, 5,269 tests passed; three jsdom “navigation to another Document” notices, no failures. `npm run lint` passed. `npm run build` passed with the existing Vite chunk-size warning. `uv run python scripts/check_documentation.py` passed. `git diff --check d6615b93d1aaa0e7fba8b08f84c224df178e6e41 f295c25807f18188acacc73050fd4673faabd305` was clean. These were first review runs; no verification reruns were needed. The intentional mutation probe temporarily replaced the successful overview's `disclosure.prune(...)` call with a no-op and ran E11 alone: it failed as expected because the returning member's explanation remained expanded (`aria-expanded="true"`, expected `false`). Restored `CampaignAccessPage.tsx` SHA-256 is exactly `6F9342B269EE45FFDBE87B1D2B6364B9C602F90C32282EB68C73F1C9A95EA684`, identical before and after.

**Re-review boundary and remaining obligations.** Re-review the corrected S02/T01 range from `f295c25807f18188acacc73050fd4673faabd305` through the correction head, including a delayed-response focus-move regression assertion. Browser, accessibility, integrated-head CI, checkpoint merge and owner acceptance remain pending; a slice pass will not close the checkpoint. S01 remains reviewed as recorded in its own plan. C02 and A5c were not started or reviewed.

## 11.5 Correction of S02-R1 (Sonnet), 2026-11-19

Luna's finding and verdict in §11.4 are unchanged. This section is the correction evidence; it does not accept the slice. **Status: corrected; Luna re-review pending.**

**Base.** `f295c25807f18188acacc73050fd4673faabd305` on `phase15/completion`. Before work the tree held only Luna's uncommitted §11.4 and the two S02 register status cells; both are preserved and committed with the correction. No `AGENTS.md`. The correction commit is titled `P15-C01-S02: respect focus changes during access refresh`; its SHA is reported in the handoff. Nothing was pushed. Only `portal/` and `docs/` changed.

**Change (`pages/CampaignAccessPage.tsx` only).**

- **Restore only displaced focus.** On a successful list read, `handleRefreshSettled` returns focus to the member's explanation toggle (or the status line if the member is gone) only when `document.activeElement` is null, the page body or no longer connected, which is what removing the Refresh control leaves. If a connected control holds focus (for example an Access tab link the manager moved to while the list was loading), focus is left there. The announcement ("Access list refreshed.") and success-only behavior are unchanged.
- **Bound to its refresh.** The pending intent now carries an `episode` from a per-page counter. A completion acts only if its episode is still the latest and its campaign is still the active one, so an older refresh cannot act after a newer one. Starting or completing an Access mutation clears an unanswered refresh, so a later successful read cannot confirm and refocus for a refresh the manager has since replaced with another operation. The existing campaign scoping of the intent is kept.
- No new framework, no change to the disclosure, refresh ordering, projections, authorization or O-3.

**Tests (`CampaignAccessPage.effectiveAccess.integration.test.tsx`).**

- New: Refresh access with the overview held; focus moved to an Access tab link; the response released; the test waits for the "Access list refreshed." announcement and the explanation to reload, then asserts the tab link still has focus and the member toggle does not.
- New: the member disappears in the refreshed list with focus displaced: focus goes to the status line.
- E6 keeps its no-intervening-move restoration assertion, now inside `waitFor` so it cannot pass before the focus effect has run. No other existing assertion changed.

**Mutation probe.** Replacing the displaced-focus check with an unconditional restore (the former behavior) failed exactly the new move-away test (1 of 14); E6 and the member-gone fallback still passed. Restored; SHA-256 of `CampaignAccessPage.tsx` before and after the probe `1BBB2DFB00F510897C9F16C95BFB939CF1DB92C6F2E5CAD1FCAAC6B57D5AAFC3`.

**Verification (portal/ PowerShell; root for the last two).**

| Run | Result |
|---|---|
| Focused integration file, first run after the change | 14 passed (no failure) |
| Mutation probe | 1 failed as above, then restored |
| `npm test`, first run | 428 files, 5271 tests passed |
| `npm run lint`, first run | passed |
| `npm run build`, first run | passed (existing chunk-size warning) |
| `uv run python scripts/check_documentation.py` | passed |
| `git diff --check` | clean (working tree and staged diff) |

There were no first-run failures and no reruns.

**Remaining limitations.** O-3 (mutation reloads and failed list reads leave focus on the body) is unchanged. If focus is on the body for any other reason when the list returns, it is treated as displaced and restored. Browser, accessibility, integrated-head CI, checkpoint merge and owner acceptance remain pending. C02 and A5c were not started.

**Luna re-review boundary.** Base `f295c25807f18188acacc73050fd4673faabd305`; head = the correction commit.

## 11.6 Luna re-review of S02-R1 (2026-11-19)

**Boundary and state.** Reviewed the complete correction range `f295c25807f18188acacc73050fd4673faabd305..df747494b6c3a3e5965dfe62de6111e8755b5ed7` on `phase15/completion`. `HEAD` was `df747494b6c3a3e5965dfe62de6111e8755b5ed7`; at review start the tree was clean and the branch was ahead of origin by six commits. No repository `AGENTS.md` was found. Correction is local and unpushed. Only this review record and the S02/T01/parent register status cells are changed for this review; production files are unchanged.

**Verdicts.** (1) **S02-R1 is resolved.** (2) **P15-C01-S02 passes independent implementation review** on the original implementation range plus this correction. No new finding is raised. The Low-scored finding in §11.4 and its original CHANGES REQUIRED verdict remain preserved as the history for the corrected range; the disposition is now closed by this re-review, not erased.

**Focus and ownership.** `handleRefreshSettled` now restores focus only when `activeElement` is null, the body, or disconnected. The member toggle is the target when present; the status paragraph is the fallback when the member disappeared. The move-away integration test holds the overview response, focuses the still-mounted Access tab link, resolves the read, waits for the success announcement and reloaded explanation, and verifies focus remains on that link. E6 still checks return to the requesting member toggle, now waiting for the focus effect; the member-disappeared test waits for successful refresh and status-line focus. The success callback is rendered only in the successful overview branch, so a failed overview cannot announce or restore focus. Access changes remain success-only.

Refresh intent includes campaign and a per-page episode, and the completion callback rejects a nonlatest episode or inactive campaign. A second refresh cannot be initiated from the UI while the overview is loading because the panel and its control are unmounted; the overview hook also aborts superseded requests and keys state by campaign/request version. In production, `CampaignLayout` keys the outlet subtree by campaign and perspective, so campaign navigation unmounts this page; a session reload replaces protected content at `AuthenticatedSessionBoundary`. Authority loss returns unavailable without mounting `OverviewSettled`. Mutation start and successful mutation handling clear pending refresh intent; mutation refresh uses the existing overview retry and request-version ownership. Existing mutation→list→explanation integration coverage remains intact. There is no dedicated test that forces a refresh and an in-flight mutation to complete in both orders; inspection of the unmount/abort and request-version paths shows an obsolete overview cannot mount a stale completion after a mutation retry. No concrete residual behavior failure was demonstrated.

**Body-focus heuristic.** The documented case where `document.activeElement` is the body for another reason remains a limitation, not a new blocker. The requested invariant is to preserve focus on another meaningful connected control, and the tested supported interaction (moving to the mounted Access tab link) is preserved. A nonfocusable blank-area click can leave body focus, but is not a meaningful control destination under that criterion; restoring to the member toggle or status line is a useful fallback. Inherited O-3 remains distinct: mutation reloads and failed list reads still leave focus on the body and are separately pending under accessibility review.

**Verification.** Focused PowerShell run from `portal/`: `npm test -- src/pages/CampaignAccessPage.effectiveAccess.integration.test.tsx src/pages/CampaignAccessPage.test.tsx src/pages/CampaignAccessPage.roleAddRevoke.integration.test.tsx src/pages/CampaignAccessPage.resourceGrant.integration.test.tsx src/App.characterRecord.test.tsx` — 5 files, 72 tests passed. `npm test` — 428 files, 5,271 tests passed. `npm run lint` passed. `npm run build` passed with the existing Vite chunk-size warning. `uv run python scripts/check_documentation.py` passed. `git diff --check f295c25807f18188acacc73050fd4673faabd305 df747494b6c3a3e5965dfe62de6111e8755b5ed7` and working-tree `git diff --check` were clean. These first runs had no failures; no reruns were required.

The requested mutation probe replaced the connected-focus early return with an unconditional restore and ran the move-away regression alone. It failed at the expected assertion: focus was on the member toggle instead of the Access link. `CampaignAccessPage.tsx` was restored byte-for-byte; SHA-256 before and after was `1BBB2DFB00F510897C9F16C95BFB939CF1DB92C6F2E5CAD1FCAAC6B57D5AAFC3`. This was the only intentional failed test run.

**Remaining P15-C01 checkpoint obligations.** S02/T01 is reviewed, but the checkpoint is not PR-ready until browser and accessibility evidence and integrated-head CI are complete. Checkpoint merge and owner acceptance remain separate pending events. S01 remains passed; G-1/G-2 and O-1–O-4 retain their separately recorded dispositions. C02 and A5c were not started or reviewed.

## 11.7 Browser and accessibility evidence; inherited observation O-5 (Sonnet), 2026-11-19

Scripted real-browser evidence for this slice's E5/E6/E8 and the focus obligations is recorded in [p15-c01-browser-ax-evidence.md](p15-c01-browser-ax-evidence.md), taken at `efe5a77` on a production build (S02: 30 of 30 checks; structure, keyboard, viewport and zoom: 18 of 18). It confirms Refresh access (list then explanation, success-only announcement, focus restored to the member's toggle, focus left where the manager moved it, status-line fallback when the member disappears, failed-list and failed-explanation behavior, authority loss). It also found one behavior that differs from this plan and from the §11.3 jsdom evidence:

- **O-5 (inherited, Low, score 3).** An Access *mutation* (for example removing character access) calls the session `reload()`, which replaces the whole page with "Loading portal". The open cards and explanations therefore start closed and the status-line announcement is lost. §2.3 and E5 above say an open explanation survives a mutation's reload; that holds for Refresh access and for Try again after a failed list read, not for mutations. The jsdom test used a session whose `reload` does nothing. The hook and boundary files are unchanged since `cdfdf21`, so this predates S02; it is recorded beside O-1 to O-4, not fixed here, and needs an owner decision (see the evidence record, finding C01-B1). **Update:** regraded Medium (5) and corrected; see §11.8. The ACCESS_CONTROL §3q and portal-behavior §8.3 paragraphs were corrected accordingly.

Assistive-technology and human checks remain pending (the evidence record, §6). S02 review status (§11.4 to §11.6) is unchanged.

## 11.8 O-5 correction (Sonnet), 2026-11-19

This section regrades O-5, records what it did to this slice's acceptance, and records the correction and its evidence. §11.3 to §11.7 are unchanged historical records; where they say otherwise, this section controls. It does not accept the slice. **Status: O-5 corrected; Luna re-review pending.**

**Base and heads.** Starting head `72b64a601b01b679e2e02463ecc39cfc09d01809` (draft PR #70, CI green). Correction commit `e8613f93a192e1f450c88811f98bd065668ab0dc` ("P15-C01: keep the Access page mounted across writes that cannot affect the caller (O-5)"); the records commit that follows it is reported in the handoff. PR #70 stays a draft; nothing was merged.

### Regrade (supersedes "Low, score 3" in §11.7 and in the evidence record)

| Factor | Score | Reason |
|---|---:|---|
| Supported-path exposure | 2 | An access manager (privileged caller) on the Access page, after any Access mutation: a normal, routine path. The earlier 1 understated it. |
| Impact magnitude | 1 | Open explanations close and the status-line confirmation is lost; no data is lost. Not raised to 2: whether a screen reader is silent was not established (no AT run). |
| Triggerability | 2 | Every Access mutation that succeeded. The earlier 1 understated it. |
| Detection and recovery | 0 | The closed explanations are visible and recoverable by reopening. Would be 1 if an AT run showed the announcement is silent. |
| Blast radius | 0 | One manager's current page. |
| **Total** | **5, Medium** | Default: prioritize a bounded correction; acceptance with the issue needs an explicit, evidence-backed risk decision. |

### Acceptance impact (before the correction)

The behavior predates S02 (the hook, session and boundary files are unchanged since `cdfdf21`), so it is not a regression. The rubric still lets a pre-existing issue block a slice that claims to fix it, and S02 did. For mutation-triggered reloads in the real app these requirements were **not met**: your scope choice "preserve expanded explanations across member-list reloads" and plan §2.3 ("whether from a mutation on the page or from Refresh access"); §1.3 point 3 (the explanation the manager is looking at no longer closes on every change); E5 ("the disclosure is still open" and "'Character access removed.' is announced"); and §2.4 (the survivor visible in the explanation, not only the list). They were met for Refresh access and Try again. S02/T01's implementation review pass (§11.4 to §11.6, at `df74749`) rested on jsdom evidence that mocked away the remount; that pass stands as a record of what was reviewed and does not cover this correction.

### Annotation of the earlier E5 evidence

The E5/E9 row of §11.3, the integration test it cites (`CampaignAccessPage.effectiveAccess.integration.test.tsx`), and the seven other `CampaignAccessPage.*.integration.test.tsx` suites (role change/add/revoke, character relationship, resource grant, access group, add/remove member, and the page test) render the page under a session context whose `reload()` does nothing. They never mount `AuthenticatedSessionBoundary` or the real session hook, so the "Loading portal" remount that every confirmed Access write caused in the real app cannot occur in them. Their names and comments ("persistent announcement survives the overview's own loading transition") are true of the overview boundary alone. The hook unit tests assert that `reload` was called, not what the call does to the page. That is the false confidence O-5 exposed; those suites are kept (they test other behavior) and the E5 test now carries a pointer to the real-lifecycle test.

### What `refresh()` does (inspected before choosing the design)

`useSessionBootstrap.refresh()` re-reads the bootstrap without passing through `loading`. It resolves `true` only when its result was **published**. It resolves `false` when the session turned out to be unauthenticated (state becomes `unauthenticated`), or when the read was not its own to publish (a reload, an expiry, or a newer read took ownership: "NOT APPLIED. It is not a verdict"). It rejects when the read failed. A call with no signal **joins a read already in flight**, which may have started before this write committed and would then report an older state. So a resolved call is not proof that fresh state was applied, and the shared form must not be used after a write.

### Correction

- **`hooks/useAccessWriteCompletion.ts`** (new): `useAccessWriteCompletion()` returns the function an Access mutation hook calls when its write is confirmed. With `affectsCaller` true (the default when no scope is provided) it calls `reload()` exactly as before. With it false it calls `refresh()` **with a signal of its own** (never joins an older read; never aborted, so leaving the page does not cancel confirming a committed write), and treats only a resolved `true` as applied. A resolved `false` or `undefined`, a rejection, or a synchronous throw falls back to the full `reload()` (fail closed; this includes an overtaken, superseded or unauthenticated read).
- **16 Access mutation hooks** call it instead of `reload()` on success (add/change/revoke role, add/change/revoke character relationship, add/revoke resource grant, add group resource grant, create/update/deactivate/reactivate access group, add/remove group member, remove campaign member). Their 401 path still calls `reload()`. `useAddCampaignMember` never reloaded on success and is unchanged. Invitation, account-admin and revoke-all-sessions hooks are not Access-page writes and are unchanged.
- **`pages/AccessPage.tsx`** supplies the scope: a control in the **caller's own member card** may affect the caller (reload); in another member's card it cannot. In a **group card** the write may affect the caller if the caller is a member of that group, or if the caller is not a listed member at all (unknown: reload); adding a group member may also affect the caller when the caller is among the members offered (active, not already in the group). **Create group** cannot (a new group has no members). Everything else, and any control outside a scope, stays on the reload path.
- **Preserved:** an authoritative bootstrap after every confirmed write; reload for self-affecting writes, 401, and any refresh that failed or was not applied; the overview retry and its ordering (the explanation is read after the list); idempotency and status snapshots in the hooks; `CampaignLayout`'s handling of a revoked perspective.

### Evidence

- **Regression tests (real session lifecycle).** `CampaignAccessPage.sessionLifecycle.integration.test.tsx` mounts the real `SessionProvider` (real `useSessionBootstrap`, reading `/auth/session`), the real `AuthenticatedSessionBoundary` and the Access page, with only the network mocked: a non-self write keeps the page mounted (same status-line element, text present, explanation open and re-read after the list, "Loading portal" never shown, one session re-read); a write on the caller's own membership reloads the session and remounts; a failed in-place read falls back to a reload; a session that ended leaves for sign-in with no access content; a refreshed session and list reporting lost access show "Access unavailable" with no member or explanation content; and a read overtaken by a newer one is not applied and reloads. `useAccessWriteCompletion.test.tsx` (7 tests) covers the helper (default scope, own signal, applied, not applied, no answer, rejection, throw).
- **It fails before the correction.** With the helper forced to the old behavior (always reload), 4 of the 6 lifecycle tests failed (non-self mounted, failed-read fallback, authority loss, overtaken read) and the 2 fail-closed tests passed as expected. `useAccessWriteCompletion.ts` SHA-256 before and after the probe: `DCB42CA1DAF42BF6EE7DAB4AC9282800CF6DEA8A64C341E8B03186140D0BA8E2`; restored.
- **Browser re-run on a production build of `e8613f9`** (same stack and method as the evidence record's §1; see its §7): S02 34 of 34, structure/keyboard/reflow 18 of 18, S01 personas 29 of 29. In the real browser a non-self write (G1) left the page mounted (`Loading portal` never appeared, the status line was the same element and read "Character access removed.", the open explanation stayed open and was re-read after the list, the session was re-read once); a write on the caller's own membership (G8) reloaded the session and remounted with the explanation closed; a failed session read (G9, injected 500) fell back to a full reload; and lost authority (G10, injected session and list responses) showed "Access unavailable" with no member or explanation content while the write's confirmation stayed on the status line. Focus after a write is the page body (O-3, inherited and unchanged: the confirm control is replaced by the list reload).
- **Not claimed.** No screen reader was run, so that the announcement is **spoken** is not established; the evidence is that the live region is `role="status" aria-live="polite"`, stays mounted, and its text changes. Actual browser zoom, human review and other browsers remain unperformed.

### Verification (portal/ PowerShell; root for the last two)

| Run | Result |
|---|---|
| Focused: lifecycle test, helper test | lifecycle first run: 2 of 6 failed (a harness defect: the page's initial "Loading portal" was counted; the counter now starts after first load), rerun 6 of 6; helper 7 of 7 |
| Pre-correction probe | 4 of 6 failed, restored, bytes verified |
| `src/pages`, `src/hooks`, `src/components` and the character-record suite | 275 files, 3150 tests passed (existing Access, hook and component tests unchanged and passing) |
| `npm test` | first run: 430 files, 5284 tests passed |
| `npm run lint` | passed |
| `npm run build` | passed (existing chunk-size warning) |
| Browser re-run | first attempt: 33 of 34 (G10's page-text check matched the signed-in user's name in the portal header, a harness assertion; scoped to the page content); rebuilt fixtures and run again in full: 34 of 34, with S01 and the structure run 29 of 29 and 18 of 18 |
| `uv run python scripts/check_documentation.py`, `git diff --check` | recorded in the handoff for the final head |
| CI | draft PR #70 on the final head: recorded in the handoff |

### Remaining limitations

- A self-affecting write still remounts the page (by design, fail closed), and a refresh that is overtaken falls back to a reload even when the newer read had already applied fresh state; both are conservative.
- O-3 (focus after a reload or write) is unchanged; O-1, O-2, O-4, G-1 and G-2 are unchanged.
- Screen-reader, actual-zoom, human and other-browser checks remain pending, as do the register's integrated-head `browser` and `ax` obligations, owner acceptance and checkpoint merge. A5c and P15-C02 were not started. Luna's re-review of this correction is pending.

## 11.9 Luna independent re-review of O-5 correction (2026-11-20)

**Boundary and state.** Reviewed baseline `72b64a601b01b679e2e02463ecc39cfc09d01809`, code correction `e8613f93a192e1f450c88811f98bd065668ab0dc`, and records/head `1c57b04fb52ffe64091dc78052529514bd5866b4` on `phase15/completion`. The tree was clean at review start; `HEAD` was the records/head SHA. No repository `AGENTS.md` was found. Production code was not changed. This re-review does not pass the corrected slice because of finding O-5-R1 below; prior S01/S02 findings and verdicts remain historical records.

### Verdicts

1. The correction implements the requested preservation path for caller-unaffected confirmed writes, while self-affecting writes and failed/unapplied bootstrap reads conservatively reload and remount.
2. **O-5 is not fully closed:** a fresh, successfully applied bootstrap can report loss of `access.manage` without clearing an already-successful overview on the still-mounted page. O-5-R1 is **Medium, score 6/10**, and blocks independent implementation-review pass pending a bounded correction.
3. P15-C01-S02 therefore does **not** pass this independent re-review yet. This finding is separate from inherited O-3; no new O-3 focus defect was demonstrated.

### O-5-R1 — applied authority loss leaves protected overview mounted (Medium, 6/10)

**Location.** [`useAccessOverview.ts`](../../portal/src/hooks/useAccessOverview.ts#L53) owns overview state and requests; [`AccessOverviewBoundary.tsx`](../../portal/src/components/AccessOverviewBoundary.tsx#L19) renders its successful snapshot without consulting the current session capability; [`CampaignAccessPage.tsx`](../../portal/src/pages/CampaignAccessPage.tsx#L61) calls `useSession()` but uses the session only for the audience-preview decision at line 119, while the Access route at `App.tsx` mounts this page without a client capability gate. The corrected helper's non-self path applies a bootstrap refresh in place (`useAccessWriteCompletion.ts`); `AuthenticatedSessionBoundary` replaces protected children on reload/loading, but that remount does not occur for a successfully applied in-place refresh.

**Concrete trigger and behavior.** An access manager has a successful overview with member/source data rendered. A non-self mutation is confirmed and starts the overview retry and the helper's fresh session read. Another manager revokes the caller's `access.manage` while those independent reads are in flight. The overview request can return its earlier authorized 200, and the fresh bootstrap can then successfully publish a session without `access.manage`. The page remains mounted and the overview snapshot remains `success`; the boundary does not hide it based on the newly published capability. Existing source labels and member data can therefore remain visible, and previously opened explanations can be requested/rendered, after the session bootstrap has authoritatively removed the caller's manager capability. Subsequent writes remain backend-authorized, but that does not clear the already-rendered protected read data.

**Expected / actual.** Once the applied bootstrap says this campaign no longer grants `access.manage`, protected overview and explanation content should be cleared/unmounted and no new explanation request should be made. Actual: the session state updates, but the mounted overview boundary has no dependency on that state; content disappears only if a later overview GET itself returns 403/404 or a full reload occurs. The existing lifecycle test pairs loss of session authority with an overview 403, so it does not cover a successful/stale overview response alongside the applied capability loss.

**Rubric.** Supported-path exposure **1** (constrained race during a manager's Access-page refresh after a concurrent authority revocation); impact **3** (protected access-source/member information remains exposed after the application's authoritative manager capability is withdrawn); triggerability **1** (requires concurrent revocation and independent response ordering); detection/recovery **1** (content can remain silently visible until another read/navigation); blast radius **0** (one caller's current page). Total **6/10, Medium** under [grading.md](grading.md#severity-and-checkpoint-disposition). Correction: bind the mounted Access overview/explanation subtree to the current campaign's effective `access.manage` capability and immediately clear it when that capability is absent; add a production-boundary regression with a successful overview and a refreshed session losing the capability, asserting no member/source/explanation content and no explanation request after revocation.

### Scope checks and accepted behavior

The implementation uses explicit caller scope: member-card mutations use membership identity; unknown caller identity is conservative; group-card writes reload when the caller is a member or membership is unknown; adding a group member also reloads when the caller is among eligible offered candidates; Create group is non-self because the new group is empty; unscoped controls default to self-affecting. The helper uses an independent signal so a confirmed write does not join a pre-write request; only an applied refresh avoids reload, and false, rejection, throw or self-affecting scope reloads. This preserves conservative failure behavior and avoids a stale joined bootstrap. Existing mutation-to-list-to-explanation ordering remains in the overview retry path.

For non-self writes, the component state above the boundary preserves the disclosure IDs and page status region while the list boundary reloads; those IDs do not retain access response data. Self-affecting writes intentionally remount and close disclosures. A fallback reload after a failed or superseded refresh also remounts and closes them. Documentation in §11.8, API ACCESS_CONTROL §3q and portal behavior §8.3 describes those self-affecting/fallback remount cases; the older E5 wording remains annotated as not unconditionally satisfied. The browser record demonstrates DOM live-region continuity and text mutation only; it does not establish that a screen reader spoke the announcement. Inherited O-3 remains separate.

The lifecycle integration tests mount the real SessionProvider/useSessionBootstrap, AuthenticatedSessionBoundary and CampaignAccessPage with network responses controlled by the test. They meaningfully detect the original always-reload behavior. Their authority-loss case is narrower than the race above because both session and overview deny responses are returned. No duplicate test coverage was requested; the uncovered case is the independent successful-overview/applied-session-revocation ordering described in O-5-R1.

### Verification

Focused portal run from `portal/`: `npm test -- src/hooks/useAccessWriteCompletion.test.tsx src/pages/CampaignAccessPage.sessionLifecycle.integration.test.tsx src/pages/CampaignAccessPage.effectiveAccess.integration.test.tsx src/pages/AccessPage.test.tsx src/pages/CampaignAccessPage.roleAddRevoke.integration.test.tsx src/pages/CampaignAccessPage.accessGroup.integration.test.tsx` — 6 files, 121 tests passed. Local `npm run lint` passed; local `npm run build` passed with the existing chunk-size warning. `uv run python scripts/check_documentation.py` passed; `git diff --check` was clean. No test or lint reruns were needed. The exact-head GitHub Actions run `44668809167` completed successfully with all jobs, including all eight PostgreSQL shards, passing.

The PR #70 Actions run `44668809167` is a `pull_request` run whose reported `headSha` is exactly `1c57b04fb52ffe64091dc78052529514bd5866b4`. Its workflow checks out GitHub's generated PR merge ref, not just the head tree: merge commit `c4043df6e28a8a62fd8501dac64d6ceadb08f8c8`, with base `a9952d8437934a2b6885da3196b7f15ea18e74c6` and head `1c57b04fb52ffe64091dc78052529514bd5866b4` as parents. No workflow run was found for code commit `e8613f9` alone. PR #70 is open/draft and was not merged.

### Remaining obligations

This slice remains in O-5 correction/re-review required state. The PR workflow CI passed on its generated merge ref with the exact reviewed head as the PR head; this does not close the separate integrated-head browser/ax evidence, assistive-technology, actual-zoom or human obligations. Checkpoint merge and owner acceptance remain pending. S01's pass is preserved. C02 and A5c were not started or reviewed.

## 11.10 O-5-R1 correction (Sonnet), 2026-11-19

Luna's §11.9 finding, grade (Medium, 6/10) and verdict are unchanged historical records, as are S01's pass and the earlier S02-R1 pass; inherited O-3 keeps its own disposition. This section records the correction and its evidence. **Status: O-5-R1 corrected; independent re-review pending.** **Next independent review range: `1c57b04fb52ffe64091dc78052529514bd5866b4` to the correction head** (the code commit below and the records commit that follows it, reported in the handoff). PR #70 stays a draft; nothing was merged.

**Cause.** §11.8's in-place session read (O-5) does not remount the page, so a successfully applied bootstrap without `access.manage` left an already-successful overview, its members, sources and open explanations mounted: `AccessOverviewBoundary` and the explanation hooks never consulted the session capability, and the page used the session only for the audience-preview decision. §11.8's authority-loss test paired the loss with an overview 403, which hid it.

**Correction (code commit `61da59ed4b6f854b98e920f0eb5f7f3eb9a7a364`).**

- **`pages/CampaignAccessPage.tsx`** reads the existing capability resolver, `useCampaignCapability(campaignId, "access.manage")` (the bootstrap's per-campaign capabilities, false for an unlisted campaign), on every render. Without it, nothing protected is mounted: `AccessOverviewBoundary` and everything beneath it (the overview, `AccessPage`, members, sources, `EffectiveAccessPanel`, the audience preview and the hooks holding their responses) are replaced by the established unavailable state (`PlaceholderPage` "Access unavailable", the boundary's own wording). The tab navigation and the page's status line stay mounted; the status line holds only the write's confirmation, no access data.
- **New explanation reads while unauthorized cannot start**, because no explanation component is mounted. A response still in flight is aborted with its unmounted hook (`controller.signal.aborted`) and cannot publish; an explanation answer that arrives late is dropped.
- **Protected local state is discarded:** on loss the held disclosure ids are pruned to empty and a pending refresh intent is invalidated (the episode counter advances), so a capability that returns starts from a fresh overview read with every card and explanation closed and unread. No overview or explanation data is held above the boundary, so nothing else could resurrect.
- **Behavior change to note:** an Access route opened when the applied session does not list the campaign with `access.manage` now shows "Access unavailable" without reading the overview (previously it read the overview and got the server's 403). The server still authorizes every request.
- **Preserved:** while the caller remains authorized, the O-5 behavior (page, disclosure and status line continue across a non-self write); the fail-closed reloads (own membership, group scopes, failed, unapplied or overtaken in-place reads, 401); the S02-R1 focus restoration. The Access test suites now supply a bootstrap that lists their campaign with the capability (`test/accessBootstrap.ts`, `bootstrapWithAccessManage`); no assertion was changed.

**Regression evidence.**

- **Real session lifecycle** (`CampaignAccessPage.sessionLifecycle.integration.test.tsx`, now 9 tests; real `SessionProvider`, `useSessionBootstrap` and `AuthenticatedSessionBoundary`, network mocked):
  1. *The reported ordering:* the in-place session read is held until the post-write overview read has been answered **200** and rendered; the session read is then released with a bootstrap lacking `access.manage`. The test asserts the overview had been answered and was showing, then that the page becomes "Access unavailable", that no member, source, explanation or Refresh content remains, and that no explanation read follows. No overview denial is involved.
  2. *A late explanation answer:* the explanation read that follows the write is held (the explanation is "Loading"), the applied session then loses the capability, and the held answer (carrying a distinctive source) is released afterwards; it never renders and no further read is made.
  3. *Restoration:* with the capability removed and then restored through the session context, the old overview and explanations do not return: a fresh overview read is made, the card and explanation are closed and unread, and reopening reads again.
- **It fails before the correction.** With the unauthorized branch disabled (`CampaignAccessPage.tsx` forced to always render the boundary), tests 1, 2 and 3 failed (3 of 9); the other six passed, including the earlier overview-403 authority-loss test, which confirms that test could not see this ordering. `CampaignAccessPage.tsx` SHA-256 before and after the probe `65D7CCF60A4605A0AFD016FDCCB195B02CE79F523C6C920792081C9E9DC63F4F`; restored.
- **Browser re-run** on a production build of `61da59e` (same stack and method as the evidence record; see its §8): S02 37 of 37, structure/keyboard/reflow 18 of 18, S01 29 of 29. New check G11: the list is answered and shown, then the delayed session response arrives without `access.manage`, and the page becomes "Access unavailable" with no member, revelation, source or explanation content and no further explanation read. G1 (page, explanation and status line continue), G8 (own membership reloads), G9 (failed session read reloads), G10 (lost authority) and the Refresh access focus checks (G2 to G4) still pass. Focus after a write is still the page body (O-3, unchanged).
- **Not claimed:** no screen reader was run; actual browser zoom, human review and other browsers are unperformed; the integrated-head `browser` and `ax` obligations are not satisfied by this scripted C01 evidence.

**Verification (portal/ PowerShell; root for the last two).**

| Run | Result |
|---|---|
| Existing Access suites after the gate, before the fixture update | 8 suites failed: they use campaigns the fixture bootstrap does not list, so the page (correctly) showed "Access unavailable"; fixed by `bootstrapWithAccessManage`, no assertion changed |
| A broader first run in that state also showed 2 `ItemDefinitionPages.save` failures (8 s timeouts) while those Access suites were timing out; they passed in the full run, and that file was not touched |
| Lifecycle file, first run with the new tests | 1 of 9 failed: my test asserted the overview was read twice in a sequence where the session read applied first; the session read is now held until the overview is rendered (the reported ordering); rerun 9 of 9 |
| Pre-correction probe | 3 of 9 failed, restored, bytes verified |
| `src/pages/CampaignAccessPage*`, `AccessPage` | 10 files, 135 tests passed |
| First `npm test` after the fixture update | 438 files listed, 8 failed suites: eight empty files that my first, mis-pathed fixture patch had created in `portal/src`; deleted (they were untracked) |
| `npm test` (rerun) | 430 files, 5287 tests passed |
| `npm run lint`, `npm run build` | passed (existing chunk-size warning) |
| Browser re-run | first attempt 36 of 37 (G11's content check matched the write's own confirmation "Character access removed." on the status line; a harness assertion), fixtures rebuilt and run again in full: S01 29/29, structure 18/18, S02 37/37 |
| `uv run python scripts/check_documentation.py`, `git diff --check` | recorded in the handoff for the final head |
| CI | draft PR #70 on the final head, with the PR head and the tested merge commit recorded separately in the handoff |

**Remaining limitations.** A self-affecting write, a failed or overtaken in-place read, and a restored capability still start from a fresh mount (conservative). O-3 is unchanged. Screen-reader, actual-zoom, human and other-browser checks, the integrated-head `browser` and `ax` obligations, owner acceptance and the checkpoint merge remain pending; C02 and A5c were not started. Luna's re-review of this correction is pending.
