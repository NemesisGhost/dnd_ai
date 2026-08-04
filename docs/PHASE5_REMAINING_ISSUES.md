# Phase 5 Remaining Issues

> **REOPENED (2026-08-03).** Revisions 052–055 resolved the five findings in
> the original register below, and GitHub Actions run
> [`30835071145`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30835071145)
> passed migrations, schema checks, cleanup, and all 1,080 tests. A fourth
> review of merged PR #6 found one opposing write path that revision 053 does
> not serialize: inserting a `world.dungeon_areas` subtype row while another
> transaction changes the same child location's `parent_location_id`. Phase 5
> remains in closeout until the current item and its concurrency-proof
> requirements below are complete.
>
> Original framing, preserved below as the review record: Phase 5 was merged
> to `main` by [PR #5](https://github.com/NemesisGhost/dnd_ai/pull/5) at merge
> commit `bcc22ee`, but the post-merge review found three database-integrity
> blockers and two smaller correctness/documentation gaps that the green
> verification suite did not exercise.

## Current review baseline and scope

The fourth review examined `main` at merge commit `7ae606c`, with implementation
commit `ea75f65` and Alembic head `055_conditional_route_whitespace`. PR #6 is
merged. Its push-triggered AWS workflow, run
[`30835071145`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30835071145),
passed both jobs, including migration from `base`, full downgrade/upgrade,
seed idempotency, schema comparison, cleanup, and 1,080 tests (13 unit, 1,066
database, and 1 scenario). Local formatting, Ruff, mypy, and all 13 unit tests
also passed during the review.

That evidence remains valid for the behavior it covers. It does not exercise
the race or waiting-statement behavior below.

## Current schema blocker

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

## Current verification obligations

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

## Current completion gate

Close Phase 5 only after the blocker and verification obligations above are
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
  `src/dnd_ai/persistence/tables.py` intentionally excludes all CHECK
  constraints, triggers, and default privileges from the metadata model. Record
  that project-wide exception explicitly and cover the live constraint through
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
