# Phase 14/15 integration and consolidation plan

Date: 2026-10-24 (America/Chicago). **Planning only.** No implementation, merge, migration, application-data change, staging, commit, push or PR was performed while preparing it. This dated plan is retained as CP-11's decision and scope history; its initial-state tables and closing working-tree snapshot are historical, not current.

Inputs: `PHASE14_15_TESTING_ROLES_REFACTOR_AUDIT.md` (dated baseline, 2026-10-23), `docs/PHASE14_15_MANUAL_TESTING.md`, `docs/PHASE15_MANUAL_ACCEPTANCE.md`, `docs/PHASE14_VERIFICATION.md`, `docs/PHASE15_VERIFICATION.md`, `docs/ISSUE_GRADING_RUBRIC.md`, `docs/PLANv2.md` (authoritative roadmap; Phases 15–22), `docs/ENTITY_LIFECYCLE.md` §3.3, `docs/DEVELOPMENT.md` §10, and from `origin/feature/scoped-role-model`: `docs/adr/0020-scoped-system-world-and-campaign-roles.md` and `docs/SCOPED_ROLE_IMPLEMENTATION_PLAN.md` (§3 decisions, §11 checkpoints, §14 owner decisions, §16 implementation record and amendments). No `AGENTS.md` exists; `CLAUDE.md` governs.

Conventions in this plan: **CP-n** = checkpoint; **DR-n** = decision-register entry (§10); **D1–D7** = the audit's graded defects; **C1–C10** = the audit's consolidation opportunities; **TC-nn** = manual guide cases; **SR-Mn** = new scoped-role manual scenarios (§8.3). "Proposed default" always means *not yet approved*.

---

## 1. Verified starting state and changes since the audit

### 1.1 Repository

| Item | Verified 2026-10-24 | Change since audit |
|---|---|---|
| Branch / HEAD | `phase15/completion` @ `f0aae3b94e49341545c035df754d4cc1be5e30a7` (2026-10-23 22:02 CT) | None |
| Remote refs (after `git fetch origin`) | `origin/phase15/completion` = HEAD; `origin/main` = `60d5bc9`; `origin/feature/scoped-role-model` = `07dcece` (2026-10-07). No local feature branch. | None |
| Merge base | `c1b7038` (campaign-derived world visibility + `world_viewer`, migration 136) | None |
| Divergence | 97 current-side commits; 10 feature-side (incl. sync merge `76a54dc`, which brought current work only up to `c1b7038`) | None |
| Overlap | 37 paths changed on both sides | — |
| Textual conflicts | Dry-run `git merge-tree --write-tree` (no ref, index or working-tree change): **9** — `CreateAccountPanel.tsx`, `EntityLifecyclePanel.tsx`, `PortalSidebar.tsx`, `CampaignWorldPage.tsx`, `types/bootstrap.ts`, `api/local_auth.py`, `api/relationship_authoring.py`, `api/world_explorer.py`, `tests/scenario/test_phase15_acceptance_guards.py`. The other 28 overlaps auto-merge and still need **semantic** review. | New measurement |
| Migrations | Current head `136_world_viewer_role`. Feature adds `137_system_roles` → `138_world_roles_and_use_grants`, linear from 136; no id collision. | None |
| `lock_authoring_scope` call sites | 30 at base, 30 at HEAD, 30 on feature: no new world-definition writer was added after divergence. The feature makes `world_capability` a required argument, so a missed caller fails `mypy`. | New measurement |
| Largest semantic overlaps since base | `api/knowledge.py` +540 lines, `api/characters.py` +208, `commands/world_relationships.py` +108; new current-side backend readers `queries/character_relationships.py`, `queries/session_travel.py`; ~118 new non-test portal modules (World/Knowledge/Quest/Item/Session-run workspaces, staged navigation, kept-resource hooks) that the feature never saw. | New measurement |
| Worktrees | main checkout; `C:/Users/nemes/dnd_ai-phase13` (`phase13/ui-foundation`). The feature plan's `dnd_ai-scoped-roles` worktree is no longer registered. | — |
| CI trigger | `.github/workflows/ci.yml` runs only on push to `main` and PRs to `main`. A final-head CI run therefore needs an owner-authorized PR to `main` (or a trigger change). | New measurement |

### 1.2 Working tree (must be preserved)

```
 M docs/PHASE14_VERIFICATION.md        (+2)
 M docs/PHASE15_MANUAL_ACCEPTANCE.md   (+4/-2)
 M docs/PHASE15_VERIFICATION.md        (+8/-4)
?? PHASE14_15_TESTING_ROLES_REFACTOR_AUDIT.md   (mtime 2026-10-23 23:07)
?? docs/PHASE14_15_MANUAL_TESTING.md            (mtime 2026-10-23 22:22; 40 [x], 18 [ ]; result table and run ledger blank)
```

The three tracked modifications were the owner's uncommitted edits when this plan was prepared. No checkpoint may overwrite them. The owner later explicitly directed that needed acceptance records and these edits be committed; that later instruction supersedes the original no-stage guidance.

### 1.3 Database (read-only check)

`current_database=dnd_ai`, PostgreSQL 18.4, 127.0.0.1:5432, `transaction_read_only=on`, revision **`136_world_viewer_role`**, 3 worlds, 5 campaigns, latest `audit.change_log.recorded_at` **2026-10-23 22:19:45 CT** — before the audit's timestamp, so no audited write occurred since the audit observed the R fixtures. The audit's fixture identities (§4.2: R World `c350fdd8…`, C `05223b1d…`, T `57d323ff…`, Play `ad1a4af7…` completed, Next `8ca2998e…` running, Hero A `41c7953f…`, Hero B `664c9f0d…`, Archivist `c2ba765d…`, item instance `3064f6f8…` destroyed) are taken as current without re-derivation.

### 1.4 Audit claims re-confirmed at HEAD

| Claim | Evidence at HEAD |
|---|---|
| Session `/edit` already redirects | `App.tsx:477` → `LegacySessionEditRedirect` (`CampaignSessionDetailPage.tsx:48`) |
| Participant chooser defaults to Guest, misexplains mismatch | `SessionRunPage.tsx:442` (`useState("guest")`), `:64` (`session_participant_invalid` → "only published characters can") |
| Inventory panels vanish on non-ready states | `InventoryPanels.tsx:61`, `:85` (`return null`) |
| Knowledge browse forces archive exclusion | `api/knowledge.py:629` `include_archived=False` |
| Clock advance links previous clock event as "cause" | `commands/campaign_clock.py:184` (`cause_event_id = own[2]`) |
| `narrative.event_causes` already supports `cause_event_id` **or** `cause_description`, multiple rows per event | migration `057_narrative_events.py` (no unique on `event_id`) |
| Settings swallow bootstrap refresh failure | `CampaignSettingsPage.tsx:107,117` |
| Viewer relationship = discover + summary | `domain/access.py:198–199`; same matrix seeded by migration 114 |
| Owner inventory already permitted server-side | `api/characters.py:670` (`canon.edit` or `character.view_full`, via `api/access.py:340 resolve_character_view_tier`) |
| Rubric | `docs/ISSUE_GRADING_RUBRIC.md`, copied from the supplied `.tmp/issue-grading-rubric(2).md` (SHA-256 `67ebcaa6…7fe3`); it matches the audit and feature plan Q14. A different `.tmp/issue-grading-rubric.md` also exists; it is **not** the supplied rubric. |

### 1.5 Interpretations carried forward (from the request; not re-litigated)

- 40 cases are *tester-marked executed*, not passed. Nothing in this plan relabels them.
- DB differences may be substituted fixtures, partial variants or later legitimate operations.
- The PC/NPC mismatch is a chooser/error defect; server enforcement exists (zero mismatched rows DB-wide).
- Owner inventory read already exists server-side; the defect is reachability and silent failure.
- Session `/edit` already redirects; no edit implementation is to be removed.
- A dedicated Run Session activity stays.
- Archive-reference behaviour is documented policy (`ENTITY_LIFECYCLE.md` §3.3); the guide disagrees.
- Current fixes for drafts, safe readers, named travel, retries and saved-vs-refresh feedback are preserved.

### 1.6 One sequencing change to record

ADR 0020's accepted Q10 said scoped roles land *after* the Phase 15 merge and before Phase 16. This request directs integration **into `phase15/completion`** before Phase 15 closes. That is the owner's own revision of Q10's sequencing, not a reopened decision; CP-4 records it as an ADR 0020 amendment. Likewise, the saved Phase 15 workflow ("one commit per checkpoint on `phase15/completion`, no merges") gets one deliberate exception: the feature merge itself (§3.2).

---

## 2. Requirements-to-checkpoint matrix

| Requirement / finding | Source | Checkpoints | Decisions |
|---|---|---|---|
| Evidence baseline, disposable targets, fixture repair path | Audit WP-0, §4 | CP-0 (record), CP-11 prep (repair) | DR-8 |
| **1 Events** explain party join, build activation, clock change (labels, before/after, effective vs recorded time, session/cause/correction links) | D2, C6, C7 | CP-9a | DR-6 |
| Optional validated gameplay cause + member-safe explanation for future clock advances | D2 §5A | CP-9b | DR-4 |
| **2 Participants** compatible PC/NPC/Guest options, accurate rejection | D3, C5 | CP-1 | — |
| Shared roster on detail/run/review; controls gated separately | D6, C5 | CP-3 (GM), CP-8 (members) | DR-3 |
| **3 Errors** receipt vs refresh; denied/empty/loading/unavailable/recoverable distinct; retry safety | D1, C8 | CP-2 (contract + representative callers), CP-4d (permission loss), CP-10 (remaining callers) | — |
| **4 Archived Knowledge** Active/Archived/All, server filter, keyset, URL state | D5 | CP-7 | DR-1, DR-5 |
| Guide TC-10/TC-31 expectation vs §3.3 policy | Audit §5E | CP-11 docs | DR-1 |
| **5 Inventory** reachable for full-tier readers via character workspace | D4 | CP-5 | — |
| Viewer inventory as narrow read extension | Owner request; audit §5F | CP-6 | DR-2 |
| **6 Navigation** coherent character record; session detail ↔ Run | D7, C3 | CP-3, CP-5, CP-10 | — |
| **7 Scoped roles** schema, authority, revocation, bootstrap, accounts, sharing, recovery, exceptions, Editor/Reviewer, readers | Feature branch; audit §6 | CP-4 (I-0…I-6) | DR-7 |
| Current workspaces built after divergence (WorldRecordWorkspace, KnowledgeClaimPage, QuestEditor, AuthoringEditLink, new readers, relationship writes, kept drafts, route manifest) | Audit §6.4 items 1–7 | CP-4b, CP-4c, CP-4d, CP-4e | — |
| E2 `origin_notes` cross-campaign check | Feature D8 | CP-4b | — |
| Per-record server-aligned eligibility | C1 | CP-4c | — |
| Audience-safe projections and reference labels | C2 | CP-3, CP-8, CP-9a | — |
| Lifecycle/staged navigation consistency | C4 | CP-4d (Editor/Reviewer actions only) | deferred remainder §11 |
| API client / option catalogs | C9 | CP-1 (participant role catalog only) | deferred remainder §11 |
| Large-module extraction | C10 | CP-1, CP-3, CP-4d, CP-10 (bounded) | deferred remainder §11 |
| Populated upgrade, lossy downgrade, clean install, offline deployment | Audit §6.2 | CP-4f, CP-11 | — |
| `TravelSection.arrivedText` stderr in a mocked test | Audit §2.3 | CP-2 (check the mock's receipt shape only) | — |
| ADR reference hygiene ("0019" docstrings that mean 0020) | Audit §6.3 | CP-4a | — |
| Final acceptance, AT/responsive, clean deployment, final-head CI | Audit WP-8 | CP-11 | DR-9 |

---

## 3. Scoped-role integration strategy

### 3.1 Principles

1. Integrate **from current HEAD**, never by resetting current work onto the feature tree. Current workspaces win on presentation; the feature wins on authority semantics; where both changed one contract, both behaviours must survive.
2. Ship **schema + API + portal together**. No checkpoint is deployed (to any shared DB) with only part of the authorization change.
3. Prior feature-branch test results (`27db91d`, §16.6) are not evidence for the integrated tree.
4. Accepted decisions are implemented as accepted. Branch defaults are implemented as defaults and listed for one confirmation (DR-7) before the integration branch reaches `phase15/completion`.

### 3.2 Exact branch strategy

| Step | Action | Review boundary |
|---|---|---|
| 0 | Finish Batch A/B (CP-1–CP-3) on `phase15/completion` as ordinary checkpoint commits, so the integration starts from a stable tree. | — |
| 1 | `git worktree add ../dnd_ai-roles-integration -b integration/scoped-roles phase15/completion` (new sibling directory; existing worktrees untouched). Run its API/portal on 8001/5174 against named disposable DBs only. | — |
| 2 | **I-0** `git merge --no-ff --no-commit origin/feature/scoped-role-model`; resolve the 9 conflicts keeping both sides' intent; make `ruff`, `mypy src`, `tsc` pass with the minimum edits; commit "Merge feature/scoped-role-model (conflict resolution only)". | Reviewed with `git show --remerge-diff <merge>`, which shows only the resolutions. Tests may fail here; the failures are listed in the commit body. |
| 3 | **I-1 … I-6** (CP-4a–f) as separate commits on `integration/scoped-roles`, each with its focused tests and docs. | One review per commit; behaviour-level review against §5 tables, not file-diff only. |
| 4 | If `phase15/completion` must move meanwhile (urgent fix), commit there and `git merge phase15/completion` into the integration branch; never rebase the integration branch (it contains a merge). | — |
| 5 | When CP-4 completion criteria pass, confirm DR-7, then on the main checkout: **stop the owner's 8000/5173 servers first** (§7.3), `git merge --ff-only integration/scoped-roles`. `phase15/completion` thus receives the feature merge plus I-1…I-6 as normal history. | Owner approval of the fast-forward. |
| 6 | CP-5 onward continue on `phase15/completion` (one commit per checkpoint). Remove the worktree after the fast-forward. | — |

Rejected alternatives: cherry-picking/rebasing the 10 feature commits (loses the ADR lineage and the sync merge, makes `--remerge-diff` review impossible); merging `phase15/completion` into the feature branch (puts 97 commits of unrelated work under a feature-branch review); landing roles on `main` first (contradicts the owner's current instruction).

### 3.3 Accepted decisions vs branch defaults

| Category | Item | Status |
|---|---|---|
| Accepted 2026-10-06 | Q1 Admin grant script-only, in-app path behind `DND_AI_ALLOW_IN_APP_ADMIN_GRANT` (default false) | Implement as is |
| Accepted | Q4 System GM gates world/campaign creation and world management; continuous check. *Interpretation* "no campaign role requires system GM" was recorded "for confirmation" | Implement; fold the interpretation confirmation into DR-7 |
| Accepted | Q6 Timelines: Owner and Editor | Implement |
| Accepted | Q7 World Reader browse now (location/organization/religion cards) | Implement as the limited catalog; no expansion without a separate checkpoint |
| Accepted | Q9 Exceptions E1 world-time points, E2 item instances, E3 PC identity | Implement |
| Accepted, revised by this request | Q10 sequencing → integrate into `phase15/completion` | Record in ADR 0020 (CP-4f) |
| Accepted | Q14 rubric | Use `docs/ISSUE_GRADING_RUBRIC.md` |
| ADR decisions | Three independent scopes; Viewer kept distinct from Reader; authorship is provenance; account activation separate from campaign admission; explicit audited recovery only | Implement |
| **Default, needs confirmation (DR-7)** | Q2 backfill (admins → admin+gm; open active world owners → gm; others → player; campaign GMs not promoted); Q5 Observer classification only; Q8 world-only authoring deferred; Q11 recovery by scripts, IDs-only stranded report; Q12 invited registration → player; Q13 archive/restore/supersede = `world.canon.review`; lifecycle of E2/E3 records follows the exception; Viewer/Reader coexistence | Implemented as defaults; confirm before step 5 |
| Implementation choices (reviewable, not policy) | §16.3: natural idempotency on system-role routes; existing audit action vocabulary; `security.system_roles` not reporting-readable; `claim_world_ownership.py` not requiring GM; explorer/AI draft gating extended to `read_private` | Review in CP-4; change only with cause |

### 3.4 Integration inventory (what CP-4 must touch beyond textual conflicts)

| Area | Current-side surface (post-`c1b7038`) | Required integrated behaviour |
|---|---|---|
| World record workspace | `components/world/WorldRecordWorkspace.tsx`, `CampaignWorldDetailPage`, `WorldReviewSection`, `WorldPublication`, `useDungeonRead`, `worldStages.ts` | Mode from server eligibility, not campaign `canon.edit` alone. Campaign-only GM: published details incl. GM-only fields + Use-in-play/runtime sections; Prep/Sources/Revisions/Review shown as disabled non-links with the world-authority explanation (stable-structure rule) and **never requested**. A failed optional sidebar read must not blank the record. |
| Knowledge claim workspace | `KnowledgeClaimPage.tsx`, `components/knowledge/*` (ClaimReview, ClaimPublication, KnowledgeRoster, MemberPreviewShell), `KnowledgeSectionRedirect` | Definition edit needs `world.canon.edit`; review actions `world.canon.review`; runtime roster (learn/tell/belief) stays campaign; targeted claim grant stays field-limited, read-only for baseline stages; member preview keeps subject authority. |
| Quest workspace | `components/quests/*`, `QuestSectionRedirect` | Definition sections world-gated; progress/runtime campaign-only; retained drafts survive remount. |
| Item workspace | `components/items/*`, `ItemWorkspacePage`, `ItemPages.tsx` | Definitions world-gated; instances follow E2 (whole lifecycle). |
| Character/PC | `AuthoringEditLink.tsx`, `CharacterManageLinks.tsx`, `NpcAuthoringPages.tsx`, ContentCreate/Edit configs | NPC definition world-gated; PC follows E3 via a **record-level server flag** (`campaign_originated`), not a category list in the client. |
| Lifecycle panel | `EntityLifecyclePanel.tsx` (conflict), `utils/lifecycleNextStep.ts`, `reviewTarget.ts` | Actions only from server `available_actions`; Editor sees submit/return/delete-draft; Reviewer sees approve/reject/publish/archive/restore/supersede. |
| Member readers | `queries/character_relationships.py`, `api/organization_members.py` + `OrganizationMembersReader`, `PartyDetailPage`, `useWorldCategoryCounts`, `queries/session_travel.py`, Knowledge member reads | Published member reads need **no** world role; nothing private becomes visible because a runtime GM is present; counts and lists share one filter. |
| Relationship writes | `commands/world_relationships.py`, `domain/relationship_authoring.py`, `api/relationship_authoring.py` (conflict) | Definition writes need world edit; timeline status/reaction commands stay campaign; current compatibility/period rules preserved. |
| Bootstrap / context / nav | `types/bootstrap.ts` (conflict), `PortalSidebar.tsx` (conflict), `App.tsx`, `CampaignWorldPage.tsx` (conflict), `HierarchyContextPanel`, `WorldsNavGroup`, `CampaignSetupPage` | `system_roles`, `global_capabilities`, per-campaign `world_capabilities`; no campaign's capability snapshot reused in another; Sharing page and system-role editor routes added. |
| Accounts | `CreateAccountPanel.tsx` (conflict), `AdminAccountsPage.tsx`, `api/local_auth.py` (conflict), `commands/local_auth.py` | Feature system-role creation + current-side account changes both preserved; invitation acceptance never reads/writes system roles. |
| Scripts / fixtures | `scripts/setup_phase13c_dev_data.py`, `setup_phase15_world_content.py`, `tests/factories.py` | Explicit system/world roles. **Not** rerun against the dev DB. |
| Route manifest | `tests/scenario/phase15_route_manifest.py`, `test_phase15_acceptance_guards.py` (conflict) | Regenerated from actual current routes, each classified by scope and capability. |

---

## 4. Dependency-ordered checkpoints

Sizes (S ≈ 1–3 focused days, M ≈ 3–7, L ≈ 1–2 weeks) are relative estimates. Every code checkpoint's standard gate: `ruff format --check`, `ruff check`, `mypy src`, focused `pytest` against local PostgreSQL 18 (ephemeral DB from `tests/conftest.py`), portal `tsc`/`eslint`/focused `vitest`/`vite build`; full suites at CP-4f and CP-11. Known pre-existing noise (14 Windows CRLF frozen-seed failures; intermittent portal timing tests) is recorded, not hardened.

```
CP-0 ─┬─ CP-1 ─ CP-3 ──┐
      └─ CP-2 ─────────┴─ CP-4 (I-0…I-6) ─┬─ CP-5 ─ CP-6
                                          ├─ CP-7
                                          ├─ CP-8 (after CP-3)
                                          ├─ CP-9a ─ CP-9b
                                          └─ CP-10 ──────────── CP-11 (needs all)
```

### CP-0 — Evidence baseline and testing targets (no code) · S

**Result.** A dated, restore-verified record of what exists, so integration and later acceptance never depend on the live dev DB.

**Scope.**
1. Record HEAD, refs, merge base (§1), DB revision/time anchor (§1.3), fixture identities (audit §4.2), and the guide's 40/18 markings verbatim in a new untracked `docs/PHASE14_15_EVIDENCE_BASELINE.md`.
2. Snapshot the testing documents: copy `docs/PHASE14_15_MANUAL_TESTING.md` and `git diff` of the three modified docs into an untracked evidence folder outside `docs/` (for example `.tmp/evidence-20261024/`), with SHA-256 of each. Originals untouched.
3. With owner go-ahead: `pg_dump -Fc` of `dnd_ai` (read-only) to a file outside the repo; restore it into **`dnd_ai_m1415_baseline_20261024`** and verify revision 136 and counts. This copy is never mutated; every other target is cloned from it:
   - `dnd_ai_m1415_upgrade_rehearsal` — 136→138(+139) upgrade (CP-4f, CP-6),
   - `dnd_ai_m1415_downgrade_scratch` — lossy downgrade rehearsal only,
   - `dnd_ai_m1415_accept_<prefix>` — manual acceptance on the integrated head (CP-11),
   - `dnd_ai_m1415_clean` — fresh migrate, no dev seeds (TC-56).
   Existing `dnd_ai_test_*` and other unknown DBs are never used or dropped.
4. Classify prior evidence: *Historical — executed-not-graded, pre-integration, HEAD ≤ f0aae3b, DB `dnd_ai` @136*. New results go only to a separate integrated ledger (CP-11).
5. List missing prerequisites and the supported way to create each (§7.4). Repair happens in CP-11 prep on the acceptance copy, after integration, so creation itself runs under the integrated authority model.

**Exclusions.** No reseed, reset, fixture-script run, raw SQL, or edits to the guide. No reconstruction of unknowable historical actions; nothing here blocks CP-1–CP-4.

**Verification / completion.** Baseline file exists with hashes; restore of the baseline copy verified (revision, row counts of worlds/campaigns/sessions/audit). **Risk:** a dump taken while the owner's dev server writes — take it when the owner confirms no manual testing is in progress.

### CP-1 — Session participant compatibility and accurate rejection · S

**Result.** The Add-participant form offers only compatible roles for the chosen character (PC → Player character/Guest; NPC → NPC/Guest), picks a compatible default when the character changes (PC → `player_character`, NPC → `npc`, keeps `guest` if chosen), never sends an incompatible request in ordinary use, and explains a server rejection accurately.

**Scope / files.**
- Server catalog (Phase 15 exit criterion "write options come from server-authoritative catalogs"): a pure `participant_roles_for_kind` in a small domain module (e.g. `src/dnd_ai/domain/session_participation.py`) used by `commands/session_play.py` (`_lock_participant_character`, `add_session_participant`) **and** exposed in the session run read model (`queries/session.py` / `api/session_play.py`) as `participant_role_options: {player_character: [...], npc: [...]}`.
- Distinct safe error code for wrong role (e.g. `session_participant_role_mismatch`) alongside the existing `session_participant_invalid` for unusable/unpublished/foreign characters; mapping in `api/errors.py` or the session-play adapter.
- Portal: extract the participant form from `pages/SessionRunPage.tsx` (~430–620) into `components/sessionRun/ParticipantForm.tsx`; structured `character_kind` on the reference option (via `utils/characterKind.ts` or the search response) instead of parsing `ReferenceOption.detail`; corrected `CODE_MESSAGE`.

**Contracts.** API: additive read-model field + one new error code. No schema, permission or role-vocabulary change. Observer/controller/GM are never offered as participant roles.

**Preserve.** Server rejection of mismatch/duplicate/foreign/completed; existing valid Guest PC rows; retained selection on refusal (d26be7c behaviour); same-key retry.

**Verification.** Unit: catalog per kind. DB/API: extend `tests/database/test_api_session_play.py::test_participants_are_published_characters_with_a_matching_role` to assert the new code and unchanged participant count/row version. Portal: PC↔NPC switching, Guest kept, default repair, removed/re-added participant, message per code. Manual: TC-22 participant variants; keyboard selection and announced error (one AT spot check).

**Done when** no ordinary form path can submit an incompatible pair and both rejection reasons render distinctly. **Risk:** low; keep the catalog domain-owned so encounter sides/initiative are untouched.

### CP-2 — Write receipt, refresh outcome and load-state contract · M

**Result.** A confirmed write followed by a failed refresh says "Saved — latest data couldn't be loaded" with a **read-only** retry; an uncertain write (network/5xx before a response) keeps the input and retries the **same body and key**; loaded-empty, loading, denied, unavailable and recoverable failure render differently; failures are announced once.

**Scope / files.**
- `hooks/useAuthoringMutation.ts`: separate the request outcome from the `onSuccess` refresh outcome (today one `try` classifies a throwing callback as a mutation failure). Expose `{status: "confirmed", refresh: "ok" | "failed"}`; keep the request key only while the outcome is uncertain; clear it on confirmation.
- `hooks/useAuthoringResource.ts`: `refetch` returns an explicit result the caller can await; reuse `useKeptResource`/`useKeptData` and `components/StaleReadNotice.tsx` for "showing last loaded data".
- `components/authoring/feedback.tsx`: one additive `SavedRefreshFailedNotice` (small; this file overlaps the feature, keep the change additive).
- Representative callers: `components/InventoryPanels.tsx` (character and party panels: distinct states instead of `return null`), `pages/CampaignSettingsPage.tsx` save/archive and `ArchivedCampaignsSection` (bootstrap refresh failure explained, not swallowed), one ContentEdit authoring form.
- Check the `TravelSection` mocked receipt shape behind the audit's stderr (fix the mock or the null guard; no harness work beyond that).

**Exclusions.** Rewriting every hook or access-management screen; optional reads (category counts, last-visited preference) stay quiet or subtly inline.

**Preserve.** Kept data and saved-vs-refresh behaviour in Session Run (`lastGood`), Knowledge claim, Quest and Item workspaces (1124e95, 7219db4, 1eacbf2); `ReferenceCombobox` error state; safe envelope and correlation id; no raw server detail.

**Verification.** Hook tests: uncertain POST retry reuses key/body; confirmed POST + failing GET issues only GET on retry; 409 stale keeps draft until "Load latest"; 401 rechecks session; late response after route change ignored; pending clears on abort. Caller tests for Inventory/Settings. Manual (copy): DevTools offline during save; successful save with API stopped before refresh. AT: one live-region announcement check.

**Done when** the §5D reproduction matrix in the audit passes for the representative callers. **Risk:** accidentally reusing a stale version after a confirmed write — after confirmation the form must take the receipt's new version or block edits until refresh succeeds.

### CP-3 — Shared session roster for GM views · S

**Result.** Session detail (`/sessions/:id`) shows the same present/left roster as Run → Prepare and Wrap-up review: character name, kind (PC/NPC), session role, added/removed real times, safe link to the character. Edit/remove controls appear only in Run and only when `manage_participants` and session status permit.

**Scope / files.** `queries/session.py` `list_session_participants` adds character kind; `api/sessions.py` `SessionParticipantResponse` adds `character_kind` (GM branch only; members still `participants=null` until CP-8). New `components/sessionRun/SessionRoster.tsx` (read rows + optional controls slot) used by `SessionDetailPage`, `SessionRunPage` (Prepare) and `sessionRun/SessionReview.tsx`. Detail ↔ Run links: detail offers "Run session" when the record's actions include it; Run already links back.

**Preserve.** Dedicated Run activity, staged sections and draft retention; encounter roster (sides/initiative/outcomes) stays separate; legacy `/edit` redirect unchanged.

**Verification.** API test for the new field; component tests for three callers sharing rows and control gating by status; manual GM check of scheduled/running/completed sessions (TC-22/23/50 roster assertions).

**Done when** the three views render one roster component from one projection. **Risk:** low.

### CP-4 — Scoped-role integration (integration branch, I-0…I-6) · L

**Result.** System, world and campaign authority are independent and enforced on every request; the current workspaces present reader/editor/reviewer/runtime modes from server data; campaign-only GMs keep running games and the three campaign-originated record types; nothing private leaks and nothing legitimately published is newly denied.

**CP-4a / I-0 Merge and conflict resolution.** As §3.2. Also fix "ADR 0019" docstrings that mean 0020.

**CP-4b / I-1 Backend gates for current-side surfaces.**
- `api/knowledge.py`, `api/characters.py`, `api/organization_members.py`, `api/relationship_authoring.py`, `api/world_explorer.py`, `queries/character_relationships.py`, `queries/session_travel.py`, `commands/world_relationships.py`: every call into `lifecycle_hidden_entity_ids` passes `viewer_user_id`; private reads require `world.canon.read_private`; published member reads unchanged.
- E2: verify `world.item_instances.origin_notes` is not readable from another campaign on the same world; if it is, restrict per feature D8.
- Revocation: authority resolved per request; world role end/transfer take the world lock (`FOR SHARE` re-resolution in `lock_authoring_scope`); add one real-concurrency test for "world role ended mid-command" on a current-side writer (relationship definition). Legacy transfer/encounter adapter race limits stay documented, not claimed fixed.

**CP-4c / I-2 Per-record eligibility contract (C1).** Server-computed, record-level fields on existing read models — not a policy engine:
`authoring: {campaign_originated, can_read_private, can_edit, can_review}` on world-explorer/authoring detail responses, plus existing `available_actions`. Computed with the same resolvers the commands use (`resolve_world_authority`, campaign `resolve_access_context`), under the E1–E3 classification. Portal gets one small helper that reads these fields; it never infers from role names or categories. Unit tests per role union; an agreement test that `can_edit` ⇔ the matching command does not return 403 for the same caller/record.

**CP-4d / I-3 Portal integration of current workspaces.** The §3.4 table. Plus:
- Permission loss (uses CP-2): on 403 `world_authority_required` or non-disclosing 404 after a role change, discard server-loaded private content (drafts, GM notes, revisions, sources) immediately; keep the user's own unsaved typed input in the tab, read-only, with "You no longer have permission to edit this — copy your text if you need it"; never submit it. Recoverable network/5xx failures keep drafts and versions as CP-2 defines.
- Capability snapshots are keyed by campaign id; switching campaigns refetches bootstrap-derived capabilities before rendering gated controls.
- Editor vs Reviewer: review queue readable by both (`read_private`); actions differ by `available_actions`.
- System-role editor, Platform Accounts gate on `accounts.manage`, Sharing page `/worlds/:worldId/sharing`, ownership transfer (focus returns to trigger), no-campaign GM empty state, campaign setup world/timeline eligibility with reasons, World Reader catalog page (limited to the three categories).

**CP-4e / I-4 Tests, manifest, fixtures.** Regenerate `tests/scenario/phase15_route_manifest.py` from actual `App.tsx` routes and API routers: each route → scope (system/world/campaign/member-read) and required capability; acceptance guards assert classification completeness and representative negative cases. Rewrite ADR 0018 tests per feature §12.5. Update `tests/factories.py` and both fixture scripts (code only; not run against dev). Feature scenarios `tests/scenario/test_scoped_roles_flow.py` must pass on the integrated tree.

**CP-4f / I-5–I-6 Migration rehearsal, docs, verification record.**
- On `dnd_ai_m1415_upgrade_rehearsal`: record pre-state (users, `is_platform_administrator`, world memberships, campaign memberships/roles, invitations, character relationships, resource grants/denies, counts); `alembic upgrade head`; assert IDs/memberships/owners/invites/links/grants unchanged and roles exactly: `admin` → admin+gm (+existing world_owner rows), GM2 → `player` with campaign owner+gm retained, Player A/B/observer/disabled → `player`; no campaign GM promoted. Run `alembic check`/drift, grants (`app_read_write`, `app_read_only` deny-by-default), comments.
- On `dnd_ai_m1415_downgrade_scratch`: downgrade 138→136 and record the documented loss (non-admin system roles, Editor/Reviewer/Reader rows, use grants, Viewer-beside-Owner closed); re-upgrade.
- Clean DB: migrate from empty; bootstrap admin gets admin+gm; first world and campaign creatable.
- Docs per §9; ADR 0020 amendment (Q10 sequencing; integration record); feature plan §16 addendum; `PHASE15_VERIFICATION.md` integration section (after asking about the owner's pending edits).

**Preserve (all of CP-4).** Campaign roles/custom roles/relationships/groups/grants/deny composition; character view tiers; member readers; named travel; kept drafts; staged navigation; Viewer semantics (ADR 0019); authorship columns; idempotency/audit/CSRF/Origin behaviour.

**Verification.** Full suites; feature focused tests (`test_system_roles*.py`, `test_world_sharing.py`, `test_world_canon_boundary.py`, `test_stranding_and_recovery.py`); new current-surface tests listed above; portal suites; browser pass on 8001/5174 with the rehearsal copy for SR-M1–SR-M14 smoke (full manual in CP-11).

**Completion.** All above green locally; DR-7 confirmed; owner approves the fast-forward. **Risks:** private leak or excess denial from a stale gate (mitigated by CP-4c agreement tests and route manifest); eager sidebar subrequests 403-ing a valid runtime page; downgrade loss (rehearsed only on scratch); the owner's running dev server breaking on fast-forward (§7.3).

### CP-5 — Coherent character record and inventory reachability · M

**Result.** From Characters or World, the same character shows one identity header and section navigation — **Details** (World), **Sheet** (mechanics), **Relationships**, **Inventory**, **Parties** — each linked only when the server says the caller may read it. Owners, controllers, portrayers and direct `view_full` grantees reach Inventory from the sheet. Visiting never selects a controlling perspective.

**Scope / files.**
- Server: character summary/detail response adds `sections: {details, sheet, relationships, inventory, parties}` booleans computed with the same function as the endpoints (`api/access.py:resolve_character_view_tier`; inventory endpoint `api/characters.py:670`). Agreement test: `sections.inventory` ⇔ `GET …/inventory` is 200.
- Portal: new `components/characters/CharacterRecordNav.tsx` (header + sections) used by `CharacterSheetRoutePage.tsx` and the reader branch of `CampaignWorldDetailPage`/`CharacterDetailPage.tsx`; section addressed with the existing `?section=` convention; `CharacterInventoryPanel` reused (no second inventory query); `CharacterManageLinks.tsx` keeps GM edit links, while the non-GM "World details" link moves into the nav; origin context through `useCharactersBackPath`/`useWorldBackPath` location state; member Relationships reachable from the World view too.

**Contracts.** Additive response fields; no schema or permission change.

**Preserve.** Summary-tier refusal; GM World workspace; full-sheet layout; party inventory remains GM-only; item hidden properties filtered by holder identification; reader mode sends no mutation requests.

**Verification.** API matrix: GM, owner, co-controller, direct grantee, summary viewer, revoked relationship, explicit deny. Portal: nav per role, Back/Forward/reload with list filters preserved, deep link to `?section=inventory`, perspective unchanged after visiting (assert `useCharacterPerspective` setter not called), empty vs denied vs failed inventory (CP-2 states). Manual: TC-40 inventory assertions; narrow-width nav.

**Done when** an owner reaches inventory in two clicks from Characters with no GM controls, and denied sections are absent rather than broken. **Risk:** origin context lost across the two routes — covered by Back/Forward tests.

### CP-6 — Inventory-only viewer access (policy extension) · M · needs DR-2

**Result (proposed default).** A new character-target capability `character.view_inventory` lets `viewer` and `observer_approved_viewer` relationships read the character's inventory through a restricted projection, without `view_full` and without any mutation or control.

**Scope / files.**
- Migration (id from the live head after 138, expected `139_character_inventory_capability`): insert the capability lookup row explicitly (frozen-seed rule, DATABASE_CONVENTIONS §25.4, as revisions 114/138 did); insert mapping rows for the approved relationship types following migration 114's reconcile pattern; comments. Downgrade deletes the mapping rows, any resource grants/denies naming the capability (documented loss) and the capability row.
- `domain/access.py`: add to `CHARACTER_TARGET_CAPABILITY_CODES` and `BUILTIN_RELATIONSHIP_CAPABILITIES` (code/DB agreement test already exists).
- `api/access.py`: `resolve_character_inventory_access → "full" | "inventory_only" | "none"`: `canon.edit` (baseline) → full; effective `view_full` → full; effective `view_inventory` → inventory_only; an explicit deny of `character.view_inventory` wins over both relationship sources (DR-2); entity-level campaign view deny wins over everything.
- `queries/inventory.py`: `inventory_only` projection = item rows (name, kind, quantity, equipped/attuned, destroyed, custody vs owner) with identification-filtered properties; excludes anything derived from character mechanics and any GM-only instance field (`origin_notes`). Exact field list fixed from the `InventoryView` dataclass at implementation.
- Access UI catalog label "View inventory" in the character grant/deny editor; CP-5 `sections.inventory` uses the new resolver.

**Exclusions.** Party inventory; transfer/equip/consume/quantity/award; any `character.control` or perspective.

**Verification.** Migration up/down on fresh and on the rehearsal copy; constraint/agreement tests; API matrix (viewer allowed; former_controller none; deny wins; grant to plain player allowed; hidden property not leaked; draft/archived instance excluded; foreign timeline 404); no mutation endpoint accepts the capability. Manual SR-M15.

**Done when** viewer inventory works with the restricted projection and every negative case holds. **Risk:** projection leak through shared serializers — test response JSON, not only UI.

### CP-7 — Archived Knowledge browsing · M · needs DR-1, DR-5

**Result.** Eligible users see an **Active / Archived / All** control in Knowledge; the server filters before keyset pagination; URL carries `lifecycle=`; search, view and perspective survive Back/reload; changing the filter resets the cursor; archived cards show their state; detail offers Restore when `available_actions` allows (Reviewer/Owner after CP-4).

**Scope / files.** `api/knowledge.py` list/browse: explicit `lifecycle=active|archived|all` mapped onto `lifecycle_hidden_entity_ids(include_archived=…)` (proposed: Archived = operationally archived published-history claims; All adds superseded/deprecated; drafts/rejected never appear here — they live in review views). Eligibility (proposed DR-5): **baseline** campaign `canon.edit` (never a resource-targeted grant) ∧ `world.canon.read_private` on the campaign's world. Ineligible non-`active` requests → 403 with a safe code (an explicit parameter is rejected rather than silently ignored, so the UI can never mislabel active results as archived; record this beside §3.3's "flags are ignored" rule). Cursor binds the filter fingerprint; mismatch → 400 safe code. List response carries `archive_browse_available`. Portal: `KnowledgePage.tsx`/`CampaignKnowledgePage`, knowledge client/types/hooks.

**Preserve.** Historical direct reads by ID (DR-1 default); retained knowers; archived claims reject new learn/tell/belief writes; Member preview offers no archive filter; no cosmetic counts.

**Verification.** API: GM with/without `read_private`, Reviewer, player, targeted claim grant, explicit deny, forged parameter, cursor across filter change, pagination without omission/duplication across mixed statuses. Portal: control visibility from server flag, URL round trip, cursor reset. Manual TC-31 archive part; TC-10 reconciliation.

**Done when** an eligible GM can find an archived claim from Knowledge in one filter change and no ineligible caller can. **Risk:** list/detail policy conflation — tests assert both separately.

### CP-8 — Member-safe session roster · S · needs DR-3

**Result (proposed default).** Campaign members reading a session see only participants whose character they may discover (same visibility resolver as World Explorer — `resolve_world_character_visibility` / `CharacterVisibility` — plus entity denies). Hidden participants are omitted entirely: no counts, placeholders or "N hidden". Rows carry name, kind and session role; links only where the reader route allows. Presence never implies character access or control.

**Scope / files.** `api/sessions.py` member branch, `queries/session.py`; `SessionRoster` (CP-3) without controls.

**Verification.** API: player sees own PC and discoverable NPC, not undiscovered NPC; observer; denied character; response JSON contains no hidden ids; roster count equals visible rows. Manual TC-22/50 member view.

### CP-9a — Event explanations (read side) · M · needs DR-6

**Result.** Party join/leave, build activation and clock change events read as sentences with named references, before → after values, **In-world time** (calendar formatter) and **Recorded** real time (with timezone) shown separately, and links to session, prior/caused events and corrections where the reader may open them. Unknowable or denied values show "not recorded" or "not available", never raw ids. Names are presented as current labels, not historical snapshots.

**Scope / files.** New query adapter `queries/event_explanations.py` with one function per effect family (party membership, character build, campaign clock, current location — moved from `queries/event_authoring.py`'s location special case — and travel delegating to `queries/session_travel.py`). Inputs include the caller's audience (character visibility, denies, view tier, `read_private` after CP-4). Reused by `queries/world_explorer.py:get_event_view`, `queries/event_authoring.py`, and the session log projection. Cause links are labelled by relation: the clock's existing chain row reads "follows the previous clock change", not "caused by". Portal: `components/events/EventExplanation.tsx` used by `WorldEventDetailPage` (remove its omission comment), `EventPages` `EventBody`, `sessionRun/SessionActivity`, `RecentEventsSection`.

**Exclusions.** No historical backfill, no guessed causes, no audit log as domain history, no new event store.

**Verification.** DB scenario creating fresh join/build/clock events: GM vs member vs summary-tier vs denied projections; branch cutoff (no post-branch parent event); corrected event shows correction link; same-key replay of the originating command still yields one event. Portal rendering per family. Manual TC-15/19/21/25.

### CP-9b — Optional clock cause and member-safe explanation (write side) · S · needs DR-4

**Result (proposed default).** Advancing the clock may name an existing gameplay event as its cause and give a member-safe explanation; a plain manual advance remains valid and is shown as "Manual advance". The administrative reason (audit) stays separate.

**Scope / files.** `commands/campaign_clock.py` `advance_campaign_clock(cause_event_id=None, explanation=None)`: validate the cause is in the same campaign/timeline (own history, branch-aware), not a clock event, not voided, effective at or before the new time, readable by the actor; write an additional `narrative.event_causes` row (no schema change) and the explanation into the event's existing `details` (same audience as the event) in the same transaction. Request fingerprint includes both fields (changed body + same key → 409 as today). API request model and `CampaignClockCard`/WorldTimes advance form (optional event picker via `ReferenceCombobox`, optional explanation).

**Preserve.** Strict later-time rule, no-op refusal, chain row, atomic clock/event/effect/audit/receipt.

**Verification.** Command tests for each validation, atomic rollback on invalid cause, replay; API; portal form; CP-9a shows the cause link.

### CP-10 — Recovery completion and bounded workspace consolidation · M

**Result.** Remaining domain callers adopt the CP-2 contract where they still differ; shared header/section/return glue duplicated between the World record and character record is unified; no behaviour change.

**Scope.** Only the extractions in §4.1's register marked CP-10. Stop when the named duplication is gone.

**Verification.** Route snapshots before/after; existing focused suites; no new request on stage/section switch; denied clears retained private data.

### CP-11 — Fixture repair, final manual acceptance, clean deployment · L

**Result.** The 18 unexecuted cases and the affected assertions of the 40 are recorded on the integrated head with exact environment identity; AT/responsive and clean-deployment acceptance done; owner decision recorded.

**Scope.** Clone `dnd_ai_m1415_accept_<prefix>` from the baseline, upgrade it with the integrated build, assign deliberate world roles/use grants through the Sharing UI, repair prerequisites through supported workflows (§7.4), execute §8, run TC-56 on `dnd_ai_m1415_clean`, TC-55 on final layouts. Record HEAD SHA, DB name/revision, ports, browser/AT versions, viewports, run prefix in the integrated ledger. Guide corrections (TC-10/31 expectations, role matrices, SR scenarios) as marked amendments, never rewriting historical markings. Final-head CI via an owner-authorized PR to `main`.

**Done when** every variant is Pass/Fail/Blocked/Accepted with evidence; failures fixed or explicitly accepted under the rubric's Medium disposition (DR-9); CI green on the accepted SHA.

### 4.1 Consolidation register (each extraction with its real callers)

| Extraction | CP | Actual callers | Duplication removed | Not doing |
|---|---|---|---|---|
| Participant role catalog (domain) + `ParticipantForm` | CP-1 | `commands/session_play.py`, run read model, `SessionRunPage` | Hard-coded role list and kind parsing in the page; server/client matrix drift | A generic "member" domain; encounter sides |
| `SessionRoster` + participant projection | CP-3, CP-8 | `SessionDetailPage`, `SessionRunPage` Prepare, `SessionReview` | Three roster renderings and two role-label formatters | Merging Run into detail |
| Receipt/refresh outcome in `useAuthoringMutation` + `SavedRefreshFailedNotice` | CP-2 | Inventory panels, Settings/ArchivedCampaigns, ContentEdit, later Quest/Item/Claim | Ad hoc `lastGood`/`catch(() => undefined)` patterns | A query/cache library; global toasts |
| Record-level `authoring` eligibility fields + portal helper | CP-4c | WorldRecordWorkspace, KnowledgeClaimPage, QuestWorkspace, ItemWorkspace, AuthoringEditLink, CharacterManageLinks, EntityLifecyclePanel | Seven independent `canon.edit`/category-based mode decisions | A policy engine; system/world capabilities in campaign capability rows |
| `CharacterRecordNav` + `sections` | CP-5 | CharacterSheetRoutePage, CampaignWorldDetailPage/CharacterDetailPage | Split World link (GM-only) vs sheet links; missing inventory entry | A universal record page |
| `event_explanations` adapters + `EventExplanation` | CP-9a | world_explorer event view, event_authoring, session log; WorldEventDetailPage, EventPages, SessionActivity, RecentEventsSection | Location-only special case; generic previous/new rendering; four time renderings | Parallel event store; historical name snapshots |
| Shared record header/back-navigation glue | CP-10 | `WorldRecordHeader`, `CharacterRecordNav`, `useWorldBackPath`, `useCharactersBackPath`, `useItemsBackPath` | Three origin-state helpers with the same shape | Rewriting staged navigation per domain |
| WorldRecordWorkspace loader/mode split | CP-4d (only as needed for eligibility) | WorldRecordWorkspace (710 lines) | Eager lifecycle/provenance/revision loading tied to one flag | Broader module re-layout |

Session roles, encounter participation, fictional memberships, knowledge knowers and access assignments remain distinct domains throughout.

---

## 5. Before/after permission tables

"Before" = HEAD `f0aae3b`. "After" = integrated tree plus CP-5–CP-9 under the proposed defaults. Campaign-scoped columns assume the actor is a member of the route campaign unless stated. ✔ yes, ✖ no, → change.

### 5.1 Platform and world scope

| Actor | Create world | Host campaign | Manage / share / transfer world | Create/branch timelines | Platform accounts |
|---|---|---|---|---|---|
| Legacy admin who owns worlds (dev `admin`) | ✔ → ✔ (admin+gm backfill) | ✔ → ✔ (owner + system GM) | owner ✔ (no share/transfer existed) → ✔ | ✔ → ✔ | ✔ → ✔ |
| New Admin-only account | ✔ (ADR 0018) → ✖ | → ✖ | → ✖ | → ✖ | → ✔ |
| **Campaign-only GM** (GM2: campaign owner+gm, no world role) | ✔ (ADR 0018) → ✖ until system GM assigned | ✔ via borrowed `access.manage` → ✖ | ✖ → ✖ | ✖ → ✖ | ✖ |
| World Owner + system GM | ✔ | ✔ | ✔ | ✔ | ✖ unless Admin |
| World Owner without system GM | n/a → ✖ | n/a → ✖ | n/a → ✖ (continuous) | n/a → ✔ | ✖ |
| World Editor | — → ✖ | ✖ | ✖ | → ✔ | ✖ |
| World Reviewer | — | ✖ | ✖ | ✖ | ✖ |
| World Reader | — | ✖ | ✖ | ✖ | ✖ |
| World Viewer (ADR 0019) | ✖ | ✖ | ✖ (reads world/timelines/calendars) | ✖ | ✖ |
| Use-grant holder + system GM | — | → ✔ on a timeline with no campaign; ✖ on a used one | ✖ | ✖ | ✖ |
| Player / Observer | ✖ | ✖ | ✖ | ✖ | ✖ |

### 5.2 Shared canon and campaign operations

| Actor | Published canon incl. GM-only fields (in campaign) | Private prep: drafts, revisions, sources, provenance, review queue | Create/edit world definitions (NPC, location, org, religion, quest, claim, item def, calendar) | Review/publish/archive/restore/supersede | PC identity, item instances, world-time points (E1–E3) | Runtime: sessions, clock, events, encounters, travel, item ops, knowledge runtime |
|---|---|---|---|---|---|---|
| **Campaign-only GM** | ✔ → ✔ | ✔ → ✖ | ✔ → ✖ | ✔ → ✖ | ✔ → ✔ | ✔ → ✔ |
| World Editor + campaign `canon.edit` | — → ✔ | — → ✔ | — → ✔ (incl. submit, return to draft, delete draft) | — → ✖ | ✔ | ✔ |
| World Reviewer + campaign `canon.edit` | — → ✔ | — → ✔ | — → ✖ | — → ✔ | ✔ | ✔ |
| World Owner + campaign `canon.edit` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| World Editor who is only a Player in the route campaign | — → player projection | ✖ | ✖ (needs campaign `canon.edit`; world-only authoring deferred) | ✖ | ✖ | player rights only |
| World Reader (no campaign) | — → published player-safe catalog of locations, organizations, religions at the world | ✖ | ✖ | ✖ | ✖ | ✖ (no campaign data) |
| World Viewer | ✖ | ✖ | ✖ | ✖ | ✖ | ✖ |
| Player / Observer | player-safe projection, unchanged | ✖ | ✖ | ✖ | ✖ | ✖ |

### 5.3 Character, inventory, session and knowledge reads

| Actor | Full sheet | Inventory read | Inventory mutation | Perspective / control | Session roster | Knowledge archive browse | Event explanation |
|---|---|---|---|---|---|---|---|
| GM (baseline campaign `canon.edit`) | ✔ | API ✔, sheet ✖ → ✔ via character nav | ✔ (unchanged) | only via own relationship; visiting never selects | API ✔, detail ✖ → detail/run/review ✔ | ✖ → ✔ only with `world.canon.read_private` (DR-5); campaign-only GM ✖ | ids/generic → named, full values |
| Character owner (player) | ✔ | API ✔, unreachable → ✔ reachable | ✖ | per relationship | ✖ → discoverable rows only (DR-3) | ✖ | labels per audience; own build values |
| Full-tier reader (primary/co-controller, portrayer, direct `view_full` grant) | ✔ | as owner | ✖ | per relationship | as owner | ✖ | as owner |
| Viewer / observer-approved viewer | summary | ✖ → inventory-only projection (DR-2) | ✖ | ✖ | discoverable rows | ✖ | summary level; build values withheld (DR-6) |
| Former controller | ✖ | ✖ | ✖ | ✖ | discoverable rows | ✖ | per discovery |
| Explicit deny of `character.view_inventory` (new) | unaffected | → ✖ even with full tier (DR-2) | ✖ | — | — | — | — |
| Targeted claim `canon.edit` grant | — | — | — | — | — | ✖ (never general archive access) | — |
| Plain player without relationship / Observer | per discovery | ✖ | ✖ | ✖ | discoverable rows | ✖ | per discovery |

---

## 6. Requirements detail that cuts across checkpoints

### 6.1 Error vocabulary (CP-1, CP-2, CP-4)

| State | Presentation | Action offered |
|---|---|---|
| Loading | inline progress; previous data kept if any | — |
| Loaded empty | explicit empty text ("No items carried") | — |
| Denied (403) | "You don't have access to this" with the server's safe reason (`world_authority_required` explains which world role); protected data cleared | Recheck session |
| Unavailable (non-disclosing 404) | neutral "not available" | Back |
| Recoverable failure (network/5xx) | "Couldn't load — Retry" with safe correlation id | Read retry |
| Uncertain write | input kept; "We couldn't confirm the save" | Retry same request (same key/body) |
| Confirmed write, refresh failed | "Saved. Latest data couldn't be loaded." | Read retry only |
| Stale (409 version) | draft kept; Load latest / reapply | Explicit |
| Optional read failed (counts, preferences) | quiet or subtle inline | none or retry link |

### 6.2 Proposed policy defaults (labelled; not approved)

1. Preserve authorized historical archive references (§3.3 reference mode). Archive **browse** is separate and narrower.
2. Viewer inventory via `character.view_inventory`, restricted projection, no mutation.
3. Member roster discloses only discoverable participants; hidden ones leak through nothing.
4. Manual clock advancement stays; gameplay cause and member explanation optional and validated.
5. World Viewer and Reader keep distinct meanings.
6. World Reader catalog stays the feature's three categories until a separate checkpoint.

---

## 7. Database upgrade, deployment and evidence preservation

### 7.1 Targets

| Target | Purpose | Writes allowed |
|---|---|---|
| `dnd_ai` (owner dev) | Owner's working DB; historical evidence | None by this plan until the owner chooses its own upgrade (§7.3) |
| `pg_dump` file + `dnd_ai_m1415_baseline_20261024` | Immutable restore-verified baseline at 136 | Restore only |
| `dnd_ai_m1415_upgrade_rehearsal` | Populated 136→138→139 upgrade verification | Migrations only |
| `dnd_ai_m1415_downgrade_scratch` | Lossy downgrade rehearsal | Migrations; discard after |
| `dnd_ai_m1415_accept_<prefix>` | Integrated manual acceptance | Supported UI/API workflows only |
| `dnd_ai_m1415_clean` | Clean deployment (TC-56) | Migrations + bootstrap + UI |
| pytest ephemeral DBs | Automated suites | Owned by `tests/conftest.py` |

Never: blanket reseed, fixture-script runs against `dnd_ai` or the acceptance copy, raw SQL domain fabrication, or use of unidentified existing databases.

### 7.2 Offline upgrade runbook (rehearsed in CP-4f, executed for real only with owner approval)

1. Announce maintenance; stop API, worker and portal writers (Compose `api` service, or the local Uvicorn/Vite processes).
2. `pg_dump -Fc`; verify the dump by restoring it to a scratch name.
3. `alembic upgrade head` (137, 138, and 139 if CP-6 has landed).
4. Start the **matching** API and portal build together (same SHA). Old portal tabs reload into the new bootstrap; no old-boolean code runs against 137+.
5. Smoke: admin bootstrap shows admin+gm; campaign-only GMs listed by the upgrade-note query; stranded report empty or understood.
6. Assign world Editor/Reviewer to secondary GMs who should keep authoring (owner decision per world), via Sharing UI.
7. Rollback = restore the step-2 dump with the previous SHA. Downgrade is lossy and is not the rollback path.

### 7.3 The owner's running dev servers

The owner's API (8000, `--reload`) and portal (5173) run from the main checkout against `dnd_ai` @136. Fast-forwarding `phase15/completion` (§3.2 step 5) reloads code that requires 137/138 and will fail against 136. Before the fast-forward the owner stops those servers and either (a) upgrades `dnd_ai` with §7.2 after a dump, or (b) points them at an upgraded copy. This plan does not choose for the owner.

### 7.4 Missing prerequisites and the supported way to establish them (CP-11 prep, on the acceptance copy)

| Missing | Supported route | Needed by |
|---|---|---|
| R observer membership | Invite via campaign Access, accept, assign `observer` | TC-49, 55, 58 |
| Named times T0–T4 / Between | World Times page (E1 exception: campaign GM can create) | TC-14, 15, 24, 52 |
| Active Reserve; B leave/rejoin; NPC Reserve membership | Party restore and membership commands in the portal | TC-20, 21, 30 |
| Hero B / Archivist starting state and builds | Character build pages and starting-state flow | TC-19, 38, 43 |
| NPC portrayal versions | Portrayal page (world-authorized after CP-4) | TC-38 |
| Charm / Draft item definitions | Items workspace (world Editor/Reviewer) | TC-39, 41, 45 |
| Fresh running session (Play completed, Next running) | End Next or schedule a new session | TC-24, 37, 40–44, 50 |
| Encounter with tracked HP | Encounter preparation on the fresh session | TC-42–44 |
| Explicit source links | Sources panel | TC-32, 45 |
| Published unpublished-subject + its claim | Lifecycle publish (Reviewer) | TC-29 |
| Branch at a known point; branch campaign | Timeline branch (Owner/Editor), campaign creation (system GM + eligibility) | TC-52 |
| Empty world | World creation (system GM) | TC-51, 53 |
| Positive NPC resource adjustment | No supported pre-tracked fixture → **Blocked** unless one is provided | TC-38 variant |

Do not reuse destroyed Token, completed Play or `R Alternate` as fresh fixtures.

### 7.5 Evidence separation

- Historical: the guide's existing 40 markings, unchanged, plus the CP-0 snapshot hashes.
- Integrated: a new ledger (proposed `docs/PHASE14_15_ACCEPTANCE_LEDGER.md`, untracked until the owner decides) with one row per case/variant: SHA, DB name/revision, ports, browser/AT, viewport, result, evidence, issue link.
- A historical marking is never upgraded to Pass by inference; a new Pass needs a new row.

---

## 8. Manual retest map

Classes: **F** full rerun on the integrated head (authority model changed); **T** targeted assertions only; **D** defect retest; **X** expectation corrected by a decision; **N** not yet executed — run on the integrated head. Historical markings remain as recorded in every case.

### 8.1 Cases 01–40 (tester-marked executed)

| TC | Class | What to recheck | Driven by |
|---|---|---|---|
| 01 | T | Admin login return; admin+gm display; disabled login refused | CP-4 |
| 02 | F | Campaign lists/capabilities under new bootstrap; GM2 loses world creation | CP-4 |
| 03 | T | Hierarchy, Back/Forward, no stale flash after bootstrap change | CP-4 |
| 04 | F | Creation eligibility per ADR 0020 (system GM, use grant) | CP-4 |
| 05 | T | Counts equal list for GM2 (no drafts without `read_private`) vs owner | CP-4 |
| 06 | T | Parties disclosure smoke | CP-4 |
| 07–08 | T | Player/public Knowledge smoke; no regression | CP-4 |
| 09 | T | Member preview by GM2 (subject authority; no private world prep) | CP-4 |
| 10 | X + T | Archived reference expectation per DR-1; draft visibility needs `read_private` | DR-1, CP-4, CP-7 |
| 11 | F | Setup with system GM + world eligibility; existing-timeline reuse denial | CP-4 |
| 12 | F | Cancel/recovery in the new setup flow | CP-4 |
| 13 | F | Invitations keep system roles; explicit campaign roles; **establish observer** | CP-4 |
| 14 | T | Calendar (`world.manage`) vs time points (E1); create T0–T4/Between | CP-4 |
| 15 | D + T | Clock event explanation; optional cause; runtime GM advance without world role | CP-9a/b |
| 16–17 | T | Location/org/religion authoring by Editor, review by Reviewer, GM2 read-only; missing kinds and Archive summary edit | CP-4 |
| 18 | T | NPC shared canon vs PC exception (GM2 can create/publish PC) | CP-4 |
| 19 | D + T | Build activation explanation; B/NPC state and builds | CP-9a |
| 20 | T | Party lifecycle by runtime GM; Reserve restore | CP-4 |
| 21 | D + T | Join explanation; B leave/rejoin | CP-9a |
| 22 | D | Compatible roles, accurate rejection, roster on detail, member roster | CP-1, CP-3, CP-8 |
| 23 | T | Staged Run unaffected; roster section present; inputs kept | CP-3 |
| 24 | T | Start/log/clock bar on a fresh session | CP-4 |
| 25 | D + T | Event correction view explanation; Wrong-title replacement variant | CP-9a |
| 26 | T | Quest definition by world roles | CP-4 |
| 27 | T | Quest runtime by campaign-only GM; global vs party | CP-4 |
| 28 | T | Claim workspace stages under Editor vs Reviewer vs GM2 | CP-4 |
| 29 | T | Review/publication by Reviewer; finish unpublished-subject blocker | CP-4 |
| 30 | T | Party/public/individual knowledge variants not yet evidenced | CP-4 |
| 31 | X + D | Archive browse; archived direct read per DR-1; no new knowledge writes | CP-7, DR-1 |
| 32 | T | Sources need world edit; attach/detach/reattach; separate keys | CP-4 |
| 33 | T | Dungeon structure by world roles | CP-4 |
| 34 | T | Dungeon runtime by campaign-only GM; correction variant | CP-4 |
| 35 | T | Relationship definitions (world) vs runtime status (campaign); member reader | CP-4 |
| 36 | T | Org members/offices reader (f0aae3b) under world scopes | CP-4 |
| 37 | T | Named travel by runtime GM on a fresh session; clock untouched | CP-4 |
| 38 | T | Portrayal private read/edit needs world authority; runtime separate; resource variant Blocked | CP-4 |
| 39 | T | Item definitions world-gated; Charm/Draft created | CP-4 |
| 40 | D + T | Instance exception; owner inventory via character nav; viewer inventory | CP-5, CP-6 |

### 8.2 Cases 41–58 (not executed) — all N on the integrated head

| TC | Notes | Driven by |
|---|---|---|
| 41–44 | Fresh Charm, session and encounter HP; retest 42 roster identity | CP-11 prep |
| 45–46 | Explicit source links; editable history fixture | CP-4 |
| 47 | Queue and lifecycle with Editor/Reviewer split | CP-4 |
| 48 | Validation/stale/retry/no-store with CP-2 behaviour | CP-2 |
| 49 | Denial matrix over the regenerated route manifest, including Sharing, system roles, Reader catalog and member readers | CP-4e |
| 50 | End/review/archive on a fresh session; roster on completed detail | CP-3 |
| 51 | Archive/restore guards with separated world/campaign authority | CP-4 |
| 52 | Branch by Owner/Editor; inherited clock/build cutoff | CP-4 |
| 53 | Viewer distinct from Reader | CP-4 |
| 54 | CSRF/signed-out; world-role, use-grant and system-GM revocation on next request | CP-4 |
| 55 | AT/responsive on final layouts, including new Sharing, system-role editor, character nav, roster, archive filter, event explanation, clock cause form | CP-11 |
| 56 | Clean deployment: bootstrap admin = admin+gm; invited player gets explicit campaign role and character link; owner inventory reachable | CP-11 |
| 57 | Privacy evidence (receipts/audit/reporting role), no secrets in artefacts | CP-11 |
| 58 | Targeted claim allow/deny never yields world authority or archive browse; preview agreement | CP-4, CP-7 |

### 8.3 New scenarios

| ID | Scenario | Expected |
|---|---|---|
| SR-M1 | Admin creates a GM-only account; GM signs in with no campaigns | Create a world offered; no account admin |
| SR-M2 | Admin-only account | Manages accounts; cannot create worlds or read any world/campaign |
| SR-M3 | Populated upgrade identities | §4 CP-4f role expectations on the acceptance copy |
| SR-M4 | Editor vs Reviewer vs both | Edit-only, review-only, union; self-approval allowed when both |
| SR-M5 | Reader vs Viewer | Reader sees the three-category published catalog; Viewer only world/timelines/calendars; neither sees campaigns or drafts |
| SR-M6 | Use grant hosting | Unused timeline ✔; used timeline ✖ with reason; revoking blocks new hosting only |
| SR-M7 | Revoke then restore system GM from an Owner | Manage/share/transfer/host vanish next request; edit/review/timelines persist; restore returns them |
| SR-M8 | Campaign-only GM in shared world | Runs session, clock, events, encounters; creates/publishes PC and item instance; creates time point; world records open in runtime mode with explained disabled prep/review sections; no 403 blanks a page |
| SR-M9 | Same person GM in A and Player in B on one world | Capabilities switch with campaign; nothing of A visible from B |
| SR-M10 | Invitation and account split | Invited new account = player; existing account keeps system roles; campaign gm never mints system GM |
| SR-M11 | World and campaign ownership transfer | Authorship unchanged; last-owner guard; retain-as-Editor works |
| SR-M12 | Stranding and recovery | Disabling sole owner reports ids only; recovery script/command with mandatory reason; last admin protected |
| SR-M13 | Permission loss mid-edit | Role ended while editing a draft: private content cleared, typed input kept read-only, no submit |
| SR-M14 | Offline upgrade with a stale tab | Old tab reloads into the new bootstrap without errors |
| SR-M15 | Viewer inventory (after CP-6) | Viewer reads inventory-only view; no sheet, no mutation; deny wins; hidden properties absent |
| SR-M16 | Character record navigation | Same sections/Back behaviour from Characters and World; perspective unchanged |

---

## 9. Documentation updates during implementation

| CP | Documents |
|---|---|
| CP-0 | New untracked `docs/PHASE14_15_EVIDENCE_BASELINE.md` |
| CP-1 | Session participation matrix and error codes: `DOMAIN_MODEL.md` (session participants), API error catalog location used by `api/errors.py` docs, `UI_DESIGN.md` Run Session |
| CP-2 | `UI_DESIGN.md` feedback/recovery states (§6.1 vocabulary) |
| CP-3 | `UI_DESIGN.md` session detail/run roster |
| CP-4 | ADR 0020 amendment (Q10 sequencing, integration record); feature plan §16 addendum; `architecture/DATABASE_MODEL.md` §19; `DOMAIN_MODEL.md` security/world authority; `architecture/SYSTEM_ARCHITECTURE.md` §7.1 lock order, §18; `ENTITY_LIFECYCLE.md` §3.1a and §3.3 (`read_private` conjunction); `UI_DESIGN.md` §3/§4.3/§4.4/§4.6/§5.2/§6.4/§8; `PHASE13E_ACCESS_CONTRACT.md`; `LOCAL_DEPLOYMENT.md` upgrade note and §7.2 runbook; `operations/PLATFORM_ADMINISTRATOR_RECOVERY.md`; `PHASE15_VERIFICATION.md` integration section (after asking about the owner's pending edits); `PLANv2.md`/`PLAN.md`/`PROJECT_STATUS.md` status lines only |
| CP-5 | `UI_DESIGN.md` character record; `DOMAIN_MODEL.md` character access tiers note |
| CP-6 | `DATABASE_MODEL.md` capability catalog; relationship-capability matrix (15.2A-1 record); `DOMAIN_MODEL.md`; `PHASE13E_ACCESS_CONTRACT.md` grant catalog |
| CP-7 | `ENTITY_LIFECYCLE.md` §3.3 (explicit `lifecycle` parameter and its rejection rule); `UI_DESIGN.md` Knowledge |
| CP-8 | `DOMAIN_MODEL.md` session participant audience |
| CP-9 | `DOMAIN_MODEL.md` §13 event explanation, cause vs chain semantics; `DATABASE_MODEL.md` note on `event_causes` usage for clock causes |
| CP-11 | `PHASE14_15_MANUAL_TESTING.md` marked amendments (TC-10/31 expectations, role matrices, SR scenarios), integrated ledger, `PHASE15_MANUAL_ACCEPTANCE.md`, `PHASE14_VERIFICATION.md`, `PHASE15_VERIFICATION.md`, `PLANv2.md` status |

---

## 10. Decision register

Only DR-7 blocks the scoped-role fast-forward; nothing here blocks Batch A.

| DR | Decision | Current rule | Recommended | Implementation impact | Blocks |
|---|---|---|---|---|---|
| DR-1 | Archived historical references | §3.3: published-history definitions readable by reference in any lifecycle except deleted; guide TC-10/31 expect member denial | Keep §3.3; correct the guide | Guide amendment only; strict denial would need a policy change across every reference projection | CP-7 acceptance; TC-10/31 |
| DR-2 | Viewer inventory | Viewer = discover + summary; inventory needs full tier | New `character.view_inventory`; default for `viewer` and `observer_approved_viewer` (and listed for owner/controllers/portrayer for explicitness); not `former_controller`; explicit deny of the capability wins over full tier; restricted projection | Migration 139, matrix, resolver, projection, access UI label | CP-6 |
| DR-3 | Member session roster | Members get no roster | Discoverable participants only; no counts/placeholders for hidden | API member branch | CP-8 |
| DR-4 | Clock cause / explanation | Advance links only the previous clock event | Optional validated non-clock cause event + optional member-safe explanation in event `details`; admin reason stays in audit; manual advance shown as such; no schema unless chain/cause cannot be distinguished by cause event type | Command/API/form | CP-9b |
| DR-5 | Archive-browse eligibility (and Archived/All semantics) | No one can browse archives | Baseline campaign `canon.edit` ∧ `world.canon.read_private`; Archived = archived, All adds superseded/deprecated; drafts excluded; ineligible explicit parameter → 403. Alternative: let campaign-only GMs browse archived *published* claims | API eligibility | CP-7 |
| DR-6 | Build values in event explanations | n/a (ids only today) | Build labels to readers with full tier for that character (and GM); others see "build changed" | Explanation adapter | CP-9a |
| DR-7 | Scoped-role defaults (Q2, Q5, Q8, Q11, Q12, Q13, E2/E3 lifecycle, Viewer/Reader coexistence) and Q4 interpretation ("no campaign role requires system GM") | Adopted by the branch as defaults | Confirm as a set | None if confirmed; any change alters CP-4 | CP-4 fast-forward (not CP-4 start) |
| DR-8 | Fixture substitutions / variant equivalence | Unrecorded | Record actual values; targeted reruns; owner states whether any existing R operation counts | Ledger only | CP-11 retests of affected cases |
| DR-9 | Release disposition for any remaining Medium defects | Rubric: merge only with explicit evidence-backed risk decision | Fix D1–D7 per this plan; record any exception explicitly | Acceptance record | CP-11 |

---

## 11. Deferred refactoring and why

| Deferred | Why now is wrong | Revisit at |
|---|---|---|
| C9 unify legacy domain API clients (`api/knowledge.ts`, `world.ts`, `character.ts`, `session.ts`) with `api/http.ts` | No defect requires it; broad churn during role integration | Phase 16 when new clients are added; migrate one only while fixing a concrete inconsistency |
| C10 broad splits (QuestEditor, KnowledgeClaimPage, RelationshipsPanel, RelationshipEditor, EncounterPages; backend `access_grants`, `local_auth`, `world_explorer`, `domain/access`) | Size is not a defect; overlap with CP-4 would multiply conflicts | After CP-4/CP-9 reveal stable seams; Phase 16 authoring |
| C4 full staged-navigation/lifecycle-panel unification | Role modes must settle first; risk of collapsing Reviewer into Editor | After CP-4; Phase 16 proposals and Phase 18 change sets reuse navigation, not canon lifecycle semantics |
| C7 picker-state simplification | Display first (CP-9); picker semantics differ per domain | Phase 18 time extraction, Phase 20 scenes |
| Generic roster/member domain | Would merge distinct domains | Not planned |
| World-scoped authoring workspace (Q8) | Deferred by default | Phase 16/17 if owners need world-only authoring |
| Comprehensive World Reader browser | Outside accepted Q7 scope | Separate checkpoint before Phase 17 browser acceptance if wanted |
| Event name snapshots / historical backfill | Unknowable; would invent history | Phase 18 provenance may record names at promotion time going forward |
| `cause_kind` column on `event_causes` | Not needed if cause type disambiguates | Only if DR-4 shows ambiguity |
| Private-collaboration audience channel | Phase 16 domain; must not reuse `canon.edit` or `read_private` | Phase 16C |
| Promotion idempotency/provenance on the same commands | Phase 18 | Phase 18D (benefits from CP-4c eligibility and CP-9 explanations) |
| Build-history presentation beyond activation events | Phase 19 advancement | Phase 19.2 |
| Purpose-specific AI context from audience projections | Phase 20 | Phase 20.2 (consumes CP-4/CP-8/CP-9 projections) |
| Adapter command attribution | Phase 21 | Phase 21 (consumes CP-2 receipt semantics) |
| Windows CRLF frozen-seed failures; intermittent portal timing tests; legacy adapter revocation races | Pre-existing, not production defects under the rubric; harness hardening out of scope | Separate maintenance item |

---

## 12. Implementation and review batches

| Batch | Contents | Where | Review focus |
|---|---|---|---|
| **A (first)** | CP-0, CP-1, CP-2 | `phase15/completion` | Evidence integrity; participant matrix; receipt vs refresh correctness |
| B | CP-3 | `phase15/completion` | One roster projection, three callers |
| C | CP-4 (I-0…I-6) | `integration/scoped-roles` worktree, then fast-forward | Remerge-diff of conflicts; §5 tables; route manifest; upgrade rehearsal |
| D | CP-5, CP-6 | `phase15/completion` | Character nav; inventory policy and projection; migration 139 |
| E | CP-7, CP-8 | `phase15/completion` | Archive eligibility and paging; roster non-disclosure |
| F | CP-9a, CP-9b | `phase15/completion` | Audience-safe explanations; cause validation and atomicity |
| G | CP-10 | `phase15/completion` | Behaviour-preserving extraction only |
| H | CP-11 | acceptance copy + clean DB; PR to `main` for CI (owner-authorized) | Evidence completeness; owner decision |

### Batch A, ready to start

1. **CP-0**: write the baseline record and evidence snapshot (no DB writes needed for these two steps); take the dump and restore the baseline copy once the owner confirms no manual testing is in progress.
2. **CP-1**: domain role catalog + distinct mismatch code; extract `ParticipantForm`; tests.
3. **CP-2**: split mutation outcome from refresh outcome; Inventory panel states; Settings/ArchivedCampaigns refresh handling; one ContentEdit caller; TravelSection mock check; tests.

Historical implementation guidance: one commit per code checkpoint on `phase15/completion`, with explicit paths. The original instruction to leave the three owner-modified docs and CP-11 records uncommitted was superseded by the owner's later direction to commit the documentation still needed for acceptance.

---

## Closing summary

**Recommended work order:** CP-0 → CP-1 → CP-2 → CP-3 → CP-4 (integration worktree, fast-forward after DR-7) → CP-5 → CP-6 → CP-7 → CP-8 → CP-9a → CP-9b → CP-10 → CP-11.

**First implementation batch:** Batch A — CP-0 evidence baseline, CP-1 participant compatibility, CP-2 receipt/refresh/load-state contract.

**Decisions that block Batch A:** none of the policy decisions. CP-0's dump and baseline copy need only the owner's go-ahead to create the named database and confirmation that no manual testing is running; CP-1 and CP-2 need nothing.

**Plan path:** `docs/PHASE14_15_INTEGRATION_AND_CONSOLIDATION_PLAN.md` (committed as a dated planning record).

**Initial working-tree snapshot at plan preparation** (historical; not the current status):

```
 M docs/PHASE14_VERIFICATION.md
 M docs/PHASE15_MANUAL_ACCEPTANCE.md
 M docs/PHASE15_VERIFICATION.md
?? PHASE14_15_INTEGRATION_AND_CONSOLIDATION_PLAN.md
?? PHASE14_15_TESTING_ROLES_REFACTOR_AUDIT.md
?? docs/PHASE14_15_MANUAL_TESTING.md
```
