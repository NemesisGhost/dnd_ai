# Issue Grading and Review Disposition Rubric

Use this rubric to rank concrete findings by demonstrated impact and credible
supported use. Record severity separately from whether a finding prevents the
current checkpoint from meeting its acceptance criteria.

## Current project basis

As confirmed by the owner on 2026-11-07, the application is undeployed and has no
production data or production rollback requirement. Development and disposable
test databases exist. Reassess this basis when deployment or data use changes.

- Do not assume rolling deployments, production traffic during migrations,
  production database size, or an obligation to preserve every development
  database revision.
- Do not treat all development data as disposable. Real campaign content,
  owner-authored records, and data explicitly designated for preservation require
  protection. A database is disposable only when that status is established.
- Runtime authorization, disclosure, corruption, and concurrency defects can
  matter before deployment. Ground their exposure in current supported use or
  the concrete planned application path. Lack of deployment alone does not make
  functioning application code unreachable.
- Record production-impact claims separately from current development impact.
  Repository requirements still apply. Identify any requirement that should be
  amended rather than inventing additional release gates.

## Scoring factors

| Factor | Points | Evaluation guidance |
|---|---:|---|
| Supported-path exposure | 0–3 | `0` unreachable in supported use or no credible application consequence; `1` rare, constrained, or operator-only path; `2` normal but limited application path; `3` common, public, privileged-boundary, or always-on path. Name the environment and caller. |
| Impact magnitude | 0–3 | `0` no material effect; `1` minor degradation, bounded request failure, or modest operator work; `2` serious partial failure or loss of meaningful work; `3` authorization/confidentiality boundary failure, corruption or loss of valuable data, or broad outage. |
| Triggerability | 0–2 | `0` exceptional internal conditions; `1` special timing, uncommon configuration, or constrained authenticated action; `2` routine operation or readily repeatable remote triggering. Authentication alone does not make an otherwise routine action rare. |
| Detection and recovery | 0–1 | `0` visible and automatically or easily recovered; `1` silent, misleading, persistent, difficult to diagnose, or requiring substantial manual recovery. |
| Blast radius | 0–1 | `0` bounded to one request, record, or user; `1` affects multiple users, a shared service, or persistent state beyond that bounded operation. A durable row alone does not establish broad impact. |

Maximum score is **10**. Explain every factor. Do not double-count a consequence
or give imagined production effects points under another factor.

## Severity and checkpoint disposition

| Score | Severity | Default disposition |
|---:|---|---|
| 9–10 | Critical | Stop affected work and correct before integration or use. |
| 7–8 | High | Block affected integration or release until corrected. |
| 4–6 | Medium | Prioritize a bounded correction. Acceptance with the issue requires an explicit, evidence-backed risk decision. |
| 1–3 | Low | Schedule normally or document acceptance. Block a checkpoint only when its specific acceptance contract cannot be met. |
| 0 | Informational | Record the observation where useful. No product-severity blocker. |

Give each finding a separate readiness disposition, such as blocking this slice,
required before deployment, follow-up, or accepted. Explain that disposition.
A low-severity defect can fail a specific promised behavior without becoming a
high-severity defect. A pre-existing issue can block a new slice if the slice
inherits or worsens it; identify the dependency explicitly.

Use **CHANGES REQUIRED** for demonstrated implementation defects or design gaps
that prevent the scoped acceptance contract from being met. Use **PASS WITH
NONBLOCKING FINDINGS** when the scoped behavior is supported and residual issues
can be tracked separately. An unexecuted required check is a verification gap;
state it without presenting it as a demonstrated application defect.

Security-boundary findings may be elevated one severity band when evidence shows
the residual uncertainty is unacceptable. Explain the elevation and retain the
numeric score. Do not elevate merely because a finding mentions security.

## Data preservation priorities

Assess the data's value, ownership, reproducibility, and approved lifecycle before
scoring loss or corruption.

| Data or operation | Priority guidance |
|---|---|
| Real campaign/user data, private content, access decisions | Protect confidentiality and integrity in normal reads and writes. Undeployed status does not authorize loss or disclosure. |
| Failed or retried application request | Preserve transaction atomicity. A failure must not leave partial business writes, incorrect access, duplicate effects, or a misleading completed receipt. |
| Immutable releases and provenance | Enforce the guarantees the application relies on for safe reads. Distinguish a reachable application bypass from unsupported direct SQL or a stated database-integrity promise. |
| Disposable fixtures and test databases | Re-creation is normally acceptable. Loss of reproducible fixtures is not equivalent to loss of user data. Cleanup must target only resources owned by the run. |
| Explicitly disposable development database | Reset or rebuild may be an acceptable migration strategy. Obtain authorization before destroying existing data; scoring a reset as acceptable is not permission to execute it. |

For each preservation finding, name the exact records at risk and whether a
failed transaction actually commits damage. A visible failure with complete
rollback is generally an availability/correctness issue, not data corruption.

## Migrations and rollback

Distinguish these three operations before assessing a finding:

1. **Request rollback** undoes a failed runtime operation. Atomicity remains a
   correctness requirement in development and production.
2. **Migration failure rollback** leaves a failed upgrade in its documented state.
   Verify the supported database and migration runner's transactional behavior.
3. **Deployment downgrade** returns an installed schema/application to an earlier
   version. Support depends on the actual release and recovery contract.

For this undeployed project, missing optional downgrade support, inability to
preserve disposable fixtures across revisions, or lack of a hypothetical
production rollback path is normally a development/recovery limitation. It does
not automatically block feature implementation. If repository policy explicitly
requires a downgrade, assess compliance separately and allow the owner to amend
that policy.

- Identify the actual path: fresh initialization, upgrade of a retained database,
  restoration, tenant provisioning, or an explicitly supported downgrade.
- For unreleased migrations, editing or consolidating revisions can be acceptable
  when repository policy permits. Account for development databases already at
  those revisions, which will not automatically rerun an edited upgrade. Document
  a reset, corrective migration, or other concrete reconciliation path as needed.
- A downgrade that is unsupported can refuse clearly. Do not require elaborate
  data-preserving reverse transformations without an actual requirement.
- Existing downgrade guards need not be removed. Grade proposed additional guards
  by their demonstrated need. A downgrade restoring weaker enforcement is not
  automatically a runtime disclosure; identify the subsequent write or read that
  would violate a supported guarantee.
- Prioritize correct forward installation, supported retained-data upgrades, and
  runtime integrity over optional reverse migration convenience.
- Offline initialization has no concurrent application traffic unless evidence
  establishes otherwise. Migration lock availability findings need a credible
  concurrent workload and material operational consequence.
- A historical migration can still be reachable during a fresh installation.
  Name that path rather than assuming every historical revision runs against
  populated production data.

## Runtime concurrency, idempotency, and unsupported inputs

- Grade deadlocks by frequency, reachability, transaction outcome, retry behavior,
  and affected users. A rare deadlock returning a visible failure with complete
  rollback is usually Low. Routine failures or partial commits can justify more.
- A reproducible new deadlock can still block the slice's stated concurrency
  acceptance even when its severity is Low. Scope the correction to that behavior.
- Reuse of an idempotency key across routes or payloads may be rejected. It must
  preserve the documented conflict behavior and transaction integrity. Do not
  silently change key scope or retry semantics to remove a race.
- Raw SQL fixtures are appropriate for database invariants and legacy states.
  They do not establish that a normal caller can create that state. Conversely,
  an explicitly promised database invariant can be defective without a route
  exploit. State both reachability and the violated contract.
- Distinguish actual supported command/HTTP races from SQL models. Models support
  design hypotheses; production-path tests establish implemented outcomes.

## Test, harness, and verification findings

| Finding | Assessment |
|---|---|
| Test exposes an application defect | Grade the application behavior. Use the test as evidence. |
| Incorrect test expectation or obsolete fixture | Correct the test. Do not assign the application the severity implied by the assertion alone. |
| Harness timeout, scheduling sensitivity, weak blocker observation | Track as a test-reliability finding until diagnostics establish an application cause. Repeated passing reruns do not identify that cause. |
| Harness cleanup affects user databases, unrelated sessions, or files | Grade the actual destructive impact. Test code can have serious operational consequences. |
| Missing coverage with no demonstrated defect | Record a coverage gap, normally Informational or Low in the engineering track. Identify a concrete risk rather than assuming failure. |
| Required test/check remains unexecuted | Report verification as pending or blocked, with the specific reason. Do not claim a pass. |
| Environment-dependent failure | Reproduce under the documented environment. Isolate repository overrides without pinning the expected result or disabling the behavior being tested. |

Record a test-only finding on an engineering track rather than assigning invented
product effects. Give its actual maintenance, CI, or developer impact and priority.
If the scoring factors genuinely apply, use them with that scope stated clearly.
Do not call a failure a known flake solely because it resembles an earlier timeout.

Run focused tests and required repository checks. Broaden testing for shared
behavior changes, migration effects, demonstrated failures, or explicit full-suite
requirements. A documentation-only correction normally needs a diff check, not
another full suite. Repeat concurrency runs when they test a concrete unresolved
timing concern; avoid arbitrary rerun counts as a substitute for diagnosis.

Preserve the first-run result, failure diagnostics, and separate rerun results.
Report independent checks separately from implementer-reported evidence. A full
run with failures remains a failed run even if subsequent targeted reruns pass.

## Required assessment fields

For each concrete finding, record:

1. Title, affected file/symbol, and evidence or reproduction.
2. Track: application, migration/operations, test/tooling, documentation, or design.
3. Environment, supported path, caller, preconditions, and data at risk.
4. Observed failure and whether it persists, commits partial state, or rolls back.
5. Factor scores and severity, or the reason no product score is applicable.
6. Readiness disposition and the specific acceptance criterion or policy it affects.
7. Recommended bounded correction and verification proportional to the change.
8. Mitigations, uncertainty, prior existence, and any accepted residual risk.

Keep the fields concise for small findings. Do not turn each observation into a
separate approval gate. Group findings with the same cause and correction.

Rank by severity and score, then prioritize security and valuable-data integrity,
availability, functional correctness, and engineering reliability. Within the
current checkpoint, address concrete blockers before unrelated follow-ups.
Accepted owner decisions persist. Reopen them only when new evidence materially
changes the stated consequence or the proposed implementation violates them.
