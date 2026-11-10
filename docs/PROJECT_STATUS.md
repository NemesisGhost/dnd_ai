# Project status

Documentation reconciled 2026-11-08 against committed baseline `53416d5`; the P03-A row was
updated 2026-11-10 against `bfa64f2`.
This page summarizes recorded delivery state; it is not a new verification run.
Concurrent implementation can be ahead of this baseline. Consult the latest active-plan
handoff and Git history before starting a checkpoint.

**Phase 15 is not complete.** The earlier GM-authoring checkpoint sequence is implemented,
but expanded character/revelation work and broader acceptance remain. Phase 16 is gated on
Phase 15 closure. P02 acceptance does not close Phase 14/15 as a whole.

| Area | Recorded delivery state | Remaining gate / authoritative record |
|---|---|---|
| Database/domain and core API, Phases 0–10 | Delivered baseline; historical verification retained in Git | Preserve current invariants; [delivery history](DELIVERY_HISTORY.md) is not current test evidence |
| Foundry integration, Phase 11 | Per-device pairing and bounded adapter implemented | Live licensed Foundry v13 acceptance remains unrecorded; [procedure](../foundry-module/README.md#manual-live-foundry-verification) |
| AI/NPC MVP, Phase 12 | Provider abstraction and narrow NPC/proposal/synthesis surfaces implemented | Real-provider smoke evidence and Phase 12 closure record remain due |
| Portal/access foundation, Phase 13 | Read portal and access-management mutations delivered | Current contracts in [access control](api/ACCESS_CONTROL.md); later integration/AI surfaces follow the roadmap |
| Authoring kernel, Phase 14 | Closed with accepted limitations; PR #64, merge `3046714`, recorded green CI `37227612984` | Historical navigation/manual limitations must be reconciled with later P02 evidence, not retroactively marked passed |
| GM authoring, Phase 15 | Earlier authoring sequence implemented; active P03-A extends character/public-profile/revelation behavior | [Active plan](PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md), [phase evidence](PHASE15_VERIFICATION.md), integrated acceptance/review/CI/merge gates |
| P02 navigation | Owner acceptance recorded on 2026-11-06 for `81bf164` | B20 keyboard activation, B9 physical Escape/backdrop, B16 actual 200%/400% zoom, B21 deferred/unverified screen reader remain separate; [ledger](PHASE14_15_ACCEPTANCE_LEDGER.md) |
| P03-A prerequisites and profiles | A0/A1/P0/P1/A2a/A2a-R/A2b/P2/P3/A3a/A3b delivered with review records; A3b verification closeout PASS WITH NONBLOCKING FINDINGS; CI run 42755362414 green at `bfa64f2`, draft PR #68 open and unmerged (2026-11-10) | D6 approved 2026-11-10; A4 designed (plan §12), not started; A5–A7 not started. DEF-019/020/021, stale authorization and the A1 wait-observation flake remain open. No new closure inferred here |
| Scoped roles | Implemented and integrated into this branch; historical PR #67 CI and snapshot-upgrade evidence exist | Retain exact rehearsal limits and current acceptance evidence; [ADR 0020](adr/0020-scoped-system-world-and-campaign-roles.md) |
| R19 foundations | ADRs 0021–0023 accepted on 2026-11-06 at reviewed revision `2ca4648`; implementation plan remains proposed | Primary-PC acknowledgment and checkpoint gates in [R19 plan](R19_FOUNDATION_IMPLEMENTATION_PLAN.md) |
| Standalone production packaging, Phase 17 | Base Compose database/migration/API and recovery tooling exist | Portal/worker/ingress/TLS/operations and deployment acceptance per [runbook](LOCAL_DEPLOYMENT.md) and roadmap |

## Completion evidence

The [acceptance ledger](PHASE14_15_ACCEPTANCE_LEDGER.md) owns recorded manual/scripted
results and owner decisions; the [defect register](PHASE14_15_DEFECT_REGISTER.md) owns
defect dispositions. CI on a final head and a merge are independent events. This summary
does not claim either has happened for current uncommitted work.

Use the [roadmap](PLANv2.md) for product order and the [backlog](BACKLOG.md) for open
findings. Historical test counts, superseded findings, and old branch snapshots belong in
[delivery history](DELIVERY_HISTORY.md), not a second current-state inventory.
