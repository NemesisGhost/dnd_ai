# Delivery history and retired-source map

This is an index of recorded evidence, not a claim that old tests pass on the present tree.
Full tracked originals are pinned to commit `53416d5`; that commit remains an ancestor of
the documentation consolidation. Use `git show 53416d5:docs/<filename>` offline. Old
phase/source citations in code are historical provenance unless they link a maintained
contract explicitly. Current roadmap, policy and contracts start at [the index](README.md).

## Milestones and limitations

| Milestone | Recorded result | Limits carried forward |
|---|---|---|
| PostgreSQL 18/local loop | Upgrade plan closed 2026-08-08; RDS replaced, not upgraded in place | Not a reusable data-preserving production upgrade recipe |
| Phases 1–4 | Historical foundation/rules delivery | AWS resource/role concerns need reconciliation only if operating that target; no live AWS inspection here |
| Phase 5 | Closed; run 30977657034, head 267ac1d | Proportional harness policy in DEVELOPMENT; schema deferrals reconciled through current roadmap |
| Phase 6 | Closed; merged 2692f41, run 31140171269 passed after diagnosed RDS retry | Historical AWS environment, not current CI |
| Phase 7 | Initial phase merged; correction evidence in original verification | Do not reuse stale PR-state prose as current work |
| Phase 8 | Closed; run 31217977401 at 70fffbe | Historical AWS environment |
| Phase 9 | Closed; final recorded run 31349958030 at 15096dd passed | Earlier failed cleanup and intermediate “still required” statements remain in original history |
| Phase 10 | Vertical-slice/API verification recorded | Original record distinguishes local fix verification from CI at e293163; no new final-head proof inferred |
| Phase 11 | Adapter/pairing code and automated delivery recorded | Live Foundry v13 exercise remains due |
| Phase 13D/13E | Read/access delivery; 13E closure at 30fcec5, PR #62 | Endpoint contracts moved to api/; deferred manual preview checks retained in companion scenarios |
| Phase 14 | PR #64 merged 3046714; CI 37227612984 recorded green | Original manual navigation limits retained, later P02 evidence separate |
| Scoped roles / CP-4 | Integration evidence and PR #67 run 40151267535, third attempt green | Attempts/failures are not erased; snapshot rehearsal had no Viewer or deny-grant source rows |
| CP-10 / DEF-001 | CP-10 complete; later operation inventory and browser retest recorded | RC-10 command variants, AT/layout gaps and run identities retained in coverage/ledger |
| P02 | Owner approval 2026-11-06 at 81bf164 | Browser follow-ups and broader Phase 14/15 acceptance remain separate |

## Retired sources and maintained destinations

Rows describe documentation ownership, not a fresh implementation or acceptance judgment.
Legacy code citations may use the old filename; this table resolves them to exact originals.

| Source at reviewed baseline | Current home | Treatment |
|---|---|---|
| [AI_ASSISTANT_GUIDE.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/AI_ASSISTANT_GUIDE.md) | [README.md](README.md) | Retired; immutable original retained in Git |
| [CHECKLIST.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/CHECKLIST.md) | [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | Retired; immutable original retained in Git |
| [CONTRIBUTING.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/CONTRIBUTING.md) | [DEVELOPMENT.md](DEVELOPMENT.md) | Retired; immutable original retained in Git |
| [PHASE10_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE10_VERIFICATION.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PHASE11_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE11_VERIFICATION.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PHASE13D_BACKEND_READINESS.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE13D_BACKEND_READINESS.md) | [READ_API.md](api/READ_API.md) | Retired; immutable original retained in Git |
| [PHASE13D_CHARACTER_SHEET_BACKEND.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE13D_CHARACTER_SHEET_BACKEND.md) | [CHARACTER_SHEET.md](api/CHARACTER_SHEET.md) | Retired; immutable original retained in Git |
| [PHASE13E_ACCESS_CONTRACT.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE13E_ACCESS_CONTRACT.md) | [ACCESS_CONTROL.md](api/ACCESS_CONTROL.md) | Short compatibility pointer |
| [PHASE13E_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE13E_VERIFICATION.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PHASE14_15_ACCOUNT_MANIFEST.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_ACCOUNT_MANIFEST.md) | [PHASE14_15_ACCEPTANCE_ENVIRONMENT.md](PHASE14_15_ACCEPTANCE_ENVIRONMENT.md) | Retired; immutable original retained in Git |
| [PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md) | [BACKLOG.md](BACKLOG.md) | Short compatibility pointer |
| `PHASE14_15_APP_INTERACTION_REPAIR_PLAN_BATCH1_2026-11-01.md` (local, not in Git baseline) | [BACKLOG.md](BACKLOG.md) | Local source consolidated |
| `PHASE14_15_DEF007_EFFECTIVE_TIME_MEMBERSHIP_PLAN_2026-11-01.md` (local, not in Git baseline) | [BACKLOG.md](BACKLOG.md) | Local source consolidated |
| [PHASE14_15_INTEGRATION_AND_CONSOLIDATION_PLAN.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_INTEGRATION_AND_CONSOLIDATION_PLAN.md) | [BACKLOG.md](BACKLOG.md) | Retired; immutable original retained in Git |
| [PHASE14_15_MANUAL_TESTING.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_MANUAL_TESTING.md) | [PHASE14_15_HOWTO_FIRST_CAMPAIGN.md](PHASE14_15_HOWTO_FIRST_CAMPAIGN.md) | Retired; immutable original retained in Git |
| `PHASE14_15_P02_NAVIGATION_CONTEXT_PLAN_2026-11-02.md` (local, not in Git baseline) | [BACKLOG.md](BACKLOG.md) | Local source consolidated |
| [PHASE14_15_P02_NAVIGATION_ROUTE_AND_GUARD_AUDIT.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_P02_NAVIGATION_ROUTE_AND_GUARD_AUDIT.md) | [UI_DESIGN.md](UI_DESIGN.md) | Retired; immutable original retained in Git |
| [PHASE14_15_P02_RECONCILIATION_2026-11-04.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_P02_RECONCILIATION_2026-11-04.md) | [BACKLOG.md](BACKLOG.md) | Retired; immutable original retained in Git |
| [PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md) | [PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md](PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md) | Retained active handoff; extraction deferred until stable |
| [PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md) | [BACKLOG.md](BACKLOG.md) | Short compatibility pointer |
| [PHASE14_15_STEP_G_REPAIR_REPORT.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_15_STEP_G_REPAIR_REPORT.md) | [PHASE14_15_ACCEPTANCE_LEDGER.md](PHASE14_15_ACCEPTANCE_LEDGER.md) | Retired; immutable original retained in Git |
| [PHASE14_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE14_VERIFICATION.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PHASE15_CP10_HANDOFF.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE15_CP10_HANDOFF.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PHASE15_DEF001_BROWSER_RETEST.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE15_DEF001_BROWSER_RETEST.md) | [PHASE14_15_ACCEPTANCE_LEDGER.md](PHASE14_15_ACCEPTANCE_LEDGER.md) | Retired; immutable original retained in Git |
| [PHASE15_DEF001_INVENTORY.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE15_DEF001_INVENTORY.md) | [PHASE14_15_COVERAGE_MATRIX.md](PHASE14_15_COVERAGE_MATRIX.md) | Retired; immutable original retained in Git |
| [PHASE15_MANUAL_ACCEPTANCE.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE15_MANUAL_ACCEPTANCE.md) | [PHASE14_15_COMPANION_SCENARIOS.md](PHASE14_15_COMPANION_SCENARIOS.md) | Retired; immutable original retained in Git |
| [PHASE1_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE1_VERIFICATION.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PHASE2_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE2_VERIFICATION.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PHASE3_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE3_VERIFICATION.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PHASE4_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE4_VERIFICATION.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PHASE5_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE5_VERIFICATION.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PHASE6_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE6_VERIFICATION.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PHASE7_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE7_VERIFICATION.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PHASE8_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE8_VERIFICATION.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PHASE9_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PHASE9_VERIFICATION.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [PLAN.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PLAN.md) | [README.md](README.md) | Short compatibility pointer |
| [PLATFORM_REVIEW_2026-09-25.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PLATFORM_REVIEW_2026-09-25.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [POSTGRES18_UPGRADE_PLAN.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/POSTGRES18_UPGRADE_PLAN.md) | [DELIVERY_HISTORY.md](DELIVERY_HISTORY.md) | Retired; immutable original retained in Git |
| [QUICKSTART.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/QUICKSTART.md) | [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | Retired; immutable original retained in Git |
| [SCOPED_ROLE_IMPLEMENTATION_PLAN.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/SCOPED_ROLE_IMPLEMENTATION_PLAN.md) | [ACCESS_CONTROL.md](api/ACCESS_CONTROL.md) | Short compatibility pointer |
| [SCOPED_ROLE_INTEGRATION_VERIFICATION.md](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/SCOPED_ROLE_INTEGRATION_VERIFICATION.md) | [PHASE14_15_ACCEPTANCE_LEDGER.md](PHASE14_15_ACCEPTANCE_LEDGER.md) | Retired; immutable original retained in Git |

## Untracked source preservation

The three local planning sources were copied byte-for-byte before consolidation to
`C:/Users/nemes/dnd_ai_documentation_sources_20261108/`. This is local provenance, not a
Git-recoverability claim. Approved current behavior is documented in the topic references;
pending requirements retain the original finding IDs in BACKLOG and the acceptance set.

| Local source | SHA-256 |
|---|---|
| `PHASE14_15_APP_INTERACTION_REPAIR_PLAN_BATCH1_2026-11-01.md` | `9632e562b527e350473989622ee1a53f832f973ecfbc32b16a90343dfe500170` |
| `PHASE14_15_DEF007_EFFECTIVE_TIME_MEMBERSHIP_PLAN_2026-11-01.md` | `0c96475fcd1fa330d18826ce04ca98d726ea1ae3f80dd40cdaa22792a9aaef14` |
| `PHASE14_15_P02_NAVIGATION_CONTEXT_PLAN_2026-11-02.md` | `c0e2489f8d4da5d471cb4a8ec06e6100852c6f6cb5289dba0ed4779184e9b613` |
