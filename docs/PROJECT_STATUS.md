# Project status

Last reviewed: **2026-10-05** at commit `60d5bc9` (documentation reconciliation only; the verification table and findings below are from the 2026-09-14 review at `518c079` and were not re-run).

This is the concise current-state companion to [PLANv2.md](PLANv2.md), the
authoritative product roadmap (the authoring-first revision; it supersedes the
future-delivery portion of [PLAN.md](PLAN.md), which remains the detailed
architectural and historical record). Phase verification files are historical
evidence; they are not a claim that the present working tree has been fully
reverified.

**Phase 15 is incomplete.** Phase 15.1 (world-content definitions) is merged,
but a GM cannot yet author or operate player characters, parties, sessions,
world time, events and corrections, quest and knowledge runtime state,
dungeons, routes, relationships, items and inventory, or encounters, nor review
provenance and revisions, through supported interfaces. The remaining work is
the checkpoint sequence in [PLAN.md Phase 15](PLAN.md). **Phase 16 (player
authoring and collaboration) is blocked by the Phase 15 completion gate.**

## Current delivery state

| Area | Current state | Next closure gate |
|---|---|---|
| Database and domain model (Phases 0-9) | Complete through migration `103_login_failure_audit_action`, plus the 2026-08 schema-comment reconciliation revision | Continue regression verification with every schema change |
| Core FastAPI/API slice (Phase 10) | Complete | Preserve authentication, authorization, audit, idempotency, and non-disclosure boundaries |
| Foundry MVP (Phase 11) | Pairing, per-device credentials, scoped access, synchronization, module, and automated coverage are implemented | Run and record the documented live Foundry v13 acceptance exercise |
| AI/NPC MVP (Phase 12) | Schema, reference corpus, provider abstraction, NPC turn/proposals, and audience-aware synthesis are implemented | Run a real-provider smoke test and create `PHASE12_VERIFICATION.md` |
| Web portal (Phase 13) | **Clean-install relationship-capability defaults (previously a known limitation) are production reference data since Phase 15 checkpoint 15.2A-1 (migration `114_relationship_defaults`).** **13A-13D complete** (13D closed complete with explicit limitations: reviewed commit `5bd6fd5efac64b07e5d452687ffaa010b2583a6b`, CI run `35148055021`, 603 portal tests, 147 focused backend tests; its accepted limitations carry forward rather than being re-litigated). **Phase 13 is closed as the portal/read/access foundation under the authoring-first roadmap (13F/13G/13H moved to Phases 21/20/17)**; its 13E increment delivered GM access tools. The earlier description follows: 13E (GM access tools) was in progress: increment 13E-A delivered a live, read-only campaign access overview (`GET /campaigns/{campaign_id}/access-overview`, capability `access.manage`) replacing the Access screen's placeholder — current members, roles, character relationships, and explicit membership-targeted resource grants, all read-only. No 13E mutation workflow (account/role/relationship/grant changes, invitations, preview-as-user) exists yet — see PLAN.md §13 | Remaining 13E mutation increments, 13F Foundry device UI, 13G AI surfaces, and 13H E2E/production packaging |
| Authoring kernel and campaign setup (Phase 14) | **Complete with accepted limitations** (PR #64, merge `3046714`, CI run `37227612984` green; see [PHASE14_VERIFICATION.md](PHASE14_VERIFICATION.md)). Per-world authority, world/timeline/campaign commands, branches, campaign and canon lifecycle, and the portal workflow exist. Limitations: the sidebar/hierarchy correction's manual browser verification is still pending; source attachment, provenance presentation, and prior-version history are not provided (Phase 15 checkpoints 15.2R, 15.3C-1, 15.3C-2) | Manual navigation check (carried into the Phase 15 acceptance matrix) |
| GM world-content authoring (Phase 15.1) | **Implemented and merged** (PR #65, merge `60d5bc9`; [ADR 0015](adr/0015-typed-world-content-authoring.md), [PHASE15_VERIFICATION.md](PHASE15_VERIFICATION.md)) as a **subset** of Phase 15: typed definition authoring for locations, organizations/religions, NPC identity, quest definitions, and knowledge items. Manual browser/accessibility verification not performed. **Known limitation:** rows written before checkpoint 15.2A-3 still hold narrative values (up to 1,000 characters per field) in audit metadata and full authoring views in idempotency replay rows; new writes store only redacted audit values and receipts (existing rows: owner-gated checkpoint 15.2A-4) | Phase 15 completion checkpoints; see [PLAN.md Phase 15](PLAN.md) |
| GM authoring completion (Phase 15, remaining) | **Not started.** Checkpoints 15.2-0 through 15.4 (see [PLAN.md Phase 15](PLAN.md)); 15.2-0 is this documentation reconciliation | 15.2A-1 relationship-capability defaults, then the merge order in PLAN.md |
| Player authoring and collaboration (Phase 16) | **Blocked** by the Phase 15 completion gate (full exit scenario and acceptance evidence) | Phase 15 closure |
| Local production deployment (now Phase 17) | PostgreSQL, one-off migrations, and a single-worker API are available in Compose | Package the portal and worker, add reverse proxy/TLS, secrets/monitoring, backup/restore, and rollback evidence (after Phases 14-16) |
| Controlled import (now Phase 18) | Not started | Begins only after the matching manual-authoring commands exist |

The project is a capable pre-release platform, not a production-complete
application. The backend/domain surface is considerably further along than the
browser and operational packaging surfaces.

## Repository inventory

- Python 3.12+ FastAPI application with command, query, domain, API, and persistence layers.
- PostgreSQL 18 schema managed by Alembic, with 104 revision files and structured seed data.
- React 19/TypeScript/Vite portal with 65 test files and 369 tests in the observed local run.
- Foundry VTT v13 adapter implemented as dependency-free native ES modules.
- Docker/Compose self-hosted database, migration, and API topology; optional Terraform for AWS RDS development.
- 2,416 statically discoverable Python test functions; parameterization makes executed totals larger.

## Verification observed in this review

| Check | Result |
|---|---|
| `ruff check src tests scripts` | Passed |
| `mypy src` | Passed as the CI-scoped check; extending it to `scripts` exposed four errors in `scripts/wait_for_ci.py` |
| Portal `npm test` | Passed: 65 files, 369 tests |
| Portal `npm run lint` | Passed |
| Portal `npm run build` | Passed: TypeScript project build and Vite production bundle |
| Foundry packaging | Passed; produced a `0.2.0` archive |
| Foundry `npm test` / CI command | Failed before discovery because `node --test test/` treats the directory as a module path on the reviewed Node 24 runtime |
| Python unit/scenario run | Reached 519 passes before the first failure; the failure was observed in a Windows shell-test fixture interaction in `test_verify_sh.py`, so this was not a clean full-suite result |
| Database/migration/Compose integration | Not run: Docker Desktop was unavailable in the review environment |

No claim of a green current full suite or deployable production stack should be
made from this review. Historical green runs remain recorded in the applicable
phase verification documents.

## Review findings (graded)

Scores use the supplied rubric and show production exposure, impact magnitude,
triggerability, detection/recovery, and blast radius (`E/I/T/D/B`).

### 1. Foundry verification command cannot discover the suite — 4/10, Medium

- **Affected component:** `foundry-module/package.json`, script `test`, and `.github/workflows/ci.yml`, step “Run the test suite (node --test)”.
- **Scenario/preconditions:** a contributor or CI runner executes the declared check. The runner attempts to load `test/` as a module and exits before executing the 76 test declarations.
- **Impact and symptoms:** the Foundry CI job and documented local command fail; releases cannot obtain required automated evidence. Runtime users and canonical data are not directly affected.
- **Evidence:** `npm test` failed with `MODULE_NOT_FOUND` for `foundry-module/test`; packaging succeeded separately.
- **Score:** E1 (release/CI path), I1 (verification unavailable), T1 (routine supported command), D0 (immediate clear failure), B1 (whole Foundry validation job) = **4**.
- **Correction/tests:** use Node discovery (`node --test`) or an explicit cross-platform file pattern, make package and workflow invoke one canonical script, then prove all declarations execute on Node 20 and the documented developer version.
- **Mitigation/residual risk:** the tests exist and the package builder succeeds, but neither substitutes for executing the suite.

### 2. CI does not type-check operational Python scripts — 3/10, Low

- **Affected component:** `.github/workflows/ci.yml` type-check step and `scripts/wait_for_ci.py` (`fetch_json` and workflow-run response helpers).
- **Scenario/preconditions:** an operator uses the helper on an unusual or changing GitHub API response. Unchecked `Any` values and incomplete generic types allow shape mistakes through the merge gate.
- **Impact and symptoms:** CI observation may fail or misreport a run; application requests and stored game data are unaffected.
- **Evidence:** CI runs `mypy src` only. `mypy src scripts` reports four strict errors in `scripts/wait_for_ci.py`; no focused test covers the script.
- **Score:** E1 (operator path), I1 (operational degradation), T0 (requires an atypical response or script defect), D1 (misreporting can require diagnosis), B0 (one invocation) = **3**.
- **Correction/tests:** add typed response validation and malformed/partial-response tests, then include `scripts` in CI's mypy scope.
- **Mitigation/residual risk:** GitHub remains the authoritative status and can be inspected directly.

### 3. Foundry package metadata versions disagree — 2/10, Low

- **Affected component:** `foundry-module/package.json` (`0.1.0`) versus `foundry-module/module.json` and the generated archive (`0.2.0`).
- **Scenario/preconditions:** release automation reads the npm manifest while Foundry reads `module.json`.
- **Impact and symptoms:** release labels, artifact selection, or diagnostics can report inconsistent versions; the installed module continues to run.
- **Evidence:** direct manifest inspection and packager output naming `foundry-dnd-ai-0.2.0.zip`; no consistency test is present.
- **Score:** E1 (release path), I1 (minor release confusion), T0 (requires a metadata consumer), D0 (visible), B0 (one artifact) = **2**.
- **Correction/tests:** define one version source or assert that all manifests agree during packaging.
- **Mitigation/residual risk:** the Foundry-facing manifest and archive agree.

## Review conclusion

No Critical or High issue was demonstrated in the reviewed production paths.
The single Medium issue is a release-verification blocker, not an application
runtime defect. Production readiness is still intentionally blocked by the
unfinished Phase 13/14 packaging, ingress, backup/restore, monitoring, and
acceptance work listed above.
