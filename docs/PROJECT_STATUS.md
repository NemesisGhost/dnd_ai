# Project status

Last reviewed: **2026-09-26** at commit on branch `phase14/product-direction-and-world-ownership` (product-direction documentation and world-ownership-scope foundation; see [PRODUCT_DIRECTION.md](PRODUCT_DIRECTION.md) and [ADR 0014](adr/0014-world-ownership-scope.md)).

This is the concise current-state companion to [PLAN.md](PLAN.md), which remains
the delivery-status source of truth. Phase verification files are historical
evidence; they are not a claim that the present working tree has been fully
reverified. This update corrects stale migration-count and 13E status claims
below against evidence collected on the current branch; it does not rerun the
full 2026-09-14 platform review.

## Current delivery state

| Area | Current state | Next closure gate |
|---|---|---|
| Database and domain model (Phases 0-9) | Complete through migration `107_world_ownership_scope` (head; ADR 0014) — 108 revision files as of this review, since the chain includes one interstitial non-numeric revision id | Continue regression verification with every schema change |
| Core FastAPI/API slice (Phase 10) | Complete | Preserve authentication, authorization, audit, idempotency, and non-disclosure boundaries |
| Foundry MVP (Phase 11) | Pairing, per-device credentials, scoped access, synchronization, module, and automated coverage are implemented | Run and record the documented live Foundry v13 acceptance exercise |
| AI/NPC MVP (Phase 12) | Schema, reference corpus, provider abstraction, NPC turn/proposals, and audience-aware synthesis are implemented | Run a real-provider smoke test and create `PHASE12_VERIFICATION.md` |
| Web portal (Phase 13) | **13A-13D complete** (13D closed complete with explicit limitations: reviewed commit `5bd6fd5efac64b07e5d452687ffaa010b2583a6b`, CI run `35148055021`, 603 portal tests, 147 focused backend tests; its accepted limitations carry forward rather than being re-litigated). **13E (GM access tools) is in progress**: 13E-A delivered a live, read-only campaign access overview (`GET /campaigns/{campaign_id}/access-overview`, capability `access.manage`). **13E-B delivered a read-only audit-history API and portal foundation** (`dnd_ai.queries.audit_history`/`dnd_ai.api.audit_history`, campaign-scoped, curated command-name allowlist — see that module's own docstring for its documented scope limits). No 13E mutation workflow (account/role/relationship/grant changes, invitations, preview-as-user) exists yet — see PLAN.md §13 | Remaining 13E mutation increments, 13F Foundry device UI, 13G AI surfaces, and 13H E2E/production packaging |
| Local production deployment (Phase 14) | PostgreSQL, one-off migrations, and a single-worker API are available in Compose | Package the portal and worker, add reverse proxy/TLS, secrets/monitoring, backup/restore, and rollback evidence |
| World ownership foundation (ahead of Phase 15) | **Delivered**: `security.ownership_scopes`/`.ownership_scope_roles`/`.ownership_scope_memberships`, `core.worlds.ownership_scope_id`, and the minimal `dnd_ai.commands.ownership` command layer (ADR 0014). **Not delivered**: `create_world` and the rest of the missing authoring-command surface (PLAN.md §15), any API/UI surface for ownership | Schedule the full authoring-command surface PLAN.md §15 now lists explicitly |
| Controlled import (Phase 15) | Not started; blocked on the authoring-command prerequisite above | Complete the staged review and command-backed promotion workflow, after the authoring commands exist |

The project is a capable pre-release platform, not a production-complete
application. The backend/domain surface is considerably further along than the
browser and operational packaging surfaces.

## Repository inventory

- Python 3.12+ FastAPI application with command, query, domain, API, and persistence layers.
- PostgreSQL 18 schema managed by Alembic, with 108 revision files and structured seed data.
- React 19/TypeScript/Vite portal with 65 test files and 369 tests in the observed local run (not rerun in this update — no portal files changed).
- Foundry VTT v13 adapter implemented as dependency-free native ES modules.
- Docker/Compose self-hosted database, migration, and API topology; optional Terraform for AWS RDS development.
- 2,625 statically discoverable Python test functions (`grep -rc '^def test_\|^    def test_' tests/`, re-counted for this review; up from 2,416 on 2026-09-14) — parameterization makes executed totals larger (4,345 collected via `pytest --collect-only`).

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
