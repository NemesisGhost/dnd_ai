# Documentation review — 2026-11-08

**Recommendation:** remove eight historical documents outright, consolidate 33 more into a smaller set of maintained references, and retain the active plans, acceptance evidence, operational runbooks, and architectural decisions. Do not delete documents merely because their names contain `PHASE`, `PLAN`, or an old date.

The original review below was a proposal and changed only this report. The user subsequently authorized implementation. See the implementation receipt at the end for the completed cleanup, validation, and deliberate deferrals; the original inventory and recommendations describe the pre-cleanup baseline.

## Scope and confidence

Reviewed the working checkout of `phase15/completion`, with committed baseline `53416d5` on 2026-11-08. The inventory contains **101 documentation files: 97 tracked files, three untracked planning files, and one ignored local scratch file**. Together they occupy **5,103,919 bytes**, about 4.87 MiB. This excludes this report, dependencies, caches, generated output, and external evidence directories. It includes root and component READMEs, Copilot instructions, and the two repository-local skill files.

The review covered document purposes, headings, status declarations, closeouts, unresolved-work sections, contract sections, supersession statements, local Markdown links, and references from tracked code/configuration. I cross-checked selected claims against source, migration files, manifests, CI configuration, and local Git history. This is a documentation audit using targeted content review across the inventory, not a line-by-line correctness certification of every design or a fresh product acceptance run.

No test suites, database commands, deployment commands, or live CI checks were run. Recorded test results and owner decisions are attributed to the documents that contain them; they were not independently reproduced here. No external attachments or evidence directories were inspected.

At the start of the review, existing work included the following, all left alone:

- Modified `src/dnd_ai/persistence/tables/campaign.py` and `security.py`.
- Untracked `database/migrations/versions/145_character_revelations.py`.
- Untracked Batch 1, DEF-007, and P02 navigation implementation plans, identified individually below.
- Ignored `docs/Testing Notes.txt`.

The untracked migration and table edits mean the committed plan is not a complete description of work in progress. Additional character-revelation API/command/query files and related code/test edits appeared during the review; they were also left alone. Cleanup must use the actual checkout at implementation time, not treat this report as a frozen product-state assessment.

## 1. What can be removed outright

“Remove outright” means delete the whole document without first moving substantive sections into another maintained document. It still requires repairing references in the same cleanup change. The retained topic references listed below must remain. Historical details remain recoverable from Git; there is no need to create an archive copy of each deleted file.

These **eight tracked files total 250,919 bytes**, approximately 245 KiB.

| Document | Why the file can go | Retained authority / reference cleanup |
|---|---|---|
| [POSTGRES18_UPGRADE_PLAN.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/POSTGRES18_UPGRADE_PLAN.md) | Explicitly closed on 2026-08-08, with both workstreams completed (§8, line 294). It describes a one-time replacement of the old RDS instance and an already-completed local-loop transition. | `DATABASE_CONVENTIONS.md` §2, `DEVELOPMENT.md` §3, ADR 0012, and `INFRASTRUCTURE.md` already document the resulting version, development posture, and AWS configuration. Replace links in those documents and `PLAN.md` with the current references or a historical Git reference. Do not treat the old replacement procedure as a general production upgrade runbook. |
| [PHASE6_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE6_VERIFICATION.md) | Completed event/interaction implementation and successive correction-run diary. Its final status explicitly closes the phase (line 158). | Current event/interaction rules are in `architecture/DATABASE_MODEL.md` §27, lifecycle/architecture documentation, migrations, and tests. Retarget the citation in `src/dnd_ai/api/interactions.py` and the schema document's historical links. |
| [PHASE7_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE7_VERIFICATION.md) | Historical quest/knowledge delivery and correction evidence; phase completion is explicitly recorded. | Keep quest/knowledge contracts in the domain/schema/lifecycle documents and tests. Old statements that a correction PR was not yet merged are dated observations, not present-day tasks. |
| [PHASE8_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE8_VERIFICATION.md) | Completed relationship/organization delivery with final-head CI evidence (§Verification status). | Keep the relationship/organization schema and domain references. The document is not needed as a current operating guide. |
| [PHASE9_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE9_VERIFICATION.md) | Seven correction-pass narratives and AWS verification history. The last entry records the successful run `31349958030` and closes Phase 9; earlier “still required” paragraphs are superseded within the file. | Keep current item/integration semantics in schema/architecture references and implementation tests. Retarget comments/docstrings in item and integration commands, API, migrations 077/079, and `test_foundry_sync_commands.py`. Do not change migration behavior. |
| [PHASE10_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE10_VERIFICATION.md) | Historical API vertical-slice checklist, one fixture fix, and local environment troubleshooting. It is not the current API contract or current verification result. | `architecture/DUNGEON_FLOW.md`, `SYSTEM_ARCHITECTURE.md`, the vertical-slice scenario tests, and `DEVELOPMENT.md` retain the ongoing requirements. Remove the status-page link. |
| [PHASE13E_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE13E_VERIFICATION.md) | Closed access-management delivery record (lines 294–299), with current endpoint contracts maintained elsewhere. | Keep `PHASE13E_ACCESS_CONTRACT.md` until its replacement exists. Its §6 already holds the manual-validation scenarios, including the deferred audience-preview walkthrough. Do not infer that deletion accepts those deferred manual checks. |
| [PHASE15_CP10_HANDOFF.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE15_CP10_HANDOFF.md) | Explicitly historical and CP-10-complete at line 3. The deferred refresh callers became the DEF-001 inventory and repair/retest work. Its old return-state utilities also predate the P02 navigation consolidation. | Keep current refresh/recovery behavior in `UI_DESIGN.md` and the DEF-001 material until that material is consolidated. Remove historical handoff links from the integration/verification records. |

Confidence is high that these files have no remaining standalone maintenance role. That does not mean the work they describe has been reverified on today's head.

## 2. Documents to retire after consolidation

These files contain useful material or unresolved obligations. They are **not** approved for immediate deletion. Each group below specifies what must survive and where it should live. The full inventory in §8 identifies all 33 consolidation candidates.

### A. Replace the old implementation encyclopedia with topic authorities

**Source to retire:** [PLAN.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PLAN.md), 416,069 bytes.

Its opening explicitly gives future-roadmap authority to `PLANv2.md`, but retains architectural history and the Phase 15 checkpoint sequence. It is still cited by **282 other tracked text files in the scanned source/config/documentation set**, including **220 non-Markdown files**. These are filename-reference counts, not a claim that code opens the file at runtime. It cannot safely be treated as a redundant roadmap and simply deleted.

Before retiring it:

| PLAN.md content | Destination |
|---|---|
| §§1–22: domain implementation descriptions and architectural decisions | Retain unique current rules in `DOMAIN_MODEL.md`, `architecture/DATABASE_MODEL.md`, `SYSTEM_ARCHITECTURE.md`, and `ENTITY_LIFECYCLE.md`; remove duplicated tables and implementation narration. |
| §23: authentication, authorization, browser security, Foundry identity | A maintained `docs/api/ACCESS_CONTROL.md` assembled with the access/scoped-role contracts; Foundry-specific integration behavior stays in `foundry-module/README.md`. |
| §24.0–24.1: verification and exit policy | `DEVELOPMENT.md` §6/§10. Preserve policy requirements rather than all historical execution records. |
| §24 phase entries | Future order stays in `PLANv2.md`. Current Phase 15 scope/gates go to `PROJECT_STATUS.md`, the active P03-A plan, and the acceptance documents. Closed milestone evidence can be summarized in `DELIVERY_HISTORY.md`. |
| §25: vertical slice | `architecture/DUNGEON_FLOW.md`; retain any unique acceptance requirement. |
| §26: testing strategy | `DEVELOPMENT.md` testing sections; preserve unimplemented requirements as explicit backlog items. |
| §§27–29: operations, deferred decisions, success criteria | `LOCAL_DEPLOYMENT.md`, `PLANv2.md`, and `BACKLOG.md`, according to purpose. |
| §§30–31: old AWS database/application deployment plans | Retain still-useful optional RDS procedures in `INFRASTRUCTURE.md`. Retire superseded AWS-first/Fargate delivery expectations rather than presenting them as required work. |
| §32: local deployment | `LOCAL_DEPLOYMENT.md`, linked from the Phase 17 roadmap. |

ADRs 0001–0007 still have “Stub — to be written” context/consequence sections that point into `PLAN.md`. Complete those concise rationales from existing material before removing their source. Preserve ADR identifiers.

Keep `PLANv2.md` as the single roadmap. Renaming it to `ROADMAP.md` would improve discoverability, but that is optional and should happen after reference cleanup, not alongside the largest extraction.

### B. Turn phase-branded backend reports into current API references

**Sources to retire:** `PHASE13D_BACKEND_READINESS.md`, `PHASE13D_CHARACTER_SHEET_BACKEND.md`, `PHASE13E_ACCESS_CONTRACT.md`, and `SCOPED_ROLE_IMPLEMENTATION_PLAN.md`.

Recommended destinations:

- **`docs/api/READ_API.md`:** pagination, World Explorer/search, Knowledge browse semantics, audience projections, response/error behavior, and outstanding limitations from the 13D readiness report.
- **`docs/api/CHARACTER_SHEET.md`:** active-build selection, branch inheritance, raw versus derived mechanics, authorization, empty-build behavior, and known calculation limitations from the sheet report.
- **`docs/api/ACCESS_CONTROL.md`:** system/world/campaign authority, membership/role/grant/group/invitation/account contracts, relevant owner decisions, operator recovery links, and the current owner/reveal/public-profile amendments. Link `AUDIT_HISTORY_API.md`; do not fold that independent contract into an already large access reference.

Strip implementation file lists, checkpoint instructions, superseded alternatives, fixture-specific execution logs, and repeated test counts from these references. Put reusable fixture setup in `DEVELOPMENT.md` or its existing script documentation; move actual unresolved work to `BACKLOG.md`.

These are substantive references: the 13D readiness, sheet, and 13E access files are cited by **14, 4, and 12 non-Markdown tracked files**, respectively. For example, `src/dnd_ai/api/pagination.py`, `queries/world_explorer.py`, `queries/character_build_resolution.py`, and `api/memberships.py` refer to them. Retarget those references during extraction.

Do not blindly copy “current” paragraphs. The readiness report says World Explorer and pagination do not exist in §3, then records them delivered in §§9–10. The scoped-role plan's opening says no CI run, while its later integration history records one. The new references need one current description per behavior.

### C. Collapse the acceptance-document layers without losing evidence

Retain these distinct responsibilities:

1. **Specification:** `PHASE14_15_HOWTO_FIRST_CAMPAIGN.md` and its companion scenarios. This is currently an acceptance test journey, not a general end-user tutorial; its title and navigation should make that clear.
2. **Traceability:** `PHASE14_15_COVERAGE_MATRIX.md`, mapping stable case/variant IDs to specification and evidence.
3. **Results and decisions:** `PHASE14_15_ACCEPTANCE_LEDGER.md`, retaining separate human, scripted-browser, automated, database, and accessibility evidence.
4. **Defects:** `PHASE14_15_DEFECT_REGISTER.md`, with one current disposition per defect and links to historical evidence.
5. **Run identity/setup:** `PHASE14_15_ACCEPTANCE_ENVIRONMENT.md`, clearly distinguishing old baselines from the next run's environment.

**Sources to retire after extraction:**

| Source | Content that must survive | Destination |
|---|---|---|
| `PHASE14_15_MANUAL_TESTING.md` | All original TC-01–TC-58 requirements, any unique steps/expected results, and historical results with their original baseline. | Current journey/scenarios and coverage matrix for requirements; ledger for evidence. The restarted ledger explicitly says previous results are not fresh passes. |
| `PHASE15_MANUAL_ACCEPTANCE.md` | Page/panel-specific keyboard, screen-reader, viewport, zoom, theme, reduced-motion and carried-forward checks, plus the owner completion decision fields. | TC-55 companion specification and coverage matrix; ledger for results/sign-off. Prove coverage before deleting the old matrix. |
| `PHASE14_15_ACCOUNT_MANIFEST.md` | Account-preservation/rename record, baseline identity, verification limits, and evidence references. | A historical appendix to the acceptance environment record. It is a dated handoff, not a live account directory. |
| `PHASE14_15_STEP_G_REPAIR_REPORT.md` | Repair provenance and maintenance exceptions, DEF-007/DEF-008/DEF-DOC-01 links, and remaining unverified expectations. | Ledger evidence appendix and defect register; reusable test instructions in the journey. |
| `PHASE15_DEF001_INVENTORY.md` | The 26-operation coverage list, intentional differences, regression-test mapping, and still-relevant recovery contract. | RC-10 coverage section/matrix and `UI_DESIGN.md` recovery behavior. |
| `PHASE15_DEF001_BROWSER_RETEST.md` | Per-run SHA/method/evidence attribution, failures and corrections, and the unexercised command variants in §9.6. | Ledger evidence appendix and RC-10 variant mapping. “Every operation has one tested variant” must not become “every command passed.” |

The ledger is already **285,612 bytes in 468 lines** because many table cells contain entire implementation and review narratives. Retain immutable evidence, but move code implementation descriptions to their topic reference or a concise delivery-history entry. Add a short, maintained current-disposition summary that links to the evidence; readers should not have to interpret hundreds of historical corrections to learn today's state.

Do not combine the specification, result ledger, and defect register into one giant file. Their different purposes help prevent a written test or a code review from being mistaken for acceptance.

### D. Consolidate investigation, handoff, and finished repair plans into one backlog

**Sources to retire:**

- `PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md`
- `PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md`
- `PHASE14_15_INTEGRATION_AND_CONSOLIDATION_PLAN.md`
- `PHASE14_15_APP_INTERACTION_REPAIR_PLAN_BATCH1_2026-11-01.md` — untracked
- `PHASE14_15_DEF007_EFFECTIVE_TIME_MEMBERSHIP_PLAN_2026-11-01.md` — untracked
- `PHASE14_15_P02_NAVIGATION_CONTEXT_PLAN_2026-11-02.md` — untracked
- `PHASE14_15_P02_NAVIGATION_ROUTE_AND_GUARD_AUDIT.md`
- `PHASE14_15_P02_RECONCILIATION_2026-11-04.md`

Create **`docs/BACKLOG.md`** as the current outstanding-work register. Preserve the original finding/package IDs, requirement, disposition, dependency, implementation link, acceptance obligation, and evidence link. Keep `DEF-*` details in the defect register and link them rather than duplicating the full reports. Keep product delivery order in `PLANv2.md`, not in a second backlog roadmap.

Specific extraction requirements:

- Preserve the investigation's **43 original finding IDs** and package crosswalk. Later packages such as P03-B/C and the other workflow packages are not all complete merely because P02 was accepted.
- Carry the integration plan's DR-1–DR-9 decisions and remaining deferred work. Preserve the distinction between a proposed default and a recorded owner approval.
- Retain current effective-time membership semantics in `DOMAIN_MODEL.md`/`DATABASE_MODEL.md`, API contracts, and the defect record; the untracked DEF-007 plan's “plan only” opening is not a reliable present status.
- Move P02 navigation state/guard/route contracts to `UI_DESIGN.md` §§4.8/5.11 and relevant source comments. Preserve the owner-approved legacy-entry adapter behavior. Do not resurrect its superseded removal proposal.
- Carry B20 keyboard activation, B9 physical Escape and the separate backdrop check, B16 actual 200%/400% zoom, and B21's owner-deferred/unverified screen-reader status from the latest ledger evidence. Preserve P02 approval as a distinct decision.
- Retarget `portal/src/navigation/routeMeta.ts` and `hooks/useUnsavedChangesGuard.ts`, which cite the route/guard audit.

The three untracked plans are **not recoverable from the committed baseline**. Review/preserve their unique decisions and requirements before any later deletion. Several plans reference an external proposed `APP_INTERACTION_STANDARDS.md`; the repository cannot serve as a self-contained authority until approved requirements from that source have a maintained local home. This review did not read or adopt that external file.

### E. Retire historical verification files that still carry unique obligations

**Sources to retire after extraction:** `PHASE1_VERIFICATION.md` through `PHASE5_VERIFICATION.md`, `PHASE11_VERIFICATION.md`, `PHASE14_VERIFICATION.md`, `SCOPED_ROLE_INTEGRATION_VERIFICATION.md`, and `PLATFORM_REVIEW_2026-09-25.md`.

Use one concise **`docs/DELIVERY_HISTORY.md`** for useful milestone evidence: scope, date, source SHA, recorded CI/PR reference, accepted limitations, and a link to Git history for the full account. This should be an index, not concatenated verification files.

Before deleting these sources:

- **Phases 1–4:** account for the historical orphaned KMS resource and `iam_auth_db_users` drift concern. The remote-state and narrower test-role issues are also repeated in `INFRASTRUCTURE.md`; reconcile them there as dated/optional-AWS matters. This audit did not inspect AWS and does not establish whether any live resource still exists. Do not transform a historical resource observation into either a confirmed current incident or a silent closure.
- **Phase 5:** retain the proportional test-infrastructure policy in `DEVELOPMENT.md`, relevant current schema decisions in `DATABASE_MODEL.md`, and the historical closeout reference. `scripts/verify.sh` cites this document. Preserve any still-applicable creature/spawn/knowledge deferral in the current roadmap/backlog, without carrying forward requirements that later phases already implemented.
- **Phase 11:** preserve the missing live Foundry v13 acceptance gate in `PROJECT_STATUS.md`/`BACKLOG.md` and the live procedure in `foundry-module/README.md`. The file expressly says automated completion did not supply that run. Preserve the security decision to reject legacy shared `FoundrySystem` credentials in current integration documentation.
- **Phase 14:** retain the recorded PR/CI closure and the carried navigation/manual limitations. Reconcile them with P02's later acceptance and follow-ups; do not claim the original manual run happened retroactively.
- **Scoped-role integration:** preserve the actual snapshot-upgrade rehearsal, data-preservation limits, approved defaults, and separate browser/AT/CI outcomes in the acceptance ledger/history. Its initial “not merged/no CI” framing and later run record cannot both describe the present.
- **September platform review:** disposition all **18 findings**, and extract still-relevant product/deployment requirements into the roadmap/runbook/backlog. This is not safe to delete as “old review, presumably fixed.” For example, `httpx` still appears in the `dev` optional dependency group in `pyproject.toml`, while the provider imports it; the dependency concern is not disproved by the present manifest. That is a source-level observation, not a fresh runtime reproduction or severity regrading.

### F. Consolidate setup, AWS, and assistant guidance

**Sources to retire after extraction:** `CONTRIBUTING.md`, `QUICKSTART.md`, `CHECKLIST.md`, and `AI_ASSISTANT_GUIDE.md`.

- Put unique contributor workflow, external-key configuration pointers, Git conventions, and help routing into **`DEVELOPMENT.md`**. Remove the duplicate setup/test command sequences from `CONTRIBUTING.md`. A root README link can take contributors directly to development setup.
- Merge the useful AWS quick-start and checklist into **`INFRASTRUCTURE.md`**, clearly named “Optional AWS RDS.” Keep its operational commands once. Do not remove the AWS documentation while Terraform and optional scripts remain supported in the repository. Move the long OIDC state-management explanation from `terraform/README.md` into this reference; leave that README as a short component pointer.
- Remove duplicated architectural rules, technology stack, documentation maps, and development workflow from **`AI_ASSISTANT_GUIDE.md`**. Move only useful, unique worked examples into the corresponding conventions/lifecycle/architecture section. Then remove the guide.
- Keep **`CLAUDE.md`** as the assistant entrypoint and **`.github/copilot-instructions.md`** as the tool-discovery entrypoint. Reduce the latter to routing plus any genuinely tool-specific instructions; do not delete a recognized tool instruction file merely to reduce the count. Keep the two local skills, with their policy links updated.
- Keep **`portal/README.md`**, but limit it to running/testing the portal, source organization, and links. Its long route lists, phase verification, learning checkpoints, and replicated access contracts belong in the current topic documents or delivery-history index.

### G. Extract the completed A1 design after the active handoff is stable

**Source to retire later:** `PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md`.

The owner eligibility policy, command/recovery paths, lock-order rules, accepted D3 decision, DEF-011/DEF-013 disposition, and verification limits must survive in the access reference, system architecture, defect register, and delivery history. It has five non-Markdown referrers and is a governing input to the active P03-A work. Do this after reconciling the active plan and working changes; do not remove it during an unrelated in-progress implementation.

## 3. Documents to retain

These distinctions remain useful and should not be erased to achieve a smaller file count:

| Documents | Reason to retain |
|---|---|
| `README.md`, `PROJECT_STATUS.md`, `PLANv2.md` | Product introduction, current delivery state, and future roadmap serve different questions. Keep each concise and link between them; stop repeating historical test counts and findings in the status page. |
| `DOMAIN_MODEL.md`, `architecture/DATABASE_MODEL.md`, `DATABASE_CONVENTIONS.md`, `ENTITY_LIFECYCLE.md`, `architecture/SYSTEM_ARCHITECTURE.md` | Vocabulary, schema, database rules, entity workflows, and service/transaction architecture are different authorities. Consolidate duplicated passages, not these whole documents into a monolith. |
| `architecture/DUNGEON_FLOW.md` | A reusable cross-domain acceptance scenario. It is not just a completed implementation diary. |
| `UI_DESIGN.md`, `UI_STYLE_GUIDE.md` | Behavior/information architecture and presentation standards are different responsibilities. Move generic spacing/tokens/card anatomy into the style guide and keep navigation/permission/recovery semantics in UI design. Remove chronological implementation notes and repeated rules. |
| `AUDIT_HISTORY_API.md` | An active read API and safe-presentation/allowlist contract, referenced by seven non-Markdown files. Keep its security semantics separate from generic access management. |
| `DEVELOPMENT.md`, `LOCAL_DEPLOYMENT.md`, `operations/DATABASE_RECOVERY.md`, `operations/PLATFORM_ADMINISTRATOR_RECOVERY.md` | Development setup, intended deployment topology, data recovery, and administrator recovery have separate audiences and failure modes. The recovery documents are active runbooks, not disposable phase plans. Clearly label intended versus implemented deployment features. |
| `INFRASTRUCTURE.md` | Optional AWS reference while the corresponding code remains. Consolidate it; do not imply that documentation cleanup decommissions infrastructure. |
| `ISSUE_GRADING_RUBRIC.md` | Current review policy, recently updated. Link it instead of copying scoring rules into every plan. |
| Active P03-A implementation plan | Contains finalized but not fully implemented A3 design, the open D6/A4 decision, prerequisite records, and unresolved defects. At 412,772 bytes it needs editing, but is not obsolete. |
| `R19_FOUNDATION_IMPLEMENTATION_PLAN.md` | Still proposed/unimplemented implementation work. Accepted ADRs 0021–0023 do not imply the implementation plan or Phase 19 is complete. |
| `PHASE15_VERIFICATION.md` and the six retained acceptance files | Phase 15 remains under active implementation/acceptance. Trim duplicate narrative and clarify current versus historical evidence; do not erase unresolved gates. |
| All 23 ADRs and `_template.md` | Decision history is valuable even when superseded. Keep identifiers and explicit supersession chains. ADRs 0008, 0011, and 0018 are correctly historical, not instructions to follow today. |
| Component READMEs and local skill entrypoints | They provide discoverable component/tool instructions. Short pointers are appropriate where details live elsewhere. |

ADRs 0021–0023 are unusually detailed, especially ADR 0021 at roughly 120 KB. They currently contain accepted policy for pending work. Prefer linked current contracts and shorter decision records when those contracts stabilize; do not move or paraphrase approval-sensitive rules during this cleanup without a precise mapping.

## 4. Concrete contradictions and maintenance defects

These examples explain why consolidation is necessary beyond merely reducing file count. Locations refer to the reviewed snapshot.

| Finding | Evidence | Recommended correction |
|---|---|---|
| P03-A contradicts itself about its next prerequisite. | [P03-A plan](PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md), line 3, says P3 is designed and not implemented. Lines 3667–3706 record implementation, limiter correction, and independent review; Git contains `0790423`, `49b683d`, and the `53416d5` handoff. | Make its opening a single maintained current state. Keep dated entries as evidence, not competing status summaries. Do not describe the untracked A3-related edits as a completed feature. |
| P02 approval is both present and denied in the same ledger. | [Acceptance ledger](PHASE14_15_ACCEPTANCE_LEDGER.md), line 466, records owner acceptance at `81bf164`. Line 468 ends by listing “P02 browser acceptance and owner sign-off” as still open. The older [reconciliation](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_P02_RECONCILIATION_2026-11-04.md), lines 9/206–211, also says nothing is accepted. | Preserve the recorded approval and all incomplete browser outcomes separately. Correct the current-disposition summary without turning partial/deferred tests into passes. |
| Current handoffs say P03-A has not started. | [Remaining-work handoff](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md), line 7; [investigation](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md), line 9. The P03-A plan and subsequent commits record multiple delivered slices. | Remove redundant current-status paragraphs; route to the status page and active plan. |
| ADR acceptance is stale in an upstream ADR. | [ADR 0020](adr/0020-scoped-system-world-and-campaign-roles.md), line 8, calls ADR 0021 a pending Proposed document. [ADR 0021](adr/0021-shared-actor-identity-control-and-authoring-responsibility.md), line 3, records acceptance on 2026-11-06. | Update the cross-reference's decision status while retaining any distinct implementation/effectiveness gate. Accepted architecture is not proof all code exists. |
| The public status page still presents superseded findings and inventories. | [PROJECT_STATUS.md](PROJECT_STATUS.md) is dated 2026-10-06 but carries September counts and old Foundry failures. Current `foundry-module/package.json` runs `node --test`; it and `module.json` both say `0.2.0`. Current CI separately checks `scripts/wait_for_ci.py`. Its portal summary also says 13E mutations do not exist despite the access contract recording them delivered. | Rewrite as a dated current milestone/gate summary. Remove fixed findings and historical static counts; keep original measurements in historical evidence. Do not infer current test success from configuration alone. |
| Assistant instructions contain obsolete implementation claims and conflicting data posture. | [Copilot instructions](../.github/copilot-instructions.md) say the API has no committed source and that any existing database content will be dropped. [CLAUDE.md](../CLAUDE.md) §6 still says CI uses AWS while §5 rule 11 says containerized PostgreSQL. | Reduce duplicated instructions to authoritative links. Reconcile the restart language with current data-preservation/recovery policy; no cleanup task should inherit blanket permission to drop working data. |
| Contributor setup is stale. | [CONTRIBUTING.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/CONTRIBUTING.md), line 34, says React UI work has not begun and suggests Node 18+. `portal/` is implemented and has its own prerequisites. | Merge into `DEVELOPMENT.md`; use the actual component/toolchain requirements. |
| AWS documents disagree about the same environment. | [CHECKLIST.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/CHECKLIST.md) says dev does not override deletion protection and that bootstrap is still future work. [INFRASTRUCTURE.md](INFRASTRUCTURE.md) records the resolved overrides; `terraform/environments/dev/main.tf` lines 86–87 set `deletion_protection = false` and `skip_final_snapshot = true`. | Maintain one AWS configuration/operation reference. Separate historical instance state from current configuration. |
| Earlier cleanup left dangling documentation links. | Inline Markdown scan found **10 broken links to two absent files**: `PHASE4_REMAINING_ISSUES.md` and `PHASE5_REMAINING_ISSUES.md`. They occur in Phase 4/5 verification and `architecture/DATABASE_MODEL.md`. | Retarget surviving rationale or use explicit historical Git references; do not leave nonexistent source documents looking authoritative. |
| Many additional dependencies are prose or anchor references, not file links. | The AWS quick-start links to removed contributor sections; `PLAN.md` references frequently use old §23/§29 numbering, although delivery and AWS database sections are now §§24/30. The integration plan mentions an absent testing-role audit/evidence baseline; 13E verification mentions an absent remaining-implementation plan. | Audit inline code/prose filenames and anchors as well as Markdown paths. Distinguish a historical/proposed artifact from a required present reference. |

The broken-link count is deliberately narrow: inline local links to Markdown files in tracked Markdown documents. It is not a full external-link, heading-anchor, or code-reference validation result.

## 5. Proposed smaller documentation layout

Use existing topic files as destinations wherever possible. The only proposed new maintained documents are:

- `docs/README.md` — a small audience/topic index with current authority and active-plan links.
- `docs/BACKLOG.md` — outstanding findings and dependencies, preserving original IDs.
- `docs/DELIVERY_HISTORY.md` — concise milestone evidence index.
- `docs/api/READ_API.md`
- `docs/api/CHARACTER_SHEET.md`
- `docs/api/ACCESS_CONTROL.md`

Keep the roadmap, status, domain/architecture references, UI references, developer/operator guides, acceptance set, active plans, and ADR directory. An `archive/` directory full of copied plans would reduce visibility but preserve the maintenance/search problem; prefer Git history for retired execution diaries.

The inventory recommends **8 removals, 33 consolidations, 59 retentions, and 1 local-only review**. Three consolidations are untracked files. If every consolidation eventually retires its source and the six destinations above are added, the maintained tracked set would fall from **97 to approximately 65 files**, excluding this review report. This is a staged target, not a promise to delete 38 tracked files in the first change. Much of the useful content moves rather than disappears; file-count reduction is not equivalent to byte savings.

## 6. Suggested implementation order and acceptance checks

1. **Establish authority and correct immediate drift.** Add the index; refresh current status; reconcile P03-A, P02 approval, and ADR 0020 cross-references. Preserve old evidence attribution. Do not change active implementation scope.
2. **Remove the eight direct candidates.** Repair all inbound links and relevant source comments/docstrings. Avoid changing migration SQL, test behavior, or application code behavior. Git holds their original contents.
3. **Consolidate low-coupling duplicates.** Contributor/AWS setup and assistant guidance, then trim component READMEs.
4. **Extract current API contracts and outstanding findings.** Produce a source-section-to-destination map; update code/document references; only then remove the 13D/13E/scoped-role reports and investigation/handoff layers. Preserve unique content from untracked files before retiring them.
5. **Reconcile acceptance material.** Account for every original case/variant, accessibility requirement, defect, owner decision, and evidence baseline. Then retire old manuals and repair/retest wrappers.
6. **Retire PLAN.md last.** Resolve its large reference set, incomplete ADR rationales, Phase 15 checkpoint/gate dependencies, security contracts, and test-policy requirements first. Defer A1 extraction until the active P03 handoff is stable.

For each batch, review the diff and verify local documentation paths, anchors, and prose/code filename references. Run `git diff --check`. A content-only reorganization does not need a database test run. If a documentation-dependent test or tool is found during implementation, run that focused check; if behavior changes become necessary, separate and test those changes appropriately.

Acceptance for cleanup itself:

- No removed file remains a required current reference; a historical reference is explicitly tied to a retained commit.
- Every live rule has an identifiable topic authority, not two conflicting plan descriptions.
- All unresolved work has a current home with its original identifier and disposition.
- No acceptance result is upgraded, reset, silently dropped, or attributed to a different SHA/method.
- No untracked/local-only content is assumed recoverable from Git.
- No external evidence artifacts, database content, infrastructure, or unrelated working changes are altered.

For tracked source material in this review, `git show 53416d5:docs/<filename>` retrieves the reviewed committed version. That command does not apply to the three untracked plans or the ignored scratch file.

## 7. Local scratch file

`docs/Testing Notes.txt` is explicitly ignored by `.gitignore` line 204. It contains local connection/session scratch material, credential-like values, and product observations. Values are intentionally not reproduced in this report.

Treat it as a personal working note, not maintained project documentation. Before optionally removing it, transfer any unique product observations into the finding backlog and preserve any local information the owner still needs outside project documentation. Do not add it to Git or copy it wholesale into a public report. It is not included in the eight proposed direct deletions.

## 8. Complete inventory and proposed disposition

`Remove` = the eight whole-file deletions in §1. `Consolidate` = preserve the material described in §2, then retire the old file. `Retain` can include substantial trimming or status correction. `Local review` is separate from repository cleanup. Paths below are relative to the repository root; this report is excluded from the baseline inventory.

| File | Tracking | Disposition | Purpose / required action |
|---|---|---|---|
| [.claude/skills/verify-local/SKILL.md](../.claude/skills/verify-local/SKILL.md) | Tracked | Retain | Active verification-tool entrypoint; keep concise. |
| [.claude/skills/wait-for-ci/SKILL.md](../.claude/skills/wait-for-ci/SKILL.md) | Tracked | Retain | Active CI-observation entrypoint; retarget old PLAN policy links. |
| [.github/copilot-instructions.md](../.github/copilot-instructions.md) | Tracked | Retain | Keep tool entrypoint; reduce to current routing and tool-specific rules. |
| [CLAUDE.md](../CLAUDE.md) | Tracked | Retain | Assistant entrypoint; correct remaining AWS-CI contradiction. |
| [README.md](../README.md) | Tracked | Retain | Product entrypoint; link current status and topic references. |
| [database/seeds/README.md](../database/seeds/README.md) | Tracked | Retain | Small useful local seed-format pointer. |
| [docs/AI_ASSISTANT_GUIDE.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/AI_ASSISTANT_GUIDE.md) | Tracked | Consolidate | Unique examples to topic references; remove duplicated operating rules (F). |
| [docs/AUDIT_HISTORY_API.md](../docs/AUDIT_HISTORY_API.md) | Tracked | Retain | Current audit read/projection contract; separate API authority. |
| [docs/CHECKLIST.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/CHECKLIST.md) | Tracked | Consolidate | One optional-AWS operating reference in INFRASTRUCTURE (F). |
| [docs/CONTRIBUTING.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/CONTRIBUTING.md) | Tracked | Consolidate | Unique contributor workflow to DEVELOPMENT (F). |
| [docs/DATABASE_CONVENTIONS.md](../docs/DATABASE_CONVENTIONS.md) | Tracked | Retain | Authoritative database rules; prune historical narration. |
| [docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md) | Tracked | Retain | Canonical developer workflow and verification policy. |
| [docs/DOMAIN_MODEL.md](../docs/DOMAIN_MODEL.md) | Tracked | Retain | Conceptual vocabulary and domain boundaries. |
| [docs/ENTITY_LIFECYCLE.md](../docs/ENTITY_LIFECYCLE.md) | Tracked | Retain | Current creation/mutation/approval/history lifecycle contracts. |
| [docs/INFRASTRUCTURE.md](../docs/INFRASTRUCTURE.md) | Tracked | Retain | Canonical optional-AWS reference; absorb quick-start/checklist. |
| [docs/ISSUE_GRADING_RUBRIC.md](../docs/ISSUE_GRADING_RUBRIC.md) | Tracked | Retain | Current review policy; link rather than duplicate. |
| [docs/LOCAL_DEPLOYMENT.md](../docs/LOCAL_DEPLOYMENT.md) | Tracked | Retain | Deployment target/runbook; label planned versus delivered features. |
| [docs/PHASE10_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE10_VERIFICATION.md) | Tracked | Remove | Historical vertical-slice execution record. |
| [docs/PHASE11_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE11_VERIFICATION.md) | Tracked | Consolidate | Preserve live Foundry acceptance gate and security transition rationale (E). |
| [docs/PHASE13D_BACKEND_READINESS.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE13D_BACKEND_READINESS.md) | Tracked | Consolidate | Current read/pagination/browse API reference; remove obsolete gaps (B). |
| [docs/PHASE13D_CHARACTER_SHEET_BACKEND.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE13D_CHARACTER_SHEET_BACKEND.md) | Tracked | Consolidate | Current sheet API/build-resolution contract and limitations (B). |
| [docs/PHASE13E_ACCESS_CONTRACT.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE13E_ACCESS_CONTRACT.md) | Tracked | Consolidate | Current access API/authority reference; retain latest P03 amendments (B). |
| [docs/PHASE13E_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE13E_VERIFICATION.md) | Tracked | Remove | Closed access delivery; contract and manual scenarios survive elsewhere. |
| [docs/PHASE14_15_ACCEPTANCE_ENVIRONMENT.md](../docs/PHASE14_15_ACCEPTANCE_ENVIRONMENT.md) | Tracked | Retain | Run identity/setup; absorb historical account manifest. |
| [docs/PHASE14_15_ACCEPTANCE_LEDGER.md](../docs/PHASE14_15_ACCEPTANCE_LEDGER.md) | Tracked | Retain | Preserve evidence and owner decisions; add concise current summary. |
| [docs/PHASE14_15_ACCOUNT_MANIFEST.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_ACCOUNT_MANIFEST.md) | Tracked | Consolidate | Historical identity/preservation appendix in acceptance environment (C). |
| [docs/PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md) | Tracked | Consolidate | Preserve 43 finding IDs/package mapping in backlog and contracts (D). |
| [docs/PHASE14_15_APP_INTERACTION_REPAIR_PLAN_BATCH1_2026-11-01.md](BACKLOG.md) | Untracked | Consolidate | Preserve unique requirements/status before retiring untracked plan (D). |
| [docs/PHASE14_15_COMPANION_SCENARIOS.md](../docs/PHASE14_15_COMPANION_SCENARIOS.md) | Tracked | Retain | Negative/recovery/scoped-role/accessibility/clean-install specification. |
| [docs/PHASE14_15_COVERAGE_MATRIX.md](../docs/PHASE14_15_COVERAGE_MATRIX.md) | Tracked | Retain | Stable case/variant traceability; absorb missing old-matrix requirements. |
| [docs/PHASE14_15_DEF007_EFFECTIVE_TIME_MEMBERSHIP_PLAN_2026-11-01.md](BACKLOG.md) | Untracked | Consolidate | Preserve temporal policy and evidence obligations; untracked (D). |
| [docs/PHASE14_15_DEFECT_REGISTER.md](../docs/PHASE14_15_DEFECT_REGISTER.md) | Tracked | Retain | Current defect dispositions and evidence links. |
| [docs/PHASE14_15_HOWTO_FIRST_CAMPAIGN.md](../docs/PHASE14_15_HOWTO_FIRST_CAMPAIGN.md) | Tracked | Retain | Main acceptance journey; clearly distinguish from end-user guide. |
| [docs/PHASE14_15_INTEGRATION_AND_CONSOLIDATION_PLAN.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_INTEGRATION_AND_CONSOLIDATION_PLAN.md) | Tracked | Consolidate | Preserve DR decisions and open/deferred work in current backlog (D). |
| [docs/PHASE14_15_MANUAL_TESTING.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_MANUAL_TESTING.md) | Tracked | Consolidate | Reconcile all original cases and dated results into current acceptance set (C). |
| [docs/PHASE14_15_P02_NAVIGATION_CONTEXT_PLAN_2026-11-02.md](BACKLOG.md) | Untracked | Consolidate | Preserve approved navigation decisions and open checks; untracked (D). |
| [docs/PHASE14_15_P02_NAVIGATION_ROUTE_AND_GUARD_AUDIT.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_P02_NAVIGATION_ROUTE_AND_GUARD_AUDIT.md) | Tracked | Consolidate | Current navigation contracts to UI_DESIGN; retarget source citations (D). |
| [docs/PHASE14_15_P02_RECONCILIATION_2026-11-04.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_P02_RECONCILIATION_2026-11-04.md) | Tracked | Consolidate | Navigation decisions, open browser checks and current evidence disposition (D). |
| [docs/PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md](../docs/PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md) | Tracked | Consolidate | Extract current owner/lock contracts after active handoff stabilizes (G). |
| [docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md](../docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md) | Tracked | Retain | Active design/implementation; reconcile current status and trim history. |
| [docs/PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md) | Tracked | Consolidate | One current backlog; status and active-plan links (D). |
| [docs/PHASE14_15_STEP_G_REPAIR_REPORT.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_STEP_G_REPAIR_REPORT.md) | Tracked | Consolidate | Repair provenance to ledger; unresolved findings to defect register (C). |
| [docs/PHASE14_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_VERIFICATION.md) | Tracked | Consolidate | Retain milestone closure and reconcile manual limitations with P02 (E). |
| [docs/PHASE15_CP10_HANDOFF.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE15_CP10_HANDOFF.md) | Tracked | Remove | Historical completed handoff superseded by DEF-001/P02 work. |
| [docs/PHASE15_DEF001_BROWSER_RETEST.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE15_DEF001_BROWSER_RETEST.md) | Tracked | Consolidate | Keep run attribution and unexercised command variants in ledger (C). |
| [docs/PHASE15_DEF001_INVENTORY.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE15_DEF001_INVENTORY.md) | Tracked | Consolidate | Recovery contract plus RC-10 operation/variant coverage (C). |
| [docs/PHASE15_MANUAL_ACCEPTANCE.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE15_MANUAL_ACCEPTANCE.md) | Tracked | Consolidate | Preserve all page/accessibility requirements and sign-off fields (C). |
| [docs/PHASE15_VERIFICATION.md](../docs/PHASE15_VERIFICATION.md) | Tracked | Retain | Active phase evidence/gates; trim duplicates without changing results. |
| [docs/PHASE1_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE1_VERIFICATION.md) | Tracked | Consolidate | Carry unique AWS/resource concerns before retiring historical evidence (E). |
| [docs/PHASE2_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE2_VERIFICATION.md) | Tracked | Consolidate | Reconcile carried AWS concerns and historical scope limitations (E). |
| [docs/PHASE3_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE3_VERIFICATION.md) | Tracked | Consolidate | Reconcile carried AWS concerns; current temporal rules stay in ADR/schema (E). |
| [docs/PHASE4_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE4_VERIFICATION.md) | Tracked | Consolidate | Carry unresolved AWS concerns; retire superseded delivery gates (E). |
| [docs/PHASE5_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE5_VERIFICATION.md) | Tracked | Consolidate | Preserve proportional verification policy and live deferrals (E). |
| [docs/PHASE6_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE6_VERIFICATION.md) | Tracked | Remove | Closed event/interaction evidence; current schema contracts retained. |
| [docs/PHASE7_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE7_VERIFICATION.md) | Tracked | Remove | Closed quest/knowledge evidence. |
| [docs/PHASE8_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE8_VERIFICATION.md) | Tracked | Remove | Closed relationship/organization evidence. |
| [docs/PHASE9_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE9_VERIFICATION.md) | Tracked | Remove | Closed item/integration evidence; retarget source citations. |
| [docs/PLAN.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PLAN.md) | Tracked | Consolidate | Extract architecture, security, delivery gates and policy; retire last (A). |
| [docs/PLANv2.md](../docs/PLANv2.md) | Tracked | Retain | Single authoritative roadmap; optional later rename to ROADMAP. |
| [docs/PLATFORM_REVIEW_2026-09-25.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PLATFORM_REVIEW_2026-09-25.md) | Tracked | Consolidate | Disposition all 18 findings; backlog, deployment/roadmap, history (E). |
| [docs/POSTGRES18_UPGRADE_PLAN.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/POSTGRES18_UPGRADE_PLAN.md) | Tracked | Remove | Closed one-time upgrade/local-loop plan; current policy retained. |
| [docs/PROJECT_STATUS.md](../docs/PROJECT_STATUS.md) | Tracked | Retain | Single concise delivery-state/gate summary; substantial refresh needed. |
| [docs/QUICKSTART.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/QUICKSTART.md) | Tracked | Consolidate | Optional-AWS procedures to INFRASTRUCTURE (F). |
| [docs/R19_FOUNDATION_IMPLEMENTATION_PLAN.md](../docs/R19_FOUNDATION_IMPLEMENTATION_PLAN.md) | Tracked | Retain | Pending foundation implementation; accepted ADRs do not close it. |
| [docs/SCOPED_ROLE_IMPLEMENTATION_PLAN.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/SCOPED_ROLE_IMPLEMENTATION_PLAN.md) | Tracked | Consolidate | Current access/schema/operations references and approved defaults (B). |
| [docs/SCOPED_ROLE_INTEGRATION_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/SCOPED_ROLE_INTEGRATION_VERIFICATION.md) | Tracked | Consolidate | Upgrade/evidence limitations to ledger; concise historical record (E). |
| `docs/Testing Notes.txt` | Ignored | Local review | Ignored personal scratch; preserve unique observations, never publish values. |
| [docs/UI_DESIGN.md](../docs/UI_DESIGN.md) | Tracked | Retain | Behavior/navigation/access authority; consolidate current contracts here. |
| [docs/UI_STYLE_GUIDE.md](../docs/UI_STYLE_GUIDE.md) | Tracked | Retain | Presentation/components/accessibility standards; remove duplicate behavior. |
| [docs/adr/0001-use-postgresql.md](../docs/adr/0001-use-postgresql.md) | Tracked | Retain | Accepted decision; complete stub rationale before retiring PLAN. |
| [docs/adr/0002-use-class-table-inheritance.md](../docs/adr/0002-use-class-table-inheritance.md) | Tracked | Retain | Accepted decision; complete stub rationale before retiring PLAN. |
| [docs/adr/0003-separate-world-timeline-and-campaign.md](../docs/adr/0003-separate-world-timeline-and-campaign.md) | Tracked | Retain | Accepted decision; complete stub rationale before retiring PLAN. |
| [docs/adr/0004-use-event-assisted-state.md](../docs/adr/0004-use-event-assisted-state.md) | Tracked | Retain | Accepted decision; complete stub rationale before retiring PLAN. |
| [docs/adr/0005-separate-rules-definitions-from-world-instances.md](../docs/adr/0005-separate-rules-definitions-from-world-instances.md) | Tracked | Retain | Accepted decision; complete stub rationale before retiring PLAN. |
| [docs/adr/0006-ai-proposes-but-does-not-own-canon.md](../docs/adr/0006-ai-proposes-but-does-not-own-canon.md) | Tracked | Retain | Accepted decision; complete stub rationale before retiring PLAN. |
| [docs/adr/0007-separate-knowledge-from-truth.md](../docs/adr/0007-separate-knowledge-from-truth.md) | Tracked | Retain | Accepted decision; complete stub rationale before retiring PLAN. |
| [docs/adr/0008-aws-first-deployment-and-verification.md](../docs/adr/0008-aws-first-deployment-and-verification.md) | Tracked | Retain | Superseded decision history; keep identity and successor link. |
| [docs/adr/0009-separate-owning-role-from-login-roles.md](../docs/adr/0009-separate-owning-role-from-login-roles.md) | Tracked | Retain | Architectural decision/rationale; retain amendments and current status. |
| [docs/adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md](../docs/adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md) | Tracked | Retain | Architectural decision/rationale; retain amendments and current status. |
| [docs/adr/0011-local-first-development-aws-verified-delivery.md](../docs/adr/0011-local-first-development-aws-verified-delivery.md) | Tracked | Retain | Superseded decision history; keep identity and successor link. |
| [docs/adr/0012-self-hosted-docker-deployment-and-ci-verification.md](../docs/adr/0012-self-hosted-docker-deployment-and-ci-verification.md) | Tracked | Retain | Architectural decision/rationale; retain amendments and current status. |
| [docs/adr/0013-locally-host-production-on-existing-mini-pc.md](../docs/adr/0013-locally-host-production-on-existing-mini-pc.md) | Tracked | Retain | Architectural decision/rationale; retain amendments and current status. |
| [docs/adr/0014-world-authoring-authority.md](../docs/adr/0014-world-authoring-authority.md) | Tracked | Retain | Architectural decision/rationale; retain amendments and current status. |
| [docs/adr/0015-typed-world-content-authoring.md](../docs/adr/0015-typed-world-content-authoring.md) | Tracked | Retain | Architectural decision/rationale; retain amendments and current status. |
| [docs/adr/0016-data-classification-and-private-data-handling.md](../docs/adr/0016-data-classification-and-private-data-handling.md) | Tracked | Retain | Architectural decision/rationale; retain amendments and current status. |
| [docs/adr/0017-world-relationship-lifecycle-and-projection.md](../docs/adr/0017-world-relationship-lifecycle-and-projection.md) | Tracked | Retain | Architectural decision/rationale; retain amendments and current status. |
| [docs/adr/0018-world-creation-eligibility.md](../docs/adr/0018-world-creation-eligibility.md) | Tracked | Retain | Superseded decision history; keep identity and successor link. |
| [docs/adr/0019-world-visibility-and-viewer-role.md](../docs/adr/0019-world-visibility-and-viewer-role.md) | Tracked | Retain | Architectural decision/rationale; retain amendments and current status. |
| [docs/adr/0020-scoped-system-world-and-campaign-roles.md](../docs/adr/0020-scoped-system-world-and-campaign-roles.md) | Tracked | Retain | Current scoped-role decision; correct ADR 0021 acceptance cross-reference. |
| [docs/adr/0021-shared-actor-identity-control-and-authoring-responsibility.md](../docs/adr/0021-shared-actor-identity-control-and-authoring-responsibility.md) | Tracked | Retain | Accepted architecture for pending work; preserve approved policy precisely. |
| [docs/adr/0022-creature-templates-combatants-and-promotion.md](../docs/adr/0022-creature-templates-combatants-and-promotion.md) | Tracked | Retain | Accepted architecture for pending work; preserve approved policy precisely. |
| [docs/adr/0023-rules-engine-calculation-validation-and-source-authorization.md](../docs/adr/0023-rules-engine-calculation-validation-and-source-authorization.md) | Tracked | Retain | Accepted architecture for pending work; preserve approved policy precisely. |
| [docs/adr/_template.md](../docs/adr/_template.md) | Tracked | Retain | Small reusable decision-record template. |
| [docs/architecture/DATABASE_MODEL.md](../docs/architecture/DATABASE_MODEL.md) | Tracked | Retain | Schema authority; distinguish built/planned, remove correction diaries. |
| [docs/architecture/DUNGEON_FLOW.md](../docs/architecture/DUNGEON_FLOW.md) | Tracked | Retain | Reusable cross-domain acceptance/reference scenario. |
| [docs/architecture/SYSTEM_ARCHITECTURE.md](../docs/architecture/SYSTEM_ARCHITECTURE.md) | Tracked | Retain | Layering, transactions and system boundaries. |
| [docs/operations/DATABASE_RECOVERY.md](../docs/operations/DATABASE_RECOVERY.md) | Tracked | Retain | Active backup/restore/verification runbook. |
| [docs/operations/PLATFORM_ADMINISTRATOR_RECOVERY.md](../docs/operations/PLATFORM_ADMINISTRATOR_RECOVERY.md) | Tracked | Retain | Active administrator and related scoped-role recovery procedures. |
| [foundry-module/README.md](../foundry-module/README.md) | Tracked | Retain | Install/pairing/trust and live-acceptance procedure. |
| [portal/README.md](../portal/README.md) | Tracked | Retain | Keep component setup; extract duplicate contracts and historical narratives. |
| [terraform/README.md](../terraform/README.md) | Tracked | Retain | Keep short pointer; move detailed operations into optional-AWS reference. |


## Implementation receipt ? 2026-11-08

Implemented on branch `docs/consolidate-2026-11-08`, based on `53416d5`, in the
separate worktree `C:/Users/nemes/dnd_ai_docs_review`. The shared
`C:/Users/nemes/dnd_ai` checkout remains available to Claude Code for the concurrent
P3/A3 handoff. Its files and staging area were not changed by this implementation.

### Completed

- Retired **32 tracked document paths**, including all eight direct-removal candidates.
  Git identifies 30 deletions and two moves into the maintained API references.
  Preserved substantive current requirements and acceptance obligations before
  retiring the other documents. DELIVERY_HISTORY maps retired sources to current
  destinations and immutable originals at the reviewed Git revision.
- Added six maintained references: the documentation index, backlog, delivery
  history, read API, character-sheet API, and access-control contract. With this
  review report, the resulting tracked Markdown inventory is **72 files**, down
  from 97 before the cleanup.
- Consolidated onboarding, optional AWS operations, contributor/verification
  guidance, access contracts, platform-review dispositions, and acceptance
  scenarios. Refreshed status and roadmap wording to distinguish implemented
  checkpoints, unresolved acceptance, and work in progress.
- Preserved the existing acceptance-ledger rows and outcomes, all 58 coverage
  case IDs, all 43 investigation finding IDs, the P02 B1?B22 checks, the clean
  deployment sequence, and the RC-10 operation/variant obligations. Historical
  results retain their dates, revisions, and limitations.
- Repaired documentation links and source citations. Changes in 34 source/test/
  script files are comments or docstrings only; application behavior is unchanged.
- Consolidated the unique requirements from three untracked plans. Their exact
  originals remain in the shared checkout and are also backed up outside the
  repository at `C:/Users/nemes/dnd_ai_documentation_sources_20261108`.
  DELIVERY_HISTORY records their SHA-256 hashes. The ignored personal scratch
  file was not changed or added to Git.

### Deferred to protect the concurrent handoff

Five legacy paths remain as compatibility indexes: PLAN, the old access contract,
the scoped-role plan, the interaction investigation, and the remaining-work
handoff. They route readers to maintained references and pinned original text.
Their removal can follow migration of the remaining callers.

The P03-A implementation plan and A1 ownership design are byte-for-byte unchanged
from this worktree's baseline. Extracting and retiring the A1 design remains
conditional on the active handoff stabilizing, as the original review required.
R19 and the current acceptance/evidence documents remain available.

This cleanup commit is kept on its separate branch. Integration must reconcile
Claude's concurrent edits to DOMAIN_MODEL, ENTITY_LIFECYCLE, DATABASE_MODEL, and
the old access contract; new contract amendments belong in `docs/api/ACCESS_CONTROL.md`
after that reconciliation. No merge or push is part of this cleanup. The three
untracked source plans can be removed from the shared checkout after integration
and verification that no additional edits need preserving.

### Validation

- All local Markdown file and fragment links resolve in the resulting worktree.
- Python executable ASTs match the baseline for all 30 edited Python files;
  the four other source/script diffs contain only comment changes.
- Ruff lint and formatting checks pass for all 30 edited Python files.
- The original acceptance-ledger rows match except for repaired link targets;
  coverage/finding IDs and the active handoff files pass preservation checks.
- SHA-256 checks confirm the three local source backups match the reviewed originals.
- `git diff --check` passes.

No application/database/browser test suite, deployment, or live CI run was
performed for this documentation-only change. Historical verification records
were not reclassified as current passes.
