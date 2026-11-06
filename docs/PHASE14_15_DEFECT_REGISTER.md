# Phase 14/15 acceptance — defect register (CP-11)

Started 2026-10-26 for code `9ab549ddbc78cb9b5c1aac9c99f3a967112edc62`. Acceptance handoff record. Graded with the repository's rubric, [ISSUE_GRADING_RUBRIC.md](ISSUE_GRADING_RUBRIC.md): production exposure 0–3 + impact 0–3 + triggerability 0–2 + detection/recovery 0–1 + blast radius 0–1; bands 9–10 Critical, 7–8 High (both merge blockers), 4–6 Medium (merge only with an explicit, evidence-backed risk decision), 1–3 Low, 0 Informational.

**Environment basis (applies to every score):** no production deployment exists today. The credible production path is the single-instance, self-hosted Compose deployment (ADR 0012/0013) running exactly this API and portal, so reachable application behaviour counts; development-only or test-harness behaviour scores exposure 0.

**Scores below are proposed gradings for the owner to confirm. Nothing here is accepted, and no Medium item is waived (DR-9 requires the owner's explicit decision).**

## 1. Open items found or re-confirmed during CP-11 preparation

### DEF-001 — Confirmed writes that discard the outcome of the follow-up read (deferred from CP-10)

| Field | Value |
|---|---|
| Trigger / workflow | Any author (GM, Admin, Owner) performs a write that succeeds on the server, and the page's immediate re-read of the record then fails (network drop, 5xx, throttling) or is superseded. |
| Persona | GM and Admin in the callers listed below. |
| Expected | The contract CP-2/CP-10 established for Quest, Item and Claim: the mutation reports *confirmed*, the page shows "Saved. Latest data couldn't be loaded." with a read-only **Load latest**, and "done" is announced only when the re-read is `ok`. |
| Actual (by code inspection at `9ab549d`; not yet observed in a browser) | These callers `await refetch()`/`refresh()` and drop its result, so they can announce completion, and show stale content, after a failed re-read. CP-10's handoff names: `TransitionControls`, party pages, NPC portrayal, character build, event pages, `WorldSharingPage`, `SessionRunPage` clock/log hooks, `TravelSection`. A fresh grep for an `await` of a refetch whose result is unused also finds: `useDungeonCommand` (:51), `EntityLifecyclePanel` (:250, World/Item/Quest callers), `NpcRuntimePanel` (:216), `SessionLifecycleControls` (:55), `EncounterPages` (:314), `PartyMembersPage` (:132, :293), `PartyPages` (:137), `CharacterBuildPages` (:140, :252), `NpcPortrayalPage` (:86, :97), `EventPages` (:409), `SessionRunPage` (:375, :711), `WorldSharingPage` (:133), `TravelSection` (:165), `TransitionControls` (:59). Each site must be confirmed by RC-10 before it is counted. |
| Practical impact | A user sees "done" while the screen is behind the saved data. Data is not lost or corrupted; a repeat write is rejected as stale rather than duplicated. The risk is a misleading success message and a stale view of GM-controlled state. |
| Proposed rubric score | Exposure **1** (needs a failed second request immediately after a success; rare) + Impact **1** (minor degradation, no loss) + Triggerability **1** (transient failure/special timing) + Detection **1** (silent and misleading) + Blast **0** (one user/record) = **4 — Medium**. |
| Evidence | Code inspection; CP-10 handoff §"Not changed". Browser reproduction: pending RC-10 (block the re-read GET, perform the write). |
| Affected coverage | RC-10 (and RC-04…RC-08 for the already-fixed callers), tasks D2, G3, G4, H5, H9, I1, I2, I3, I4, I9, I10, J1, K4; TC-11/14/15/19/21/25/34/37/38/42–44/50/51 error-recovery assertions. |
| Original disposition (historical, as of `9ab549d`) | **Open — owner decision required (DR-9).** Either (a) fix, or (b) record an explicit risk acceptance. |
| Disposition (updated 2026-10-26) | **Owner decision: (a) fix, across all affected operations (not a partial fix).** Implemented in the portal at code commit `7990225af3305d7d7221d0daf068ae1c70199aee` (portal and docs only; no backend change). **NOT closed:** it needs Codex review, current-head CI on PR #66, and the RC-10 / affected-task retest on the reviewed head before the owner or Codex can close it. See §5 and [PHASE15_DEF001_INVENTORY.md](PHASE15_DEF001_INVENTORY.md). |
| Bounded fix handoff (if the owner chooses to fix) | Return the refresh outcome from each call site and join multiple reads with `combineRefetchOutcomes`; report `confirmed` to `useAuthoringMutation`; announce "done" only on `ok`; otherwise render `SavedRefreshFailedNotice` with a read-only **Load latest** (never re-sending the write). One focused test per site modelled on `App.knowledgeClaim.test.tsx` ("write once, read fails, retry reads only"). Gate: ruff/mypy unchanged (portal-only), portal `tsc`/`eslint`/focused `vitest`/`vite build`, current-head CI on PR #66, Codex review. Retest: RC-10 plus the affected tasks listed above. No backend change. |

### DEF-002 — Duplicate route decorator on the access-group member endpoint

| Field | Value |
|---|---|
| Trigger / workflow | Starting the API and fetching `/openapi.json` (also seen in the API start-up log). |
| Persona | Any (operator/developer-visible). |
| Expected | One `@router.post(".../access-groups/{id}/members")` registration and a unique OpenAPI operation id. |
| Actual | `src/dnd_ai/api/access_groups.py:521-526` stacks the same `@router.post(...)` decorator twice above `add_access_group_member_endpoint`; FastAPI warns "Duplicate Operation ID add_access_group_member_endpoint_campaigns__campaign_id__access_groups__access_group_id__members_post". The second registration is unreachable (first match wins). |
| Practical impact | A spurious warning and a duplicated OpenAPI entry (ambiguous for generated clients). No behavioural difference was observed. |
| Proposed rubric score | Exposure **2** (always-on registration, but the effect is cosmetic) + Impact **0** + Trigger **0** + Detection **0** (visible warning) + Blast **0** = **2 — Low**. |
| Evidence | Source lines above; warning in `stack\api_p8001.err.log`. |
| Affected coverage | None of the manual tasks. |
| Disposition | **Open — Low.** Delete one decorator (trivial, no migration); not changed in CP-11 to avoid unrequested product edits. Schedule normally or accept. |

### DEF-003 — A unit test depends on the developer's `.env`

| Field | Value |
|---|---|
| Trigger | `scripts/verify.sh full` (or `pytest tests/unit`) on a machine whose `.env` sets `DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS`. |
| Expected | `test_local_session_allowed_origins_defaults_to_dev_topology_outside_production` is independent of the developer's environment file. |
| Actual | The test sees the `.env` value (a Cloudflare origin) instead of the default and fails: `1 failed, 1204 passed`. It passes in CI (no `.env`). Already recorded in `PHASE15_VERIFICATION.md` as "the known developer-`.env` test". |
| Impact / score | Test-harness behaviour only; no production path. Exposure **0** → **Informational (0)**. |
| Disposition | Pre-existing, not a regression; this run deselected it explicitly (`unit_excluding_env_test`). Harness hardening is outside CP-11. |

### DEF-004 — Pre-existing, already-recorded noise

Recorded in plan §11 and not re-opened: Windows CRLF frozen-seed test failures; intermittent portal timing tests (8 s `findBy` waits) in local full runs; legacy adapter revocation races (documented, separately guarded by automated route/concurrency tests). Informational unless a new run shows a change. Results of this run: see the environment document §6.

### DEF-005 — A second confirmed write in the same mounted view loses its saved-but-behind notice (found by the DEF-001 browser retest)

| Field | Value |
|---|---|
| Trigger / workflow | In one mounted view, a confirmed write whose read-back failed is recovered through the **page's own Try again** (not **Load latest**); a second confirmed write whose read-back fails follows without leaving the view. Reproduced: archive a world with the read failing, recover, then restore without reloading (`retest_20261027\ga.mjs`, "DEF-005 repro"; earlier-run screenshot `shots\FAIL_op1_world_restore_saved_but_behind_notice_held_no_done.png`). |
| Persona | GM / Admin / Owner. |
| Expected | The second write shows its own "saved, but the latest could not be loaded" notice, holds the control, announces when read. |
| Actual | No notice; the held flag is lifted; the recovery announcement is lost. The write is **not** repeated and "done" is not announced early; the page-level stale state still disables the buttons. |
| Cause (code reading, to be confirmed by the fix) | `useConfirmedRefresh` keeps its `recovered` flag set while the caller's synthetic status (the "unread" message state) stays non-null, so the hook never passes through idle for the second write. Callers that keep the unread write in component state **and** have a `pageStale` / automatic recovery path are affected: `TransitionControls`, the `EntityLifecyclePanel` provider, `OrganizationMembers`, `WorldTimesPage`. `WorldTimePicker` (no `pageStale`) and callers that use the mutation's real status are not. |
| Practical impact | The user is not told the second save was confirmed but the view is behind; the view is still guarded. No data loss, no duplicate. |
| Proposed rubric score | Exposure **1** + Impact **1** + Triggerability **1** + Detection **1** + Blast **0** = **4 — Medium** (proposed; the owner decides). |
| Affected coverage | Operations 1, 2, 22 (provider), 24, 26 when two unread writes happen in one mounted view; RC-10. |
| Disposition | **Owner chose to fix (not accept).** Fixed in two steps. (1) `caa6589`: the first fix called the caller's `reset()` from a passive effect once the page's read recovered a write. Codex review found that effect could clear a newer pending or confirmed mutation, or newer unread state, started before it ran. (2) Follow-up commit (the one after `caa6589`): **recovery is now episode-specific and has no cleanup effect.** Every write has a status object of its own (a real mutation's status; for callers that keep "saved, not yet read" in their own state, the new `useUnreadWrite`, whose `mark` creates a new status per write). `useConfirmedRefresh` records recovery against that object, so a different status is a new episode and nothing settled for the previous write carries over, even when the new write says the same thing. Load latest ends only the status it was started for (`useAuthoringMutation().reset(expected)` and `useUnreadWrite().end(ended)` leave a newer write alone). Read-only recovery, receipt/version gating, the uncertain request's payload and key, scope isolation and unmount behaviour are unchanged; a recovered write is announced once. Regressions: `WorldOverviewPage.test.tsx` (archive, page Try again, restore, page Try again: one POST each), `useConfirmedRefresh.test.tsx`, and `useConfirmedRefresh.boundary.test.tsx` (a write started in the same batch as the previous write's recovery stays pending and is sent once; ending an old episode leaves a newer one alone). **Not closed:** needs Codex review, current-head CI and the browser retest. Remaining browser variants: `ga` DEF-005 repro (world archive, page Try again, restore, page Try again); the same two-write sequence for timeline archive/restore (op 2), a lifecycle step pair on a record (op 22 provider), organization status then add member (op 24) and two world-time records on the World times page (op 26); Load latest followed by a further write; and the double-press during the pending state. **Browser-retested on `88ee96a` (scripted, disposable copy; [PHASE15_DEF001_BROWSER_RETEST.md](PHASE15_DEF001_BROWSER_RETEST.md) §9):** the world archive, Try again, restore, Try again reproduction now passes, and the same two-write sequences pass for timeline archive/restore, a lifecycle-step pair (provider), organization status then add member, two world-time records, Load latest then a further write, a double press while pending, and ownership transfer / end role / allow and revoke hosting; each write is one POST, reported afresh, announced once. Not exercised in a browser: see §9.6. **Still open until the owner accepts it; the human run is unexecuted.** |
| Bounded fix handoff (superseded) | **SUPERSEDED by the reviewed fixes (see the Disposition row; Codex-reviewed `88ee96a`).** Original proposal, kept for the record only: In `portal/src/hooks/useConfirmedRefresh.tsx`, once `recovered` becomes true (after the announcement) call the caller's `reset()` from an effect so the status returns to idle and the episode state resets; the four callers pass their `reset`. Test (per caller): first write recovered through the page retry, then a second unread write on the same mounted component must show its notice, keep the control held and announce on recovery. Gate: portal `tsc`/`eslint`/focused `vitest`/`vite build`, current-head CI on PR #66, Codex review. Retest: `ga` "DEF-005 repro", RC-10 operations 1, 2, 22, 24, 26. No backend change. |

### DEF-006 — Claim save whose authoring read fails replaces the editor silently (found by the DEF-001 browser retest)

| Field | Value |
|---|---|
| Trigger / workflow | Save a claim (Knowledge → claim → Claim section → Save claim). The save succeeds; the claim's **authoring** read (`GET /campaigns/<c>/authoring/knowledge/<id>`) then fails. (The audience-safe detail read failing is handled correctly: notice, **Load latest**, no premature "Knowledge claim saved".) `retest_20261027\ex5.mjs auth`, `logs\ex5_auth.log`, `shots\ex5_auth.png`. |
| Persona | GM / Admin with `canon.edit`. |
| Expected | The same contract as the detail-read case: a saved-but-behind notice with a read-only retry, no premature "done". |
| Actual | The page header shows the new text, but the claim form is replaced by the read-only "GM and canonical information" presentation with **no notice, no retry and no announcement** (`main` has no buttons). A reload restores the editor. The save is not repeated and "done" is not announced. |
| Cause (code reading, to be confirmed) | The saved-but-behind state (`behind`) lives inside the editable form component, which unmounts when the authoring view read leaves the ready state; the page-level `lifecycleBehind` notice is set only by lifecycle steps. |
| Practical impact | The author cannot tell the save succeeded or why the editor disappeared until they reload. No data loss, no duplicate. |
| Proposed rubric score | Exposure **1** + Impact **1** + Triggerability **1** + Detection **1** + Blast **0** = **4 — Medium** (proposed). |
| Affected coverage | RC-06 and the claim-save error-recovery assertions in the Knowledge tasks (see the coverage matrix). |
| Disposition | **Owner chose to fix (not accept).** Fixed in two steps. (1) `caa6589`: the claim page keeps the authoring view through a recoverable failure (`useKeptData`), so a confirmed save whose authoring read-back fails keeps the editor, shows "Claim saved. The latest claim could not be loaded" with the live-region status and a read-only **Load latest**, holds **Save claim** until the required reads (authoring and detail) both work, removes the editor and says why when the answer is denied or missing, and offers **Try again** for an editor that never loaded. (2) Codex review found the page's dirty calculation still read the live authoring state, so an edit on the retained editor was not counted as unsaved and leaving the page was not guarded. Follow-up commit: the page's `claimDirty` is now computed against the **kept** authoring view; a denied or missing result still drops the kept view and clears the claim draft. Regressions in `App.knowledgeClaim.test.tsx`: confirmed save with a failed authoring read; edit the retained form; Load latest fails again; leaving the page shows the unsaved-changes dialog, Keep editing keeps the draft; denied/missing removes the editor and the draft and leaving is no longer guarded. **Not closed:** needs Codex review, current-head CI and the browser retest. Remaining browser variants: `gl` RC-06 authoring-read variant and `ex5.mjs auth` (500); the same with a 403 and a 404 on the authoring read (private editor and draft gone); edit-then-navigate with the guard dialog; Load latest failing again and then succeeding (the next save carries the new row version); the detail read failing alone and both reads failing; a lifecycle step on the claim with the authoring read failing. **Browser-retested on `88ee96a` (§9):** authoring read 500 (editor kept, Save held, edit guarded, Keep editing keeps the draft, failed Load latest then recovery, next save with the refreshed row version), 403 and 404 (editor and draft removed, leaving unguarded), detail-only and both-reads failures, and a claim lifecycle step whose authoring read fails. **Still open until the owner accepts it; the human run is unexecuted.** |
| Bounded fix handoff (superseded) | **SUPERSEDED by the reviewed fixes (see the Disposition row; Codex-reviewed `88ee96a`).** Original proposal, kept for the record only: In `KnowledgeClaimPage.tsx`, report the claim save's unread outcome at page level (reuse `lifecycleBehind` / `SavedRefreshFailedNotice` with a read-only retry that refetches `view`, the lifecycle and the detail) so it survives the form unmounting; keep the last good authoring view (as `useKept` does elsewhere) rather than withdrawing the editor. Test: claim save, authoring read fails, notice and retry shown, editor held, one POST, retry reads only. Gate and retest as DEF-005, plus `gl` RC-06 authoring variant. |

## 2. Blockers to the owner's run (not defects)

| ID | Blocker | Needed from the owner |
|---|---|---|
| BLK-1 | ~~No scripted evidence for imported accounts~~ **Lifted 2026-10-26**: owner pointed to the `.env` password variables; used on a disposable copy only | Further scripted scope is optional |
| BLK-2 | Human visual judgement, NVDA/Narrator, 200 % zoom, reduced-motion and 2560 px checks (TC-55) | Human run with the tools named in the companion scenarios |
| BLK-3 | TC-38 positive NPC resource variant, TC-31 deprecated claim, TC-41 attunement-limit and SR-M14 stale tab | Remain **Blocked** (no supported fixture / not repeatable); see coverage matrix §6 |

## 3. Closed earlier (kept for the record; not re-opened)

CP-4 browser-smoke findings D-1 … D-6 (review queue / item definitions 403 for a campaign-only GM, Sharing table overflow at 390 px, focus to `BODY` after permission loss) were fixed in the CP-4 range with retest evidence (commits `9b11535`, `36910ad`, `b9b166c`, `62c96dc`); they are retested here only through SR-M8, SR-M13, NV-07/08 and AX rows, as fresh coverage.

## 4. Template for new defects found in the run

Copy one block per defect. Number DEF-0nn (product) or DEF-DOC-nn (this guide's wording).

| Field | Value |
|---|---|
| ID / title | |
| Trigger and affected persona/workflow | |
| Expected versus actual | |
| Practical impact (who, what data) | |
| Rubric: exposure / impact / triggerability / detection / blast → total, band | |
| Reproduction and evidence (ledger row, screenshot path; no secrets) | |
| Affected coverage and required retest | |
| Disposition (fix / owner-accepted exception with written reason) and code SHA of the fix | |

**Change control.** An acceptance-blocking defect (High or above, or a Medium the owner will not accept) gets a *bounded fix handoff*: files and behaviour only, tests, Codex review, current-head CI on PR #66, and a list of rows to rerun. If the code SHA changes, update the ledger's "Code change log" naming which prior results still apply and which must be rerun. CP-11 does not expand into broad product work.

## 5. DEF-001 fix record (2026-10-26)

Owner decision (DR-9): **fix**, across all affected operations. Starting HEAD `52fb3de891b3d7b4e61394edbab62a1f5b51dd2d` (CP-10 code `9ab549d` plus the acceptance-handoff docs commit). Code commit: **`7990225af3305d7d7221d0daf068ae1c70199aee`** — portal and docs only; `git diff 9ab549d..HEAD` touches nothing under `src/`, `database/`, `tests/`, `foundry-module/`, `scripts/`, `.github/`, `Dockerfile` or `compose.yaml`.

**Scope found.** The register named 8 callers and listed 14 file locations "to be confirmed". The audit (56 `useAuthoringMutation` call sites plus the shared hooks) found **26 corrected operations** (inventory §4.1), covering every site in the register's list and further ones the list did not contain: encounters, the clock card, session details and archive/restore, dungeon/area commands (the shared `reload()` returned nothing), the lifecycle panel's own read (World, Item, Quest), relationship and organization roster writes, and world-time recording (page and the shared picker). Reference callers (CP-2/CP-10), navigate-away forms and the Phase 13 reload-through-loading family were assessed and not changed (inventory §4.2–4.4).

**What changed.** Each corrected caller returns the outcome of all reads that show its write to `useAuthoringMutation` (`confirmed` unless every read was applied), announces "done" only on `"ok"`, keeps the last good read instead of an error screen, holds writes that would send the stale version/token, shows `SavedRefreshFailedNotice` with a read-only **Load latest**, and announces the write when a read completes. Shared piece: `hooks/useConfirmedRefresh`. `useAuthoringMutation`, `combineRefetchOutcomes` and the backend are unchanged.

**Verification actually performed (portal only; nothing else was applicable).**

| Check | Result |
|---|---|
| `tsc -b` | PASS |
| `eslint .` | PASS |
| `vitest run` (full portal) | **363 files, 3,527 tests passed** (`9ab549d` baseline: 360 files, 3,485 tests) |
| `npm run build` (`tsc -b && vite build`) | PASS (the existing >500 kB chunk warning only) |
| New or tightened regression tests against the **previous** source (non-test files stashed) | **33 fail**, the other 543 tests in the same 22 files pass; restored afterwards |
| Backend (`ruff`, `mypy`, `pytest`) | **Not rerun**: no backend, migration or CI-configuration change since `9ab549d`; the `9ab549d` results in the environment document §6 apply to the backend unchanged. CI reruns them |
| Browser / database | **Not performed.** No browser or database mutation was made in this work; `dnd_ai` and the acceptance databases were not touched |

**Not fixed here (as instructed).** DEF-002 (duplicate route decorator) and DEF-003 (`.env`-dependent unit test) are untouched. Neither the fix nor its tests depend on them; DEF-003 still makes `scripts/verify.sh full` fail locally on a machine whose `.env` sets `DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS`.

**Browser retest (2026-10-26, on the Codex-reviewed candidate `38d2865`).** Scripted real-browser retest done; results, the operation-by-operation evidence map and the remaining coverage are in [PHASE15_DEF001_BROWSER_RETEST.md](PHASE15_DEF001_BROWSER_RETEST.md). Every exercised operation wrote once, kept the page, explained "saved, but the view is behind", announced no premature "done", held version-dependent controls and recovered by a read; permission loss removed private content. Two residual defects were found (DEF-005, DEF-006, above). Owner acceptance and the human run remain pending, so **DEF-001 stays Open — fix implemented and browser-retested by script; not accepted**.

**Still required before DEF-001 can be called closed.** (1) Codex review of the diff and of inventory §4.4 (the reload-through-loading family was assessed as unaffected and left alone). (2) Current-head CI on PR #66. (3) Retest on the reviewed head: RC-10 (rewritten for the 26 operations) and RC-04 … RC-09, the tasks and cases listed in the register's "Affected coverage" plus the additions in the environment document §9, in a real browser. Until then DEF-001 stays **Open — fix implemented, unverified in a browser**, and no ledger row changes state.


## 6. Working-campaign repair findings (2026-10-30)

These are findings from the owner-authorized repair run on working `dnd_ai` (portal/API 5173/8000), not results from the clean acceptance database. Full evidence, UI-versus-database repair accounting, and limits: [Step G repair report](PHASE14_15_STEP_G_REPAIR_REPORT.md).

### DEF-007 — Future party membership is treated as current before its start

| Field | Value |
|---|---|
| Trigger / persona | As `player_b`, open Tobin's Parties section while the campaign clock is Meeting. Saved intervals are Arrival → Meeting and Descent → open-ended. |
| Expected | G4: no current party at Meeting; the rejoin becomes current at Descent. |
| Actual | UI shows Parties (1) and The Lantern-Bearers. Bootstrap authorizes that party despite zero stored intervals containing the Meeting sort key. The GM membership page also calls the future open-ended stint current. |
| Confirmed cause | `queries/party_members.py`, `queries/parties.py`, `queries/bootstrap.py`, and `api/access.py::resolve_party_perspective` check an absent end rather than containment of the effective campaign clock. |
| Impact / rubric | Incorrect current-party context and premature party-perspective authorization. No party-knowledge disclosure was exercised because this instance has no knowledge items. Severity/rubric remains unscored pending owner triage. |
| Reproduction / evidence | `ui_db_repairs_20261030/ui_verification.json`, `after_repairs_read_models.json`, `final_database_verification.json`, `player_b-future-membership-still-current.png`, under the external CP-11 evidence directory. |
| Coverage / retest | G4 / TC-06 / TC-21. Check Arrival, Meeting and Descent boundaries, finite intervals before their end, future open-ended intervals, bootstrap/read consistency and the per-request party-perspective authorization guard. |
| Disposition | **Open — confirmed requirement/implementation mismatch.** The data schedule is repaired. No database workaround removed the required future rejoin. A bounded application change or explicit requirement decision is needed; no source change or acceptance decision was made. |

**DEF-007 disposition update — B1-DEF7a (server) implemented, awaiting review; not accepted.** The commit titled "fix: effective-time party membership on the server (B1-DEF7a)" on `phase15/completion`, after `529bd4b`, replaces every currentness test that looked for an absent end with containment of the effective campaign clock in the stored half-open period (join included, leave excluded) through one predicate and one clock resolved per request (per campaign in the bootstrap): bootstrap `authorized_parties`, `resolve_party_perspective` and its consumers, Knowledge's implicit eligible parties, the character Parties list, the member roster, GM membership rows and the GM party inventory. With no effective clock, current membership is **undetermined** (no Current, Ended or Upcoming label; no membership-derived access), while GM management, history and independently authorized access are unchanged. Additive read fields: `current_time_set` (bootstrap campaign entry and member-preview perspectives), `as_of` and `clock_unset` (character Parties, roster, GM members, party inventory) and per-row `period_status` (GM members); `is_current` is retained and now means `period_status == "in_effect"`. Clock inheritance is not membership inheritance: a branch evaluates its own timeline-scoped rows against its inherited, branch-bounded clock. No migration. Automated tests recorded in the ledger; scripted API retest, browser/human retest (G4 / TC-06 / TC-21) and owner acceptance are **pending**. DEF7b (portal presentation) and DEF7c (stale-selection recovery) are **not** done.

**DEF-007 disposition update — B1-DEF7b (portal presentation) implemented, awaiting review; not accepted.** The portal consumes the DEF7a metadata: the GM party page groups memberships as Current, Upcoming and History from the server's `period_status` (no date arithmetic in the portal), with a clock-unset campaign listing every membership as "Members (current status unknown)" and never as History or Upcoming; the read-only roster, the character Parties disclosure, the GM party inventory and the member-preview party selector say current membership cannot be determined because campaign time has not been set (no count, no "No current members"/"No party memberships"), pointing at Campaign Home only for `canon.edit`. Management actions follow their commands, not the temporal label: **End membership** is offered for a membership with no recorded end (including an upcoming or undetermined one) and never for a finite one. Stale-selection recovery (DEF7c) and a travel-time policy are not implemented. DEF-007 remains open pending review and the human retests.

**DEF-007 disposition update — B1-DEF7c (stale party-perspective recovery) implemented, awaiting review; not accepted.** The portal re-reads eligibility (the existing session bootstrap refresh, coalesced) in the background after a confirmed clock advance or correction, membership add or end, or party archive or restore, and recovers from a party-scoped standard not-found in the Quest and Knowledge list and detail reads with one eligibility refresh per request episode: a party the fresh bootstrap no longer authorizes is dropped from the selection and the address and the no-party view is read once; a party still authorized keeps the ordinary unavailable result; a failed refresh offers a retry and is never read as revocation. The Knowledge public-only view no longer shows the membership warning. No backend, authorization or travel-command change. External changes are discovered on the next failed read only (no polling or push). Browser/human and scripted API evidence are still pending, and DEF-007 remains open.

**DEF-007 disposition update — B1-DEF7c session-read race corrected, awaiting review; not accepted.** Review found that an older shared bootstrap refresh could publish authenticated data after a newer reload found the session unauthenticated, after an expiry, or after a newer read. Session reads now carry start-order tickets and only the current owner may publish; superseded reads (successes and failures) resolve `refresh` as not applied, and party recovery treats not applied as uncertainty (a retry), not as revocation. Separate and unchanged: the recovery-map eviction limitation and the Knowledge detail post-save re-read limitation. DEF-007 remains open.

**DEF-007 disposition update — B1-DEF7c review corrections (idle-check ownership, startup-preference feedback, abort contract), awaiting review; not accepted.** The idle-expiry check now takes a session-read ticket and acts only while it owns its result (it is also aborted with its effect); a confirmed startup-preference PUT whose refresh is not applied is reported as saved-but-unconfirmed, no longer as "denied / nothing was saved"; the refresh abort/not-applied contract is documented and tested with realistic `AbortError` rejections. All other `refresh` consumers were audited and none treated `false` as a refusal. Recovery-map eviction and the Knowledge post-save re-read remain separate follow-ups. DEF-007 remains open.

**DEF-007 follow-up U1 (open, separate): party travel still uses the open-end rule.** `commands/travel.py` expands a party to its open-ended memberships regardless of the travel time, and the portal Travel preview (`TravelSection`) reads the same open-end fact through the GM members rows. This was deliberately left unchanged in B1-DEF7a so the command and its preview keep matching; a not-yet-started open-ended membership therefore still travels with the party. A later small fix should use the shared predicate with the travel time's `sort_key` (the effective travel-time question) and change command and preview together. Temporal membership behavior is therefore **not** claimed fully repaired.

**Correction to U1 (B1-DEF7b, found in review of B1-DEF7a).** The statement above that the portal Travel preview "reads the same open-end fact" and that command and preview "keep matching" was **false** as of B1-DEF7a: the preview filtered `is_current`, which after DEF7a means effective at the campaign clock, while the unchanged command moves memberships whose stored end is absent. The test comment that said the preview "keys on `left_at`" was equally inaccurate. The original text is kept as the record of what was claimed. B1-DEF7b repairs the **preview only**: it now selects the party's members with `left_at === null` (the command's condition, `effective_to_world_time_id IS NULL`), so a future open-ended member is listed (marked "party membership starts later" from the server's `period_status`), a finite member in effect at the campaign time is not, an ended finite member is not, an ordinary current open-ended member is, and a campaign with no clock lists open-ended members under the same operation authority. `commands/travel.py` is untouched. "Current members" and "Characters this travel will move" are now explicitly different sets under this legacy rule; the preview says it is not checked against the campaign time or the travel time. A deliberate travel-time policy (command and preview together) remains the open follow-up U1.

### DEF-008 — A future-dated organization status is immediately displayed as Now

| Field | Value |
|---|---|
| Trigger / persona | GM, Council → Members and offices: clock Meeting; set Dormant with When = Descent. |
| Expected / decision needed | Establish whether the card means effective status at the campaign clock or the latest recorded status. The guide is time-oriented but does not explicitly settle this card's policy. |
| Actual | The save succeeds, records an event/effect at Descent, and immediately displays Now: dormant while the clock remains Meeting. |
| Cause | `queries/organization.py` reads `campaign.organization_state` directly without resolving status at the effective campaign clock. |
| Evidence | Step G repair report; Set status/read-back in `ui_actions.jsonl`; event/state rows in `after_repairs_database_snapshot.json`; `council-members-and-status-after-ui.png`. |
| Impact / rubric | Potentially misleading fictional-time presentation. Unscored observation pending semantics triage; not claimed as a failed status save or proven acceptance blocker. |
| Disposition / retest | **Open for triage.** Decide effective-time projection versus latest-recorded labeling, then retest G7 / TC-36 and the status event explanation. No chronology-changing database workaround or product code change was made. |

### DEF-DOC-01 — G6 requests a restore reason that the relationship UI cannot collect

| Field | Value |
|---|---|
| Expected | G6: restore the General relationship with a reason. |
| Actual | Restore relationship immediately submits; no reason field or confirmation collects one. Family and General restoration both work, with empty ordinary restore audit reasons. |
| Evidence | Relationship restore actions and snapshots in `ui_actions.jsonl`; `archive_restore_audit` in the final database snapshot. |
| Disposition | **Open — UI/documentation mismatch.** Add reason entry or amend the guide. No audit row was changed to imply a reason had been entered through the UI. Human results are unchanged. |

## 7. Source-confirmed privacy findings (2026-11-01)

Found by the Phase 14/15 app-interaction investigation (planning ID ENC-01; investigation D6.4, S05, G02) and repaired in Batch 1 checkpoint B1-1. Not an observed live disclosure: no owner data was read.

### DEF-009 — The campaign encounter detail read ignores the caller's audience

| Field | Value |
|---|---|
| Trigger / persona | Any `campaign.view` holder without `canon.edit` calls `GET /campaigns/{campaign_id}/encounters/{encounter_id}`. |
| Expected | ADR 0016: GM_ONLY fields omitted without `canon.edit`; participants and references limited to what the caller may discover; unstarted preparation not readable. |
| Actual (source) | The route returned `summary` and turn `notes` (both GM_ONLY), `pending` preparation rows, every participant's entity id, `location_id`, `resulting_event_id` and combat-action `item_instance_id` without a discoverability check. An existing test asserted the player-visible notes as intended. |
| Confirmed cause | `get_encounter_view` was written under a "no audience filtering" assumption and never updated after `notes`/`summary` were classified and `pending` rows were added. |
| Impact / rubric | Potential disclosure of GM prose, undiscovered actors and unstarted GM preparation to members. Unscored pending owner triage. |
| Evidence | Source confirmation: `api/encounters.py`, `queries/encounter.py`, `domain/data_classification.py`. Automated (2026-11-01, local PostgreSQL 18, not CI): `tests/database/test_api_encounters_query.py`, 13 passed; with the projection disabled 6 of them fail. **Scripted API retest: not executed.** Owner acceptance: not given. |
| Fix | Projection inside `get_encounter_view` for non-`canon.edit` callers: started encounters only (`aborted` counts as started only with a `resulting_event_id`), `summary` and `notes` null, hidden participants and their turns removed, dense per-round `turn_order`, location/event/item ids nulled unless discoverable. Editor output unchanged. Fixed in the commit titled "fix: audience-project the campaign encounter detail read (DEF-009 / ENC-01)". |
| Disposition | **Open — fix implemented and automated-tested; scripted API retest and owner acceptance pending.** Coverage variant `22.encounter-member` (Unexecuted). |
| Follow-up, not fixed here | (1) `GET …/integration/external-systems/{id}/sync-state?target_encounter_id=` (`api/integration.py`, `queries/integration.py`) returns sync status for an encounter id under `campaign.view`. (2) Character detail's timeline-scoped `active_encounter_id` (`queries/character.py`) — **implemented in P03-A slice A0, see "A0 evidence" below**. (3) `location_id` of a dungeon area follows the World Explorer rule, not campaign dungeon discovery state. (4) A started-aborted encounter whose abort event is physically deleted reads as unstarted for members (`resulting_event_id` is `ON DELETE SET NULL`; fails closed). Inventory for P03-A. |

**A0 evidence (P03-A slice A0, `active_encounter_id` part of follow-up 2; local, not CI; independent review and CI pending).**

- Change: `get_character_view` takes a required `campaign_id` and an `encounter_reader`. The id is returned only for an `active` encounter of that campaign, selected with the campaign filter applied before `ORDER BY … LIMIT 1`. Audience readers must also pass the shared `member_may_read_encounter` rule and be able to discover the character (`discoverable_entity_ids`); `canon.edit` holders read unfiltered, as in the encounter detail route. A caller with no audience context (AI context assembly) gets `null`. No schema, API-shape or portal change; encounter detail untouched.
- Callers traced: portal and Foundry `encounter_read` share `get_character_endpoint` and the same user `AccessContext` (campaign from `access.campaign_id`); AI NPC context has the assignment campaign but no `AccessContext`, so its reference is suppressed.
- Behavior changes: a campaign-less active encounter is no longer returned (existing test updated to pass `campaign_id`); AI NPC context `active_encounter_id` is now always `null`.
- Limit: a full-tier reader always discovers the character (`character.view_full` and `canon.edit` are discover capabilities), so "same-campaign active encounter the full-tier reader cannot discover" cannot be built through the API. The withheld case is covered at query level with an audience that hides the character.

## 8. Found by the P02-7e review (2026-11-04)

Source-confirmed by reading `InvitationsSection.tsx`, `useCreateCampaignInvitation.ts` and `CampaignInvitationsPage.tsx`; **not observed in a browser**. Pre-existing: P02 did not change these files. The proposed grading is for the owner to confirm; nothing here is accepted.

### DEF-010 — Leaving the Invitations page can abandon an accepted issue response and lose the one-time token

| Field | Value |
|---|---|
| ID / title | DEF-010 — Invitations issue operation is not owned across departure |
| Trigger and affected persona/workflow | A GM or Admin issues an invitation on `/app/:c/access/invitations` and leaves the page (breadcrumb, Access tab, Navbar, Back) while the request is pending, or after the token is shown. |
| Expected versus actual | Expected: the page asks before a departure that would abandon a pending write and never discards an accepted response; any recovery of the one-time token is limited to the same currently authenticated and authorized issuer and campaign, stops on logout, a session or owner change or loss of `access.manage`, and does not retain a bearer token beyond that boundary. Actual (source-confirmed): the section has no guard or hold; `useCreateCampaignInvitation` aborts on unmount and ignores a response that arrives after the abort, and its unmount cleanup clears the reserved idempotency key; the shown token lives in the page's state and is gone after departure. |
| Practical impact (who, what data) | The invitation may exist on the server while the issuer never sees its token. **Source-derived:** a matching-key replay returns the sanitized body (invitation id, no token) and the server stores only the token hash, so the key cannot recover the token; a fresh key (or none) creates another invitation, and the reviewed schema (migration 080) has no uniqueness on `invited_email` and the create command does not look for an existing pending invitation. An outstanding invitation can be revoked by id. **Owner decision remaining:** revoke-and-reissue and duplicate handling. No data is exposed. |
| Rubric: exposure / impact / triggerability / detection / blast → total, band | Proposed: 2 (normal path, narrow timing) + 1 (minor degradation, recoverable by revoking and reissuing) + 1 (needs authenticated issuer and timing) + 1 (silent) + 0 (one invitation) → **5, Medium**. |
| Reproduction and evidence | Source reading only. No browser reproduction; no test reproduces it. Follow-up F-1 in [the reconciliation record](PHASE14_15_P02_RECONCILIATION_2026-11-04.md) §7 holds the acceptance criteria. |
| Affected coverage and required retest | `InvitationsSection.test.tsx`, `CampaignInvitationsPage*.test.tsx`; the Access navigation tests in `App.setupAccessNavigation.test.tsx` do not cover it. Retest: issue then depart (pending and settled), Stay/Leave, late response, replay wording. |
| Disposition | Open. Classified by the P02-7e code review (conversation-supplied) as a nonblocking, **pre-existing** limitation. Not fixed in P02-8 or its correction (an invitation recovery redesign needs the owner decisions above). Recovery criteria, including the authorization boundary, are follow-up F-1 in [PHASE14_15_P02_RECONCILIATION_2026-11-04.md](PHASE14_15_P02_RECONCILIATION_2026-11-04.md) §9. |

## 9. Found while implementing the D3 ownership gate (2026-11-06)

Source-confirmed while tracing the owner-granting paths for the P03-A A1 ownership gate. **Pre-existing, not changed by the gate, not fixed there.** Gradings are proposed for the owner to confirm. The read-only preflight `scripts/preflight_campaign_owner_gate.py` found no affected row in the local development database (2026-11-06).

### DEF-011 — Ownership transfer to a member whose owner assignment expired

| Field | Value |
|---|---|
| ID / title | DEF-011 — `transfer_campaign_ownership` treats an expired, unrevoked owner assignment as current |
| Trigger and affected persona/workflow | A campaign owner transfers ownership to a member whose built-in owner assignment carries a past `expires_at` and was never revoked. Reachable: `POST …/memberships/{id}/roles` accepts `expires_at`. |
| Expected versus actual | Expected: the target gets a live owner assignment. Actual (source): the existence check filters only `revoked_at IS NULL`, so the transfer returns `assigned: false` and, with `relinquish_own_ownership`, still ends the caller's own assignment. Inserting a fresh row would instead hit `ux_membership_roles_active` because the expired row stays unrevoked. |
| Practical impact (who, what data) | A campaign can lose its only live owner while the response says nothing was assigned. The commit-time retention rule refuses (400) only when no other `access.manage` holder remains; with one, the campaign is left without an owner. No data is disclosed. |
| Rubric: exposure / impact / triggerability / detection / blast → total, band | Proposed: 1 + 1 + 1 + 0 + 0 → **3, Low**. |
| Reproduction and evidence | Reproduced 2026-11-06 on `f784cc4` by `tests/database/test_campaign_owner_expired_recipient.py` (local PostgreSQL 18): with the recipient's owner row expired and unrevoked and a custom `access.manage` holder present, a relinquishing transfer returned `assigned: false, relinquished: true`, the caller's assignment was revoked, and the retention rule did not refuse. Preflight counts expired unrevoked owner rows (0 locally). |
| Affected coverage and required retest | `test_campaign_owner_expired_recipient.py` (6 tests: relinquishing and non-relinquishing replacement, repeat, live recipient unchanged, ineligible recipient refused atomically, recipient ended first without a deadlock) plus the owner-gate and lock-order suites. |
| Disposition | **Fixed** (this checkpoint, local commit, awaiting independent review). `transfer_campaign_ownership` distinguishes a live owner row from an expired, unrevoked one. It locks the recipient's expired owner rows before the recipient's membership row (the order `end_campaign_membership` uses), closes each through `revoke_membership_role`, then assigns a live row, so the recipient ends with exactly one live owner assignment or the whole transfer is refused and rolled back (for example 409 when the recipient's membership ended) with the caller's assignment untouched. Only a live row counts as "already an owner". The single audit row gains `replaced_expired_assignment`; `relinquished` still means only the caller's own ownership. No schema change. |

### DEF-012 — Recovery cannot restore an owner when a custom role is the only access manager

| Field | Value |
|---|---|
| ID / title | DEF-012 — recovery and the stranded report look for any `access.manage` holder, not an owner |
| Trigger and affected persona/workflow | An administrator runs `recover_campaign_access_manager` for a campaign whose only non-expiring `access.manage` holder is a custom role and which has no live built-in owner. |
| Expected versus actual | Expected: the administrator can restore an owner. Actual (source): the precondition (`commands/recovery.py`) and `queries/stranded.py` treat the custom manager as sufficient, so the campaign is neither reported as stranded nor recoverable. |
| Practical impact (who, what data) | The campaign permanently lacks owner-derived authority (including `character.reveal` once A1 lands). The database retention rule (`security.campaign_has_access_manager`, migration 080) guarantees an access manager, not an owner. No data is disclosed. |
| Rubric: exposure / impact / triggerability / detection / blast → total, band | Proposed: 0 (no application path writes custom role capabilities) + 2 + 1 + 0 + 0 → **3, Low**. |
| Reproduction and evidence | Source reading; the preflight's `active_campaign_without_live_owner` count is 0 locally. |
| Affected coverage and required retest | Add a recovery test with a custom manager and no owner. |
| Disposition | Open follow-up, to be resolved before any application path can grant `access.manage` to a non-owner role. |
