# Phase 5 Remaining Issues

> **CLOSED, pending this pass's CI confirmation (2026-08-03).** Revision 056
> (merged, unchanged this pass) closed the schema blocker by adding a
> child-location advisory lock. A fifth review found that while its
> accompanying test rewrite genuinely proved resumed-waiter behavior, two of
> the original verification acceptance criteria were still not met: no test
> queried the final committed database state from an independent connection,
> and the blocking-thread helper had no failure-safe cleanup path. Both are
> fixed in this pass — see
> [§ Fifth review](#fifth-review-test-hardening-and-final-state-verification-2026-08-03)
> below and
> [PHASE5_VERIFICATION.md § Fifth exit review corrections](PHASE5_VERIFICATION.md#fifth-exit-review-corrections-2026-08-03)
> for the full account. No schema or migration change was needed or made —
> revision 056 was reviewed again and found correct. This register is treated
> as closed only once this pass's push-triggered GitHub Actions run is
> confirmed green; see that section for the run and its outcome.
>
> Original framing, preserved below as the review record: Phase 5 was merged
> to `main` by [PR #5](https://github.com/NemesisGhost/dnd_ai/pull/5) at merge
> commit `bcc22ee`, but the post-merge review found three database-integrity
> blockers and two smaller correctness/documentation gaps that the green
> verification suite did not exercise. Revisions 052–055 resolved those five
> findings. A fourth review of merged PR #6 then found one opposing write path
> that revision 053 did not serialize: inserting a `world.dungeon_areas`
> subtype row while another transaction changed the same child location's
> `parent_location_id`, plus a verification gap in the three existing
> revision-053 concurrency tests (they proved lock attachment via
> `lock_timeout` and a fresh-transaction retry, not that the original waiting
> statement itself resumes and revalidates). Both were addressed by revision
> 056 and its accompanying test rewrite, pushed directly to `main` without a
> pull request or CI run — a fifth review (below) treated that as insufficient
> evidence of closure on its own, independent of the two concrete gaps it also
> found in the same test rewrite.

## At a glance (resolved by revision 056)

Phase 5's documented gameplay capabilities were implemented, merged, and
verified before this register was reopened. It failed its full
database-integrity exit requirement until both parts of the gate below closed:

1. **Schema blocker:** dungeon-area subtype creation and direct mutation of the
   same child location's parent did not use a shared child-location lock, so
   two incompatible writes could both commit. **Resolved** by revision 056's
   child-location `pg_advisory_xact_lock`, acquired first in both
   `world.enforce_dungeon_area_parent_dungeon()` and
   `world.enforce_dungeon_area_parent_dungeon_on_update()`.
2. **Verification blocker:** the existing revision-053 concurrency tests proved
   lock attachment by timing out the waiter, but did not prove that the
   original waiting statement resumes, re-reads committed state, and rejects
   an invalid result. **Resolved** by rewriting all three revision-053
   concurrency tests plus two new tests (covering both orderings of the
   child-lock race) to use a real background thread, a `pg_stat_activity`
   poll confirming a genuine lock wait, and an assertion on the resumed
   statement's actual outcome.

## Fourth review baseline and scope

The fourth review examined `main` at merge commit `7ae606c`, with implementation
commit `ea75f65` and Alembic head `055_conditional_route_whitespace`. PR #6 is
merged. Its push-triggered AWS workflow, run
[`30835071145`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30835071145),
passed both jobs, including migration from `base`, full downgrade/upgrade,
seed idempotency, schema comparison, cleanup, and 1,080 tests (13 unit, 1,066
database, and 1 scenario). Local formatting, Ruff, mypy, and all 13 unit tests
also passed during the review.

That evidence remains valid for the behavior it covers. It did not exercise
the race or waiting-statement behavior below, which revision 056 and its
tests now do.

## Fourth-review schema blocker (resolved by revision 056)

### 1. Serialize dungeon-area creation with child-location parent changes

Revision 053 coordinates generic subtype insertion with parent entity-type
changes and coordinates dungeon-area writes with retyping the proposed parent
dungeon. It does not coordinate the two sides of the child-location
relationship itself:

- `world.enforce_dungeon_area_parent_dungeon()` reads the child location's
  `parent_location_id`, then locks the proposed parent dungeon; it never locks
  the child location before that read.
- `world.enforce_dungeon_area_parent_dungeon_on_update()` first checks whether
  the child has a `world.dungeon_areas` row. If the opposing transaction's
  subtype insert is uncommitted, the check returns false and the function exits
  without acquiring a lock shared with that insert.

Consequently, one transaction can insert `world.dungeon_areas` for location L
after validating its old dungeon parent while another transaction changes L's
`parent_location_id` to a non-dungeon or `NULL`. Each transaction can miss the
other's uncommitted write, and both can commit an invalid final state. The race
exists with either transaction starting first.

Acceptance criteria:

- Add a forward-only Alembic revision after 055. Do not edit revisions
  038–055.
- Introduce one documented advisory-lock protocol keyed by the child location
  for both `world.dungeon_areas` INSERT/UPDATE and every
  `world.locations.parent_location_id` mutation that can create or invalidate
  the relationship.
- Acquire the child-location lock before reading either the subtype row or the
  child's parent. Re-read the protected state after the lock is acquired.
- Preserve revision 053's proposed-parent/type-change serialization. If a path
  needs both child and parent locks, document and enforce a deterministic
  acquisition order so the fix does not introduce a deadlock cycle.
- Reject clearing a dungeon area's parent or moving it beneath a non-dungeon;
  continue permitting a valid reparent to another dungeon and ordinary
  reparenting of locations that are not dungeon areas.
- Confirm the same child-side gap does not affect another Phase 5 subtype or
  structural relationship. Record the review result even if no additional
  function requires changes.

## Fourth-review verification obligations (resolved by revision 056)

The revision-053 concurrency tests prove that a second statement encounters a
lock by intentionally causing `lock_timeout`, rolling that transaction back,
and performing a new sequential retry. This is useful lock-attachment evidence,
but it does not prove that the original waiting statement resumes after the
blocker commits, takes a fresh READ COMMITTED snapshot, and revalidates the
invariant.

Acceptance criteria:

- Add genuine two-connection tests for dungeon-area insertion versus changing
  the same child location's parent, covering both operation orderings.
- Keep the original second statement alive while the first transaction commits
  or rolls back. Prove the waiter resumes and either succeeds or is rejected
  from the newly committed state; do not substitute a timed-out transaction
  followed by a third-connection retry.
- Extend the three existing revision-053 concurrency tests to the same standard,
  because the original remaining-issues acceptance criterion required the
  waiting statement itself to resume and revalidate.
- Use bounded synchronization (for example, futures/events plus a watchdog
  timeout) and guaranteed teardown so a failure cannot hang CI, leak
  transactions, or leave the ephemeral database dirty.
- Assert the final committed graph and type/subtype state after each ordering;
  at most one incompatible operation may succeed, and no invalid state may
  remain.

## Fourth-review completion gate (satisfied by revision 056)

Phase 5 closes only once the blocker and verification obligations above are
implemented and `PHASE5_VERIFICATION.md` records:

- the new forward-only revision and exact child-location/parent lock protocol;
- two-ordering coverage for dungeon-area creation versus parent mutation;
- resumed-waiter coverage for all affected revision-053 concurrency cases;
- formatting, Ruff, mypy, the full unit/database/scenario suite, migration
  upgrade and downgrade/upgrade checks, seed idempotency, and `alembic check`;
- a fresh push-triggered GitHub Actions AWS workflow, including cleanup; and
- repository-wide status reconciliation that closes this register and unblocks
  Phase 6 feature/schema work, assuming its separate context-modularization gate
  is also complete.

See [PHASE5_VERIFICATION.md § Fourth exit review corrections](PHASE5_VERIFICATION.md#fourth-exit-review-corrections-2026-08-03)
for exact commands, results, and the confirmed CI run.

## Fifth review: test-hardening and final-state verification (2026-08-03)

Revision 056 and its first test rewrite were pushed directly to `main`
without a pull request, so no GitHub Actions run had ever verified them —
only local `pytest` runs against AWS `dev`. A fifth review started from that
observation and re-checked the five resumed-waiter tests against the
acceptance criteria in the "Fourth-review verification obligations" section
above line by line. Six of the seven were genuinely met (the waiter
genuinely blocks, is not substituted with a retry, resumes after the blocker
commits, re-reads committed state, and is asserted to succeed or fail
accordingly, all with bounded synchronization). Two were not:

1. **No independent, fresh-connection final-state assertion.** Every test
   asserted only the *exception* the resumed statement raised (or its
   absence). None of the five then queried the actual committed rows from a
   third connection to prove directly that no invalid combination
   survived — a dungeon-area location without a valid dungeon parent, a
   subtype row incompatible with `core.entities.entity_type`, or a
   dungeon-area row left dependent on an entity no longer registered as a
   dungeon. Message-matching proves the rejected statement failed for the
   expected *reason*; it does not by itself prove the *database* ended up in
   a valid state — a defect in an unrelated code path could raise the same
   message text without actually protecting the invariant.
2. **No failure-safe cleanup for the blocking thread.** Each test's
   `thread.join(timeout=10.0)` was followed by a plain
   `assert not thread.is_alive()`. If that assertion ever failed — a real
   regression reintroducing the deadlock the lock protocol exists to
   prevent, for example — the background thread and its open connection/
   transaction would be abandoned: no code path terminated it, closed its
   connection, or released whatever lock it still held. A single failing
   assertion could therefore leak an advisory lock into every later test in
   the same session (each keyed by fresh per-test UUIDs, so the leaked lock
   itself would not block *those* tests' own operations, but the leaked
   thread and open transaction would persist until the test process exited)
   and would not be guaranteed to unblock promptly even then.

**Fix:** no schema or migration change — revision 056 and the revision-053
trigger functions were reviewed again (see
[PHASE5_VERIFICATION.md § Fifth exit review corrections](PHASE5_VERIFICATION.md#fifth-exit-review-corrections-2026-08-03))
and found correct: both dungeon-area subtype writes and child
`parent_location_id` mutations still acquire the same child-location
advisory lock before any read, state is re-read after the lock is acquired,
the existing parent-dungeon/entity-type protections from revision 053 are
intact, lock ordering remains deterministic (child-location namespace always
before entity-subtype namespace) with no new deadlock path, both concurrency
orderings are still covered, and no other Phase 5 structural relationship has
the same uncoordinated child-side gap. All changes are confined to
`tests/database/test_entity_type_change_protection.py`:

- A new `_BackgroundStatement` context-manager class replaces the previous
  free-function-plus-tuple helper. Its `__exit__` guarantees the background
  thread and its backend connection cannot outlive the `with` block: if the
  thread is still alive when the block exits — for any reason, including an
  assertion failure or a timeout — it force-terminates the backend via
  `SELECT pg_terminate_backend(:pid)` (which releases any advisory lock or
  open transaction that backend still holds) and only then joins with a
  bounded timeout. Cleanup failures are caught and discarded rather than
  raised, so a broken lock protocol can hang neither the test run nor a
  later test, and cleanup can never replace the original failure as the
  reported cause.
- Each of the five tests now opens a third, independent connection after
  asserting the resumed statement's outcome and queries the committed rows
  directly: entity type versus subtype-table presence for the two
  entity-type-change races, `parent_location_id` versus dungeon-area-row
  presence for the reparent and both child-lock races. Every assertion
  states the specific invalid combination it rules out.

**Tests:** the same five tests (three revision-053, two revision-056), all
rewritten in place — no test was added, removed, or renamed. All 14 tests in
the file, including the nine pre-existing sequential cases, pass locally
against AWS `dev`; see the verification commands in
[PHASE5_VERIFICATION.md § Fifth exit review corrections](PHASE5_VERIFICATION.md#fifth-exit-review-corrections-2026-08-03).

## Previously resolved register (historical)

### Prior review baseline and scope

The review examined merge commit `bcc22ee`, whose Phase 5 implementation head
was `f017e67` and whose Alembic head is `051_conditional_route_semantics`.
GitHub Actions runs
[`30801159031`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30801159031)
and
[`30803444653`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30803444653)
passed formatting, Ruff, mypy, the full downgrade-to-base/upgrade-to-head
round trip, seed idempotency, `alembic check`, all 1,066 tests (13 unit, 1,052
database, and 1 scenario), database cleanup, and ingress revocation.

That evidence remains valid for the cases it covers. The items below concern
final-schema behavior and upgrade paths that those tests do not model.

### Prior schema blockers

> Resolved by revisions 052–055, subject to the narrower revision-053 gap in
> the current blocker above.

#### 1. Serialize entity-type changes with subtype and dungeon-area writes

Revision 048 added parent-side checks to reject an entity-type change that
would strand an existing subtype row or dungeon-area children. The checks read
the dependent tables without taking a lock shared by the opposite write path.

Two concurrent transactions can therefore validate against different committed
snapshots and both succeed. Representative races include:

- inserting a subtype row while another transaction changes the owning
  `core.entities.entity_type_id` to a type that does not permit that subtype;
- inserting a dungeon area while another transaction removes the
  `world.dungeons` marker and retypes the parent entity; and
- reparenting or otherwise creating a dungeon-area dependency while another
  transaction retypes the proposed dungeon parent.

Sequential tests in `test_entity_type_change_protection.py` do not cover these
write-skew cases.

Acceptance criteria:

- Add a new forward-only Alembic revision after 051; do not edit revisions
  038–051 for this item.
- Use one documented, deterministic locking protocol keyed by the affected
  entity or entities. Every path that can create, remove, or invalidate the
  protected relationship must participate before it validates the invariant.
- Cover generic subtype INSERT/UPDATE versus parent type change, plus the
  dungeon-specific subtype/child paths. Do not fix only `world.dungeons` while
  leaving the generic `core.enforce_entity_subtype()` race intact.
- Preserve valid type corrections made before any subtype or dependent row
  exists.
- Add genuine two-connection tests with overlapping transactions. Prove the
  second statement waits or otherwise serializes, then prove that no ordering
  can commit an invalid final state. A sequential retry is additional evidence,
  not a substitute for testing the original waiting statement.
- Use bounded synchronization and cleanup so a failed concurrency assertion
  cannot hang CI or leak data.

#### 2. Make containment-cycle validation complete and corruption-safe

Revision 049 correctly serializes containment changes per world, closing the
reported two-writer race. Its recursive CTE stops when `depth` reaches 10,000,
however, without recording visited locations or checking that the bound was
exceeded.

As a result:

- a proposed cycle whose relevant ancestor lies beyond the cutoff can be
  accepted;
- a pre-existing cycle not containing the row being updated is silently
  truncated rather than rejected; and
- the function and documentation claim “a cycle of any length” and a “bounded
  error,” neither of which the current function guarantees.

Acceptance criteria:

- Add a new forward-only Alembic revision after 051 that replaces
  `world.enforce_location_no_cycle()` while preserving the per-world advisory
  locking protocol.
- Track visited location IDs, or use PostgreSQL's recursive-query cycle
  detection, and explicitly reject a repeated node.
- If a separate operational safety bound remains, exceeding it must raise a
  clear integrity error; it must never be interpreted as proof that the
  hierarchy is acyclic.
- Reject a cycle regardless of its position in the ancestry chain, including a
  corrupt pre-existing loop that does not initially include `NEW.location_id`.
- Retain the genuine two-connection serialization test and the sequential
  two-node/multi-node/valid-reparenting tests.
- Add focused tests for repeated-node detection and safety-bound behavior. If
  test setup must bypass the production trigger to model legacy corruption,
  isolate and restore that setup explicitly.
- Correct the database function comment, SQLAlchemy metadata where applicable,
  `DATABASE_MODEL.md`, and `PHASE5_VERIFICATION.md` to describe the final
  behavior exactly.

#### 3. Repair the populated revision-042/043 upgrade path

Revision 043 adds nullable `location_period` but does not derive it for rows
already present in `campaign.character_location_history`. Revision 050 counts
NULL periods and aborts instead of backfilling them. A database containing a
valid revision-042 history row with usable world-time endpoints can therefore
fail before reaching the final schema, even though its range is derivable.

This issue requires an explicit migration-policy decision: an ordinary revision
after 051 cannot repair a database that fails while executing revision 050 and
therefore never reaches the later revision.

Acceptance criteria:

- Provide a supported path that derives `location_period` from the referenced
  arrival/departure `core.world_times.sort_key` values before revision 050 sets
  `NOT NULL`.
- Decide and document how this is delivered now that 050 has been merged: either
  correct the not-yet-production migration under a narrowly recorded exception
  to the forward-only policy, or supply a mandatory, idempotent pre-050 repair
  step that the normal deployment workflow invokes before `alembic upgrade`.
  Do not add an unreachable revision 052 and call the older upgrade path fixed.
- Validate timeline, character, location, endpoint-world agreement, ordering,
  and overlaps while deriving ranges. Fail clearly for non-derivable rows,
  including a missing arrival endpoint, rather than manufacturing chronology.
- Add an upgrade fixture at revision 042 containing at least one valid open row
  and one valid closed row, then run the supported upgrade path through head and
  assert their exact derived ranges.
- Add negative upgrade fixtures for non-derivable or conflicting legacy rows
  and assert the documented failure/remediation behavior.
- Retain final-schema catalog tests proving `location_period` is `NOT NULL` and
  caller-supplied values are overwritten by the derivation trigger.
- Correct every claim that revision 050 already performs a backfill; it currently
  performs only a NULL assertion.

### Prior correctness and documentation gaps

#### 4. Treat all whitespace-only conditional descriptions as blank

`ck_area_connections_conditional_description_paired` uses
`trim(both ' ' from condition_description)`. PostgreSQL therefore removes
ordinary spaces only; a string containing only tabs, newlines, or carriage
returns still satisfies the claimed nonblank rule.

Acceptance criteria:

- Add a forward-only migration that defines “blank” using the project's chosen
  complete whitespace rule. Do not mirror the CHECK in SQLAlchemy metadata:
  `src/dnd_ai/persistence/tables/` (the `dnd_ai.persistence.tables` package;
  see its `__init__.py`) intentionally excludes all CHECK constraints,
  triggers, and default privileges from the metadata model. Record that
  project-wide exception explicitly and cover the live constraint through
  migration/integration tests.
- Reject space-only, tab-only, newline-only, carriage-return-only, and mixed
  whitespace descriptions on INSERT and UPDATE.
- Retain positive tests for ordinary descriptive text and the rule that an
  unconditional route must have a NULL description.
- Update schema comments and verification documentation so “nonblank” means the
  behavior the database actually enforces.

#### 5. Keep Phase 5 counts and status language exact

`PHASE5_VERIFICATION.md` previously said “Nine revisions” while listing the 14
revisions from 038 through 051. The merged documentation also described Phase 5
as complete and Phase 6 as current despite the open items above.

Acceptance criteria:

- Keep the Phase 5 inventory at 14 revisions, 24 new tables, and six columns
  added to previously existing tables until a corrective revision changes those
  counts.
- Keep status documents consistent: Phase 5 is merged but remains open; Phase 6
  is queued and must not begin until this register closes.
- When all items close, convert this file to a closed historical record, update
  `PHASE5_VERIFICATION.md` with the corrective revision(s), tests, exact totals,
  and CI evidence, and advance all current-phase statements together.

### Prior five-item completion gate (satisfied by revisions 052–055)

Close Phase 5 only after all five items meet their acceptance criteria and
`PHASE5_VERIFICATION.md` records:

- The migration-policy decision and populated upgrade proof for item 3.
- Shared-locking coverage and genuine two-connection tests for item 1.
- Complete cycle/corruption detection and the retained concurrency proof for
  item 2.
- Full whitespace semantics for conditional routes.
- `ruff format --check`, `ruff check`, and mypy clean.
- The full unit, database, and scenario suite green with updated totals.
- Upgrade from the supported populated Phase 5 baseline through the new head.
- Required bounded and full downgrade/upgrade checks.
- Seed reproducibility/idempotency and `alembic check` clean.
- A complete push-triggered GitHub Actions AWS workflow green, including
  cleanup.
- Final repository-wide documentation reconciliation that closes this register
  and unblocks Phase 6.

## Explicitly not tracked

- Conditional-route evaluation, which belongs to Phase 6 for interaction/check
  conditions and Phase 7 for quest-gated conditions.
- Knowledge-item temporal validity and the remainder of the knowledge model,
  which remain Phase 7 work.
- Real discovery provenance, which remains Phase 6 work once interactions and
  events exist.
- `world.area_spawn_definitions`, which remains Phase 9 work with encounters and
  a real creature-instance/stat-block model.
- Previously closed Phase 5 findings whose negative and concurrency cases are
  already implemented and verified; this register tracks only the gaps present
  at merge commit `bcc22ee`.
