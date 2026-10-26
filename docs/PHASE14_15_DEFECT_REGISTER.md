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
| Disposition | **Open — owner decision required (DR-9).** Either (a) fix, or (b) record an explicit risk acceptance. |
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
