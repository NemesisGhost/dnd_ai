# Phase 5 Remaining Issues

> **CLOSED (2026-08-04).** A tenth review found the ninth pass's fixes still
> left `_BackgroundStatement`'s worker thread architecture unable to deliver
> a literal no-survivor guarantee: no Python thread can be unconditionally,
> forcibly stopped regardless of what it is blocked inside. The two
> `pg_sleep` worst-case regression tests proved this directly — after
> `__exit__()` returned or raised, the worker thread was still alive, and
> only the tests' own manual `join()` afterward reclaimed it. The tenth pass
> replaced the worker thread with an independently terminable worker
> process, closing the gap for good. See
> [§ Tenth review: an independently terminable worker process](#tenth-review-an-independently-terminable-worker-process-2026-08-04)
> below and
> [PHASE5_VERIFICATION.md § Tenth exit review](PHASE5_VERIFICATION.md#tenth-exit-review-findings-and-corrections-2026-08-04).
> Phase 5 production correctness remained complete throughout; no schema,
> migration, or production-code change was needed or made. Formal
> verification and the Phase 6 correctness entry gate are both closed: the
> tenth pass's PR #13 push-triggered GitHub Actions run
> [`30955234630`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30955234630)
> passed both jobs on `ubuntu-latest`, confirming the redesign cross-platform.
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
> pull request. The integrated `main` workflow subsequently passed in
> [run 30874081442](https://github.com/NemesisGhost/dnd_ai/actions/runs/30874081442),
> a fifth review found two concrete verification-design gaps that a green
> happy-path run did not exercise, a sixth review found the fifth pass's own
> cleanup-helper fix was itself still only best-effort, a seventh review found
> the sixth pass still did not contain startup-timeout and failed-cancellation
> paths, an eighth pass fixed those two findings, a ninth review found that
> fix itself still not completely enough and closed it by establishing
> ownership synchronously and layering a fallback ending in a guarantee
> PostgreSQL itself enforces, and a tenth review found even that could not
> make good on a literal no-survivor guarantee while the worker remained a
> Python thread — closed for good, per this reopening, by replacing the
> thread with an independently terminable worker process.

## Tenth review: an independently terminable worker process (2026-08-04)

The ninth pass correctly established connection/backend ownership
synchronously and gave `_force_stop()` a layered fallback, and its pushed PR
head passed all 1,101 tests in GitHub Actions
[`30948086442`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30948086442).
A closer review of the two worst-case regression tests — the ones using
`pg_sleep` specifically because it defeats the `lock_timeout` backstop —
found they demonstrated the opposite of what they were meant to prove:

1. **The tests joined the worker manually, after the context manager had
   already returned or raised.** `blocked._thread.join(timeout=sleep_seconds)`
   ran as ordinary code *after* the `with` block, not as part of proving
   `__exit__()`'s own guarantee. That is the exact pattern the register
   explicitly prohibits: "no test relies on cleanup after the context as
   evidence of helper correctness."
2. **This was not a test-only gap — it reflected a real architectural
   limit.** No supported mechanism exists to forcibly stop a Python thread
   blocked inside a C-level call (a blocking network read, here). The
   `lock_timeout` backstop the ninth pass relied on only rescues a genuine
   lock wait; nothing in a thread-based design can end a thread blocked
   inside a statement that ignores it.

Acceptance criteria, all test-infrastructure-only (do not change a
production trigger or add a migration unless a separate review finds a
concrete production defect):

- Replace the worker thread with an independently terminable execution
  unit — a subprocess, if a thread-based design cannot guarantee the
  no-survivor contract, rather than weakening the contract.
- Keep an explicit startup handshake so `__enter__()` knows whether the
  worker acquired its connection, transaction, and backend pid before
  returning; terminate and reap the worker before raising on any startup
  failure or timeout.
- Cover every partial-startup resource path explicitly (after connect,
  after transaction begin, after `lock_timeout` is set, after the pid
  lookup) rather than a blanket suppression around cleanup; collect every
  cleanup failure instead of discarding it silently.
- On early context exit, attempt graceful database cleanup first
  (`pg_terminate_backend()`, `pg_cancel_backend()`, driver-native
  cancellation where applicable), then forcibly terminate the worker if
  that does not stop it — a step that must not itself be able to fail.
- Verify through a fresh connection that the backend is actually gone (or
  has no active transaction), not just that the local process object
  reports itself dead.
- Preserve the original test-body exception as primary, with cleanup
  problems attached as notes; when nothing is already propagating, cleanup
  failure must fail the test directly.
- Replace the two worst-case regression tests so they prove containment
  without any join or manual cleanup performed by the test after the
  `with` block.
- Re-run the focused helper tests, all five invariant concurrency tests,
  the complete test suite, migration checks, and final pushed-head CI.

**Fix — no schema or migration change; all changes confined to
`tests/database/test_entity_type_change_protection.py`:**

- The worker's statement now runs in a `multiprocessing.Process` (the
  "spawn" start method on every platform), driven by a new module-level
  `_worker_main()` function — required to be module-level, not a closure or
  method, so `multiprocessing` can pickle a reference to it. A real OS
  process, unlike a Python thread, can always be unconditionally reclaimed
  by its owner via `terminate()`/`kill()`, regardless of what it is doing.
- `__enter__()` performs the startup handshake over a queue: the worker
  connects, begins its transaction, sets `lock_timeout`, and reports its
  real backend pid, or reports a failure (plus every partial-startup
  cleanup problem, collected via a small `_attempt()` helper rather than a
  blanket `contextlib.suppress()`) — all before `__enter__()` returns.
  `backend_pid` remains a private, read-only property, unchanged from the
  ninth pass.
- `_force_stop()`'s fallback chain gained a final, genuinely unconditional
  layer: forcible process termination (which cannot itself fail), followed
  by one more, deliberately non-mockable `pg_terminate_backend()` call.
  That last call turned out to be necessary, not redundant — killing the
  client process does not by itself guarantee PostgreSQL has noticed for a
  statement (`pg_sleep`) that never touches its client socket at all,
  found empirically when an earlier version of the fix left the backend
  visibly present in `pg_stat_activity` for longer than a 5-second poll.
  Driver-native `cancel_safe()` is still in the chain, now relayed through
  a control queue to a watcher thread running *inside* the worker process,
  since the controller no longer holds a live connection object once the
  worker's connection lives in a separate process.
- Six new/parametrized regression tests inject a failure at each
  partial-startup stage (after connect, after transaction begin, after
  `lock_timeout` is set, after the pid lookup, plus a case that makes the
  connection genuinely unusable so cleanup itself fails too) and a
  deterministic slow-startup case (a real, test-controlled delay against a
  shortened handshake timeout), proving `__enter__()` fails predictably
  with no process left alive in every case, without depending on real
  network timing.
- The two worst-case regression tests were rewritten to remove the manual
  post-context join entirely: both now assert `not blocked._process.is_alive()`
  and query a fresh connection immediately after the `with` block —
  independent proof that containment already happened, not part of making
  it happen.
- The five production concurrency tests were mechanically adapted from a
  `Callable[[Connection], None]` statement argument (which cannot cross a
  process boundary as a picklable value) to a plain SQL string plus a
  parameters dict — no change to what any of them prove.

**Results:** 27 tests in `test_entity_type_change_protection.py` (9
sequential, 13 helper regression tests — up from 8 — and 5 hardened
concurrency tests) pass locally against AWS `dev`, confirmed stable across
three repeated runs; the full suite is 1,106 tests (up from 1,101). See the
verification commands and results in
[PHASE5_VERIFICATION.md § Tenth exit review](PHASE5_VERIFICATION.md#tenth-exit-review-findings-and-corrections-2026-08-04).

## Ninth review: synchronous ownership and a deterministic fallback (resolved by tenth pass, 2026-08-04)

The eighth pass correctly closed the two specific gaps the seventh review named — a bounded `connect_timeout` on the worker's connection, and an `is_alive()` check before `__enter__` raises — and its pushed `main` head passed all 1,097 tests in GitHub Actions
[`30940498153`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30940498153).
A closer review of that fix, and of the two regression tests claiming to prove `__exit__`'s cleanup-failure path, found the underlying guarantee was still not what the register requires:

1. **`__enter__()` still raced its own worker's startup rather than owning it.** The connection was opened inside the background thread; `__enter__` polled for a recorded backend pid, then joined with a timeout to find out whether startup had succeeded. A shorter `connect_timeout` makes the race narrower, but it is still a race — two independent things (the thread's own progress, and `__enter__`'s poll/join) resolving against each other, not one thing established before the other exists by construction.
2. **`_force_stop()` had no fallback beyond reporting failure.** If both `pg_terminate_backend()` and `pg_cancel_backend()` failed, nothing else the helper controlled could reach the worker. Faithfully reporting that dead end is necessary but is not the deterministic recovery the register asks for.
3. **The two termination-failure regression tests corrupted the tracked backend pid to force that failure**, rather than injecting a failure into the signaling mechanism itself. That proves "the helper honestly reports a failure when a caller lies about which backend it owns" — a real property, but not "PostgreSQL's own signals genuinely failed against the correct backend and the helper still stopped it," which is what the register's acceptance criteria actually ask for. `backend_pid` being a mutable, publicly writable list made this loophole possible in the first place.

Acceptance criteria, all test-infrastructure-only (do not add or modify a migration or production trigger unless a separate review finds a concrete production defect):

- Establish connection/backend ownership synchronously, before a worker thread is ever created — not by racing a poll/join against the thread's own progress.
- Keep the backend pid and owned connection private and immutable from callers; inject failures into the signaling operations themselves for fault-injection tests, not into tracked identity.
- Implement a deterministic fallback grounded in a resource the helper genuinely owns for when PostgreSQL's termination/cancellation signals fail, not just failure reporting.
- Prove that fallback with tests that inject failure into the signaling operations (a false result, and a raised exception, for each signal) rather than corrupting identity.
- Prove the true worst case — nothing active can stop the worker — still reports the cleanup failure correctly and preserves an already-propagating original exception, without the test using manual post-context cleanup as the thing being proven.
- Put every regression test's safety-net cleanup in `finally`; carry forward the eighth pass's fix rather than regressing it.
- Re-run the focused helper tests, all five invariant concurrency tests, the complete test suite, migration checks, and final pushed-head CI.

**Fix — no schema or migration change; all changes confined to
`tests/database/test_entity_type_change_protection.py`:**

- `_BackgroundStatement._establish_connection()` (new, isolated method) now connects through the private, single-use, `connect_timeout`-bounded engine, begins the transaction, sets `SET LOCAL lock_timeout` on it, and reads the real backend pid — synchronously, in the calling thread, inside `__enter__()`, before the worker thread is constructed at all. A failure raises directly with no thread ever created; ownership and the worker's existence no longer race each other.
- `backend_pid` is now private (`self._backend_pid_value`) with a read-only public property — no caller can overwrite it.
- `_force_stop()` gained two more fallback layers beyond the existing SQL signals (now issued through an isolated, mockable `_send_signal()` seam): `_cancel_via_driver()`, using psycopg's `Connection.cancel_safe()` directly on the worker's own connection handle (confirmed empirically to interrupt a genuinely blocked worker from another thread within 0.24s); and the `lock_timeout` set during startup, a bound PostgreSQL itself enforces regardless of anything this thread does or fails to do (confirmed empirically: an unsignaled worker with `lock_timeout = '2s'` still failed with `LockNotAvailable` after 2.04s).
- Six regression tests replace the three that corrupted `backend_pid`: the original real-signal-succeeds case; a parametrized case proving the fallback to `cancel_safe()` when both SQL signals are mocked to fail (as a false result, and by raising); a case proving the fallback to the `lock_timeout` backstop when every active mechanism is mocked to fail; and two cases — with and without an original exception propagating — using `pg_sleep` (not lock-bound, so even the backstop cannot rescue it) with every active mechanism mocked to fail, proving `_force_stop()`'s reporting path still works in the genuine worst case and the worker still terminates once its own fixed duration naturally elapses.
- The refused-port startup test is replaced by a deterministic mocked slow-then-failing `_establish_connection()`, proving `__enter__()` raises within a bounded interval with no thread ever created, plus a second test keeping a real (unmocked) connection failure to confirm the same structural guarantee against a genuine driver error.

**Results:** 22 tests in `test_entity_type_change_protection.py` (9 sequential, 8 helper regression tests, 5 hardened concurrency tests) pass locally against AWS `dev`, confirmed stable across three repeated runs; the full suite is 1,101 tests (up from 1,097). See the verification commands and results in
[PHASE5_VERIFICATION.md § Ninth exit review](PHASE5_VERIFICATION.md#ninth-exit-review-findings-and-corrections-2026-08-04).

## Seventh review: startup and failed-cancellation containment (resolved by eighth pass, 2026-08-04)

The sixth pass correctly improved successful forced cleanup, failure reporting,
connection invalidation, and liveness checks, and its pushed `main` head passed
all 1,096 tests in GitHub Actions
[`30924888684`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30924888684).
That green run does not exercise two exit paths strongly enough to establish
the register's universal teardown requirement:

1. **Startup timeout can outlive `__enter__`.** Connection acquisition runs in
   the background thread. When the startup deadline expires, `__enter__`
   performs another bounded join but does not verify that the thread stopped
   before raising. A slow or stuck connection attempt can therefore remain
   alive after context entry has failed.
2. **Failed termination and cancellation can outlive `__exit__`.** When both
   PostgreSQL signals fail, `_force_stop()` reports the failure but cannot stop
   the worker. `__exit__` then raises the cleanup failure or attaches it to the
   original exception while the worker remains alive.
3. **The fault-injection tests confirm, rather than contain, that survivor.**
   Both tests manually terminate the real backend and join the worker only
   after `_BackgroundStatement.__exit__()` has finished. That safety-net work
   is not in `finally`; an earlier assertion failure can bypass it.

The remaining acceptance criteria are test-infrastructure-only:

- Establish connection/backend ownership before starting a worker whose
  lifetime can escape the context, or use a cancellation design that can
  always contain startup failure within a bounded interval.
- Do not leave a live worker after failed `pg_terminate_backend()` and
  `pg_cancel_backend()` attempts. If a Python thread cannot be forcibly
  stopped safely, redesign ownership so releasing the context's controlled
  resource deterministically unblocks it, then verify the worker stopped.
- Preserve the original test failure while also reporting cleanup failure.
- Put every regression test's safety-net backend/thread cleanup in `finally`,
  and prove no thread, transaction, connection, or advisory lock survives.
- Re-run the focused helper tests, all five invariant concurrency tests, the
  complete 1,096-plus-test suite, migration checks, and final pushed-head CI.

Do not add a migration or alter revision 056 unless a separate review finds a
concrete production defect.

## Sixth review: attempted guaranteed worker teardown (2026-08-04)

The fifth pass's `_BackgroundStatement.__exit__()` attempted to terminate a
still-alive backend but did not guarantee the outcome: termination was skipped
entirely when no backend PID had been recorded, errors from the termination
connection and a false `pg_terminate_backend()` result were both suppressed,
and the final bounded `join()` was not followed by a check that the thread had
actually stopped. No test exercised that forced-cleanup path at all.

**Fix — no schema or migration change; all changes confined to
`tests/database/test_entity_type_change_protection.py`:**

- `__enter__` now blocks until the worker's connection is established and its
  backend PID recorded (or the thread has already failed) before returning
  control to the caller, and raises — after joining the thread, so nothing is
  left running — if that startup does not complete within a bounded deadline.
  A `with` block can therefore never begin with a worker of unowned state.
- `__exit__` signals a still-alive worker's backend to stop via
  `pg_terminate_backend()`, checking its boolean result rather than assuming
  success, falling back to `pg_cancel_backend()` if termination was not
  confirmed; each attempt is followed by a bounded join that verifies the
  thread actually stopped, not just that a signal was sent. A final,
  independent liveness check backstops both attempts.
- Cleanup failures are never silently discarded. If an exception was already
  propagating out of the `with` block, the cleanup failure is attached to it
  via `add_note()` so the original failure remains the reported cause; if
  nothing was already propagating, the cleanup failure is raised directly and
  becomes the `with` block's own failure — there is no path that returns
  cleanly while a worker, connection, transaction, or advisory lock survives.
- The worker's own connection is invalidated (not merely closed) whenever its
  statement raises, since some server-side disconnect conditions — notably
  `psycopg.errors.AdminShutdown`, which `pg_terminate_backend()` itself
  raises on its target — are not recognized by SQLAlchemy's own disconnect
  detection; relying on a plain `close()` risked silently returning a dead
  connection to the shared pool for a later, unrelated test to draw.

**Tests:** three new regression tests exercise the helper in isolation from
any production trigger, using a plain `pg_advisory_xact_lock` as the
contended resource rather than the real dungeon/entity-type locks (so no
production code needs to be deliberately broken to exercise cleanup):

1. A genuinely blocked worker, cleaned up when the `with` block exits early
   via a synthetic failure — proves the forced-termination path actually
   terminates the worker's backend (checked from an independent connection,
   not the lock holder itself — see the note below) and that the synthetic
   failure is still what propagates.
2. The same scenario with the worker's tracked backend PID deliberately
   corrupted after it has genuinely connected and blocked, so both
   `pg_terminate_backend()` and `pg_cancel_backend()` target a backend that
   does not exist and are guaranteed to report failure — a real `false`
   result from PostgreSQL, not a mock. Proves the cleanup failure is reported
   via `add_note()` on the propagated exception rather than swallowed, and
   that the original synthetic failure is still what a caller sees.
3. The same fault injection, but the `with` block exits normally with no
   exception of its own — proves `__exit__` raises the cleanup failure
   directly, since there is nothing already propagating for it to attach to.

Writing test 1 surfaced a real PostgreSQL nuance, not a defect in the helper:
a connection that holds an advisory lock retains a stale view of a terminated
*waiter's* row in `pg_stat_activity` until it releases its own lock, even
though a fresh, independent connection sees the waiter as fully gone almost
immediately. The test verifies via a fresh connection, matching the
independent-connection verification pattern the fifth pass already
established for production final-state assertions. Writing tests 2 and 3 also
surfaced a genuine race in the tests' own teardown — a safety-net termination
of the real (uncorrupted) worker backend, issued after releasing the lock it
was blocked on, could land exactly as that worker was finishing and closing
its connection normally, corrupting a connection the pool would then hand out
as healthy to a later test. Both tests now terminate the real worker
deterministically, before releasing the lock it is still guaranteed to be
blocked on.

**Results:** all 17 tests in `test_entity_type_change_protection.py` (9
sequential, 3 new helper regression tests, 5 hardened concurrency tests) pass
locally against AWS `dev`, confirmed stable across repeated runs. See the
verification commands and results in
[PHASE5_VERIFICATION.md § Sixth exit review corrections](PHASE5_VERIFICATION.md#sixth-exit-review-corrections-2026-08-04).

## At a glance (all blockers resolved)

Phase 5's documented gameplay capabilities were implemented, merged, and
verified. All production, concurrency-verification, and test-infrastructure
blockers are closed:

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
3. **Test-infrastructure blocker:** the fifth-pass helper attempted to
   terminate a blocked backend during cleanup, but did not prove termination
   succeeded or that the worker stopped, and the forced-cleanup path was
   untested. The sixth pass added explicit checks and focused regression tests;
   the seventh review found startup-timeout and failed-cancellation paths could
   still leave a worker alive; the eighth pass bounded connection acquisition
   and added an `is_alive()` check; a ninth review found ownership was still
   established by racing a poll/join against the worker thread rather than
   synchronously, and that the only fallback for failed PostgreSQL signals
   was to report the failure rather than actually stop the worker, which the
   ninth pass fixed with synchronous ownership and a layered fallback; a
   tenth review then found that even that fallback could not deliver a
   literal no-survivor guarantee, because no Python thread can be
   unconditionally, forcibly stopped. **Resolved** by the tenth pass: the
   worker now runs in an independently terminable OS process
   (`multiprocessing.Process`), reclaimable via `terminate()`/`kill()`
   regardless of what it is doing, with `_force_stop()`'s fallback chain
   ending in forcible process termination followed by one more, unconditional
   `pg_terminate_backend()` call. Confirmed by PR #13's push-triggered CI run
   [`30955234630`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30955234630),
   which passed both jobs on `ubuntu-latest`. See
   [PHASE5_VERIFICATION.md § Tenth exit review](PHASE5_VERIFICATION.md#tenth-exit-review-findings-and-corrections-2026-08-04).

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

## Fourth-review completion gate (production portion satisfied by revision 056)

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
without a pull request. GitHub Actions nevertheless verified the integrated
`main` head in [run 30874081442](https://github.com/NemesisGhost/dnd_ai/actions/runs/30874081442),
including all 1,093 tests. A fifth review re-checked the five resumed-waiter tests against the
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

**Fifth-pass response:** no schema or migration change — revision 056 and the revision-053
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
  free-function-plus-tuple helper. Its `__exit__` makes a best-effort attempt
  to terminate the background backend when the thread remains alive, then
  performs a bounded join. This is an improvement over abandoning the thread,
  but it is not the required teardown guarantee: missing PIDs, suppressed
  termination failures, and an unchecked final join can still allow a worker
  to outlive the `with` block. The sixth review above rewrote the same class
  to close every one of those gaps and added the missing focused regression
  tests.
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
The fifth-pass PR also passed runs
[`30878624056`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30878624056)
and
[`30878927585`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30878927585)
at its final reviewed head. Those happy-path runs confirm the production and
final-state behavior; the sixth review's own forced-cleanup regression tests
and its final CI run (recorded above) are what exercise the forced-cleanup
path itself.

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
