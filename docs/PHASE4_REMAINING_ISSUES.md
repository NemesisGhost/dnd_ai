# Phase 4 Remaining Issues

> **OPEN (2026-08-02).** Revision 034 and GitHub Actions run
> [`30765722355`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30765722355)
> are green, but a post-closeout review found two final-schema integrity gaps and
> three missing verification cases. Phase 5 remains blocked until this register is
> cleared and the resulting GitHub Actions run succeeds.

## Review baseline and scope

The review examined commit `257325f` after revisions `031`–`034`. The push-triggered
GitHub Actions run completed successfully: migration from empty to head, full
`downgrade base` → `upgrade head`, seed verification, `alembic check`, formatting,
Ruff, mypy, all 830 tests, ephemeral-database removal, and ingress revocation.

The items below concern the final revision-034 schema or verification obligations
that remain relevant to later phases. They do not reopen the seven revision-030
findings that revisions `031`–`034` resolved.

Historical states that existed only between revisions are intentionally excluded.
The project has no production data to preserve and previously applied migrations
remain immutable. A historical transition belongs here only if an already-deployed
database may contain affected data or the final behavior can damage later work.

## Schema blockers

### 1. Make world-ruleset allow-list enforcement concurrency-safe

The dependency checks added by revisions 029 and 031 are correct inside one
transaction, but they do not coordinate concurrent dependency creation and
allow-list deletion or repointing. At the documented `READ COMMITTED` isolation
level, one transaction can validate a new dependent row while another transaction
deletes the still-apparently-unused `rules.world_rulesets` row. Both can then commit,
leaving final data that violates the allow-list invariant.

This race affects world defaults, campaigns, character species, character builds,
applied conditions, and tracked resources.

Acceptance criteria:

- Coordinate both sides of the invariant with compatible row locks or one
  consistently acquired transaction-scoped advisory lock.
- Dependency creation must hold a lock that conflicts with deleting or repointing
  the applicable `(world_id, ruleset_id)` association until commit.
- Preserve the existing single-transaction behavior and error messages where
  practical.
- Add two-connection tests proving concurrent delete and repoint attempts cannot
  commit around each dependency category. Follow the established party-membership
  concurrency-test pattern.
- Document the chosen locking order to prevent later phases from introducing a
  deadlock-prone acquisition order.

### 2. Complete rule-content identity immutability

`DATABASE_MODEL.md` requires rule-content `ruleset_version_id` values to be immutable
identity. Revision 033 added the policy to the parent sides of current cross-version
relationships but omitted these rule-definition tables:

- `rules.creature_types`
- `rules.languages`
- `rules.feats`

Those columns remain mutable, which contradicts the authoritative model and allows
later phases to attach references to definitions whose version identity can change.

Acceptance criteria:

- Add all three tables to the `core.enforce_immutable_columns()` trigger coverage in
  a new forward-only migration.
- Add a negative update test for each table and retain positive insert coverage.
- Add a table-driven test that compares all rule-definition tables declared by the
  model with the installed immutability triggers, so a later definition table cannot
  be silently omitted.
- Keep `DATABASE_MODEL.md` as the normative rule and remove its temporary
  implementation-gap note when the migration lands.

## Verification obligations

### 3. Add the missing proficiency update test

Revision 032 enforces the proficiency type's ruleset version on both insert and
update, but the closeout suite proves only the negative insert and positive
same-version paths.

Acceptance criteria:

- Start with a valid proficiency, update `proficiency_type_id` to a type from a
  different ruleset version, and prove the database rejects the update.
- Prove the original valid row remains unchanged after the failed statement.

### 4. Assert the seeded ruleset family/version separation

Revision 034 updates the family and version display data, but no test directly
asserts the final seeded values.

Acceptance criteria:

- Assert family code `dnd5e` and display name `D&D 5e`.
- Assert that the family description is edition-neutral.
- Assert version label `2024` and that the version description carries the
  edition-specific meaning.
- Keep these assertions within the frozen structured-seed verification so later
  seed changes require an intentional forward-only migration and manifest update.

### 5. Test the CI cleanup failure path safely

The workflow now attempts both cleanup operations and combines their exit codes,
but only the successful path has been demonstrated. The implementation should be
testable without intentionally leaking a database or ingress rule in AWS.

Acceptance criteria:

- Extract the result-combining cleanup logic into a small testable script or
  equivalent reusable unit.
- Simulate database-drop failure, ingress-revocation failure, and both failures.
- Prove both operations are attempted in every case and the combined command exits
  nonzero when either fails, while identifying each failed operation.
- Retain one real successful GitHub Actions cleanup as end-to-end evidence. Do not
  deliberately leave an AWS database or security-group rule behind merely to test
  failure reporting.

## Completion gate

Close Phase 4 only after all five items meet their acceptance criteria and the
following evidence is recorded in `PHASE4_VERIFICATION.md`:

- New forward-only corrective migration or migrations; no edits to applied
  revisions.
- Positive, negative, and two-connection tests required above.
- `ruff format --check`, `ruff check`, and mypy clean.
- Full test suite green.
- Upgrade from revision 034 to the new head.
- Full `downgrade base` → `upgrade head` round trip.
- Seed reproducibility/idempotency checks green.
- `alembic check` clean.
- The complete GitHub Actions AWS workflow green, including cleanup.
- Final documentation reconciliation converting this register back to a closed
  record and unblocking Phase 5.

## Explicitly not tracked

- **Revision 023's ordering while upgrading a populated revision-022 database.**
  The project has no production data to preserve, the deployed verification
  databases are ephemeral, and only the final schema matters. Revisit only if an
  actual persistent revision-022 database is discovered.
- **Open-ended session intervals.** Start-only sessions intentionally represent an
  ongoing fictional-time interval with an unbounded upper range. Unscheduled
  sessions use neither endpoint and have a `NULL` range; overlapping sessions remain
  allowed.
- **Intermediate names, values, and columns inside applied revisions.** The final
  schema is authoritative; prior migrations remain historical and forward-only.
- **The seven revision-030 closeout findings.** Revisions `031`–`034` resolved their
  single-transaction behavior, metadata, naming, provenance-policy, and cleanup
  implementation requirements. Only the concurrency and verification follow-ups
  above remain.
