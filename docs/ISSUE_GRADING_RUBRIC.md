# Production Issue Grading Rubric

Use this rubric to rank concrete review findings by their likely production impact.
Score each factor, add the points, and apply the severity band below. Record the
reasoning for every factor so the final rank is auditable rather than intuitive.

## Scoring factors

| Factor | Points | Evaluation guidance |
|---|---:|---|
| Production exposure | 0-3 | `0`: unreachable in production; `1`: rare or tightly constrained path; `2`: normal but limited production path; `3`: common, public, privileged-boundary, or always-on path. |
| Impact magnitude | 0-3 | Consider confidentiality, integrity, availability, authentication/authorization, data loss, and operational cost. `0`: no material effect; `1`: minor degradation; `2`: serious partial failure; `3`: security boundary failure, data corruption/loss, or broad outage. |
| Triggerability | 0-2 | `0`: exceptional internal conditions only; `1`: requires authenticated access, special timing, or uncommon configuration; `2`: remotely or unauthenticatedly triggerable, or likely during routine operation. |
| Detection and recovery | 0-1 | `0`: immediately visible and automatically/easily recovered; `1`: silent, misleading, persistent, difficult to diagnose, or requires manual recovery. |
| Blast radius | 0-1 | `0`: one request, record, or user; `1`: multiple users, an instance, a shared dependency, the service, or durable system state. |

Maximum score: **10**.

## Severity bands

| Score | Severity | Default disposition |
|---:|---|---|
| 9-10 | Critical | Merge blocker. Fix before release or deployment. |
| 7-8 | High | Merge blocker. Fix before release or deployment. |
| 4-6 | Medium | Fix soon; merge only with an explicit, evidence-backed risk decision. |
| 1-3 | Low | Minor issue; schedule normally or document why it is accepted. |
| 0 | Informational | Observation with no demonstrated production defect. |

Security-boundary failures may be elevated one severity band when uncertainty
itself creates unacceptable risk. Explain any elevation; do not silently change
the numeric score.

## Environment and production-path grounding

Before scoring a finding, establish the actual environment and deployment path.
Do not assume a production topology, rolling deployment, concurrent traffic,
database size, or operational workflow that has not been shown to exist.

- Score demonstrated or credibly planned production behavior, not a hypothetical
  production scenario. If the affected path exists only in development and has no
  credible production consequence, score **Production exposure** as `0` and do
  not assign points to the other factors for imagined production effects. Such a
  finding will normally be Informational under this production-impact rubric.
- A future production path counts only when there is evidence that the affected
  code or migration will execute under the required conditions. State that
  evidence explicitly.
- Creating a new production database by applying migrations before application
  traffic begins is an offline initialization path, not a rolling deployment.
  Locks that would block concurrent requests do not create an availability impact
  when no concurrent requests can exist.
- A historical migration already applied everywhere is not an active production
  path merely because it remains in the repository. Consider whether it is
  actually replayed during fresh installation, restoration, tenant provisioning,
  or another supported production operation.
- Development disruption, inaccurate documentation, missing tests, and general
  robustness improvements may still deserve correction, but record them
  separately instead of inflating their production severity.
- If the environment or deployment path is unknown and would materially change
  the score, identify the missing fact and obtain it before assigning a definitive
  production severity. Do not default to the most severe plausible topology.

## Migration-specific guidance

For migration findings, identify which concrete path is affected: upgrade of an
existing production database, offline initialization, restoration, tenant
provisioning, staging, or development-only execution.

- An upgrade-only defect must be reachable from a production revision that will
  actually cross the affected migration. A database created at a later baseline
  or migration head does not establish that exposure by itself.
- A concurrency or locking finding requires evidence of concurrent production
  writers or readers. For availability impact, also establish that the expected
  table size or operation duration is material enough to cause observable
  blocking, latency, or timeouts.
- Transactional rollback, maintenance windows, stopped application writers,
  bounded lock timeouts, and offline deployment procedures are relevant
  mitigations and must be reflected in the score.
- A technically stronger-than-documented lock, race window, or failure mode is
  not automatically a production defect. Score its demonstrated operational
  consequence and assess documentation accuracy separately.

## Required assessment fields

For every finding, record:

1. Rank, title, numeric score, and severity.
2. Exact affected component, file, and line or symbol.
3. Production scenario and preconditions.
4. What is impacted: users, data, authorization, availability, dependencies,
   observability, cost, compliance, or deployment/recovery.
5. Failure modes and user/operator-visible symptoms.
6. Evidence supporting the finding, including relevant tests or missing coverage.
7. Factor-by-factor score justification.
8. Recommended correction and regression tests.
9. Any mitigating controls, uncertainty, or accepted residual risk.
10. Environment and deployment-path basis, including whether production exists,
    which deployed revision would traverse the path, whether traffic or direct
    writers remain active, and whether initialization or maintenance is offline.

Rank findings by numeric score descending. For equal scores, place security and
data-integrity issues first, then availability, correctness, and maintainability.
Do not inflate rankings for theoretical concerns without a credible production
path, and do not lower rankings merely because the affected code is newly added
or currently lacks a caller when it establishes a production security boundary.
