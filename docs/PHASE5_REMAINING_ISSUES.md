# Phase 5 Remaining Issues

> **CLOSED (2026-08-03).** All five items below are implemented, tested, and
> verified — see
> [PHASE5_VERIFICATION.md § Third exit review corrections](PHASE5_VERIFICATION.md#third-exit-review-corrections-2026-08-03)
> for the resolving revisions (`052`–`055`) and evidence: the revision-052
> splice point exercised in both directions, a fresh from-`base` migration
> run against an empty database, `alembic check`, `ruff format`/`ruff check`/
> `mypy src`, and the full suite (1,080 tests, up from 1,066), all against the
> deployed AWS `dev` instance, plus a push-triggered GitHub Actions AWS
> workflow. Phase 5 is complete; this register is now a closed historical
> record.
>
> Original framing, preserved below as the review record: Phase 5 was merged
> to `main` by [PR #5](https://github.com/NemesisGhost/dnd_ai/pull/5) at merge
> commit `bcc22ee`, but the post-merge review found three database-integrity
> blockers and two smaller correctness/documentation gaps that the green
> verification suite did not exercise.

## Review baseline and scope

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

## Schema blockers

### 1. Serialize entity-type changes with subtype and dungeon-area writes

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

### 2. Make containment-cycle validation complete and corruption-safe

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

### 3. Repair the populated revision-042/043 upgrade path

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

## Correctness and documentation gaps

### 4. Treat all whitespace-only conditional descriptions as blank

`ck_area_connections_conditional_description_paired` uses
`trim(both ' ' from condition_description)`. PostgreSQL therefore removes
ordinary spaces only; a string containing only tabs, newlines, or carriage
returns still satisfies the claimed nonblank rule.

Acceptance criteria:

- Add a forward-only migration that defines “blank” using the project's chosen
  complete whitespace rule, and mirror the final constraint in SQLAlchemy
  metadata.
- Reject space-only, tab-only, newline-only, carriage-return-only, and mixed
  whitespace descriptions on INSERT and UPDATE.
- Retain positive tests for ordinary descriptive text and the rule that an
  unconditional route must have a NULL description.
- Update schema comments and verification documentation so “nonblank” means the
  behavior the database actually enforces.

### 5. Keep Phase 5 counts and status language exact

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

## Completion gate

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
