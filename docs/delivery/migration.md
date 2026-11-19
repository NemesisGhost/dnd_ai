# Documentation migration · 18 November 2026

## Baseline

Working checkout `phase15/completion` at `881786c8f23ff3e2ac4e8c5b8433a54f032afadd`, including PR #69. The initial tracked tree was clean. The three untracked owner records listed below are local evidence. The reviewed Git baseline preserves the exact text of every tracked input, including prior execution dates, commands and results. Retrieve it with `git show 881786c:<original-path>`.

Tools available here were Git 2.53, ripgrep, uv 0.11.32, the project Python 3.13.12 environment, Node 24.13.1, npm 11.8.0 and Docker Compose 5.3.1. This pass uses read-only configuration, route and metadata inspection.

## Source and destination map

The destinations were selected before migration. Frequently cited technical contracts keep stable addresses. The four reader categories in the [hub](../README.md) also cover these established paths. The delivery directory owns order, work and evidence.

| Original path at baseline | Maintained destination or disposition |
|---|---|
| `.claude/skills/verify-local/SKILL.md` | [Contract or component guidance retained](../../.claude/skills/verify-local/SKILL.md) |
| `.claude/skills/wait-for-ci/SKILL.md` | [Contract or component guidance retained](../../.claude/skills/wait-for-ci/SKILL.md) |
| `.github/copilot-instructions.md` | [Contract or component guidance retained](../../.github/copilot-instructions.md) |
| `CLAUDE.md` | [Contract or component guidance retained](../../CLAUDE.md) |
| `README.md` | [Rewritten introduction, with product boundaries in the roadmap](../../README.md) |
| `database/seeds/README.md` | [Contract or component guidance retained](../../database/seeds/README.md) |
| `docs/AUDIT_HISTORY_API.md` | [Moved by subject](../reference/audit-history.md) |
| `docs/BACKLOG.md` | [Moved by subject](work-register.md) |
| `docs/DATABASE_CONVENTIONS.md` | [Contract or component guidance retained](../DATABASE_CONVENTIONS.md) |
| `docs/DELIVERY_HISTORY.md` | [Moved by subject](history.md) |
| `docs/DEVELOPMENT.md` | [Contract or component guidance retained](../DEVELOPMENT.md) |
| `docs/DOMAIN_MODEL.md` | [Contract or component guidance retained](../DOMAIN_MODEL.md) |
| `docs/ENTITY_LIFECYCLE.md` | [Contract or component guidance retained](../ENTITY_LIFECYCLE.md) |
| `docs/INFRASTRUCTURE.md` | [Moved by subject](../operations/optional-aws.md) |
| `docs/ISSUE_GRADING_RUBRIC.md` | [Moved by subject](grading.md) |
| `docs/LOCAL_DEPLOYMENT.md` | [Moved by subject](../operations/deployment.md) |
| `docs/PHASE13E_ACCESS_CONTRACT.md` | [Consolidated](../api/ACCESS_CONTROL.md) |
| `docs/PHASE14_15_ACCEPTANCE_ENVIRONMENT.md` | [Moved by subject](acceptance-environment.md) |
| `docs/PHASE14_15_ACCEPTANCE_LEDGER.md` | [Moved by subject](acceptance-ledger.md) |
| `docs/PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md` | [Consolidated](work-register.md) |
| `docs/PHASE14_15_COMPANION_SCENARIOS.md` | [Moved by subject](companion-scenarios.md) |
| `docs/PHASE14_15_COVERAGE_MATRIX.md` | [Moved by subject](coverage.md) |
| `docs/PHASE14_15_DEFECT_REGISTER.md` | [Moved by subject](defects.md) |
| `docs/PHASE14_15_HOWTO_FIRST_CAMPAIGN.md` | [Moved by subject](first-campaign-acceptance.md) |
| `docs/PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md` | [Moved by subject](ownership-design.md) |
| `docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md` | [Moved by subject](shared-characters.md) |
| `docs/PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md` | [Consolidated](work-register.md) |
| `docs/PHASE15_CONTEXT_NAVIGATION_CORRECTION_PLAN_2026-11-11.md` | [Moved by subject](context-navigation.md) |
| `docs/PHASE15_P03A_A5_PLAYER_PROFILE_DESIGN_2026-11-11.md` | [Moved by subject](player-profile-design.md) |
| `docs/PHASE15_VERIFICATION.md` | [Moved by subject](phase-15-verification.md) |
| `docs/PLAN.md` | [Historical section locator for immutable migration and test citations](../PLAN.md) |
| `docs/PLANv2.md` | [Moved by subject](roadmap.md) |
| `docs/PROJECT_STATUS.md` | [Consolidated](work-register.md) |
| `docs/R19_FOUNDATION_IMPLEMENTATION_PLAN.md` | [Moved by subject](rules-foundations.md) |
| `docs/README.md` | [Rebuilt navigation and separate documentation standard](../README.md) |
| `docs/SCOPED_ROLE_IMPLEMENTATION_PLAN.md` | [Consolidated](../api/ACCESS_CONTROL.md) |
| `docs/UI_DESIGN.md` | [Moved by subject](../reference/portal-behavior.md) |
| `docs/UI_STYLE_GUIDE.md` | [Moved by subject](../reference/portal-style.md) |
| `docs/api/ACCESS_CONTROL.md` | [Contract or component guidance retained](../api/ACCESS_CONTROL.md) |
| `docs/api/CHARACTER_SHEET.md` | [Contract or component guidance retained](../api/CHARACTER_SHEET.md) |
| `docs/api/READ_API.md` | [Contract or component guidance retained](../api/READ_API.md) |
| `docs/architecture/DATABASE_MODEL.md` | [Contract or component guidance retained](../architecture/DATABASE_MODEL.md) |
| `docs/architecture/DUNGEON_FLOW.md` | [Contract or component guidance retained](../architecture/DUNGEON_FLOW.md) |
| `docs/architecture/SYSTEM_ARCHITECTURE.md` | [Contract or component guidance retained](../architecture/SYSTEM_ARCHITECTURE.md) |
| `docs/operations/DATABASE_RECOVERY.md` | [Contract or component guidance retained](../operations/DATABASE_RECOVERY.md) |
| `docs/operations/PLATFORM_ADMINISTRATOR_RECOVERY.md` | [Contract or component guidance retained](../operations/PLATFORM_ADMINISTRATOR_RECOVERY.md) |
| `foundry-module/README.md` | [Contract or component guidance retained](../../foundry-module/README.md) |
| `portal/README.md` | [Contract or component guidance retained](../../portal/README.md) |
| `terraform/README.md` | [Contract or component guidance retained](../../terraform/README.md) |
| `docs/adr/0001…0023` and `_template.md` | [All decisions and template retained under original IDs](../adr/) |
| `docs/R01_FRESH_AUTHORIZATION_PLAN_2026-11-12.md`, `docs/R01_S6_READINESS_ASSESSMENT_2026-11-18.md`, and `docs/R01_E4_REFERENCE_CORPUS_DESIGN_2026-11-18.md` | Local source notes reconciled into the [R01 work-register entry](work-register.md#r01--runtime-authorization-and-transaction-defects) and the [ACCESS_CONTROL final-check contract](../api/ACCESS_CONTROL.md#authorization-timing-and-the-final-check-r01-s6), then removed. Detailed iteration history and local probe logs were not promoted to maintained documentation. |
| Ignored `docs/Testing Notes.txt` | Private local scratch, preserved in place. Editorial feedback on time entry, layout, navigation and publication belongs with the interaction findings. Account material and environment identifiers stay local. |
| `.env.example`, Compose comments, scripts, Terraform examples and CI | Operational inputs remain beside their consumers. The deployment and development guides explain how to use them. |

Older retirements and preserved local-plan hashes are in [delivery history](history.md). The [work register](work-register.md#documentation-drift-at-the-audited-head) records current dispositions for Fable C1–C4 and D1–D11.

## Section-level consolidations

- The old project status table and roadmap status paragraph now lead to the [single maintained work register and ID crosswalk](work-register.md#maintained-work-register). The [R01 entry](work-register.md#r01--runtime-authorization-and-transaction-defects) owns backend acceptance, excluded routes and residuals.
- The November backlog's 43-row interaction crosswalk, test commands and Fable's original acceptance criteria moved to the [dated review](review-2026-11-11.md). The [audited dispositions](work-register.md#documentation-drift-at-the-audited-head) own present status.
- UI design §4.8 now lives in the [navigation contract](../reference/portal-navigation.md). The remaining portal behavior and style rules keep separate owners. The Phase 13 read-readiness matrix was replaced by the [read guide](../api/READ_API.md) and the complete [method/path catalog](../api/operations.md).
- The former database model's logical table lists remain design material. The [declared inventory](../reference/tables.md) resolves built versus absent names. The earlier deployment diagram remains the production target, alongside the [current service list](../operations/deployment.md#runnable-services).
- The three local R01 source notes were removed after their needed current contract and disposition information was reconciled into tracked documentation (see the row above). Their detailed iteration history and local probe logs were not promoted; two unavailable reports cited by the authorization plan remain identified by filename as historical references. No substitute report or test result was created.
- Historical database comments, migration literals and fixture messages that contain original citations are preserved. Look up their old filename here or use the original Git revision. Operational pointers in scripts, configuration, clients and contributor guidance use the current subjects.

## Validation at the migration baseline

All 73 original tracked Markdown files are accounted for, including 23 ADRs and their template. The route registry matched OpenAPI method for method (348 operations, 333 paths). Rebuilding the write manifest in memory matched the checked-in manifest. Package metadata declared 228 tables and Alembic reported one revision head, `149_reservation_fk_deferrable`. Local Markdown links and heading fragments were checked across the working tree, including the owner records. The original 43 interaction findings, R01–R18 and all 15 Fable IDs were checked. Dated evidence retained its fenced commands, execution identifiers and acceptance case IDs.

The documentation checker passed, as did its Ruff checks and whitespace checks on the full proposed diff including new files. Changes to existing Python files were checked for identical executable syntax after excluding documentation strings. No database, container, deployment, full test suite, live Foundry instance, real model, browser or external CI run was exercised. Approval and verification counts in earlier records belong to the recorded heads.
