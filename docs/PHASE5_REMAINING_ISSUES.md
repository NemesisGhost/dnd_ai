# Phase 5 Remaining Issues

> **Formal closeout complete, pending this PR's own final-head CI
> confirmation (2026-08-05).** A twelfth review of merged PR #14 found the
> eleventh pass's own `scripts/verify.sh --help` claim did not hold up to its
> actual exit code, the worker outcome protocol still let a naturally exited
> worker with an empty outcome channel pass as success, `_worker_main`'s
> cleanup was not itself independently failure-safe, and the IPC redesign
> still relied on an abandonable wrapper thread to bound
> `multiprocessing.Queue`'s own unbounded `join_thread()` — the exact class
> of bug the eleventh pass's IPC-closing fix was meant to eliminate. The
> twelfth pass fixed the verification tooling first, made the worker outcome
> protocol total, made `_worker_main`'s cleanup independently failure-safe,
> and replaced the queue-based IPC with `multiprocessing.Pipe`, removing the
> abandonable-thread class of bug by construction — but a thirteenth review of
> that same open PR (commit `d0032dc`) then found the twelfth pass's own
> outcome-protocol, backend-verification, and process-ownership fixes were
> themselves still incomplete: a worker merely being *alive* when `__exit__`
> began was still treated as proof of forced termination regardless of how
> containment was actually achieved, backend verification ran only on the
> forced-stop path, a `Process.start()` failure was assumed to always mean
> nothing was spawned, and startup-cleanup failures on the redundant
> controller-side pipe copies were silently discarded once the handshake
> succeeded. A thirteenth pass fixed all four. See [§ Thirteenth review:
> accurate missing-outcome classification, universal backend verification, and
> Process.start() failure
> ownership](#thirteenth-review-accurate-missing-outcome-classification-universal-backend-verification-and-processstart-failure-ownership-2026-08-05)
> below and
> [PHASE5_VERIFICATION.md § Thirteenth exit
> review](PHASE5_VERIFICATION.md#thirteenth-exit-review-accurate-missing-outcome-classification-universal-backend-verification-and-processstart-failure-ownership-2026-08-05).
> A fourteenth review of that same open PR's follow-up commit (`267ac1d`) then
> found the thirteenth pass's own fixes were themselves still incomplete:
> `_force_stop()` still classified containment as forced from mere
> post-attempt absence of liveness, not positive evidence the controller's own
> call caused it; several `join()`/`is_alive()` calls throughout the cleanup
> paths were unguarded and could themselves replace an already-propagating
> exception; and the redesigned independent safety net never closed the
> `Process` object or any IPC endpoint and suppressed every failure it found
> instead of reporting it. A fourteenth pass fixed all three. See [§
> Fourteenth review: evidence-based containment classification, fully guarded
> cleanup, and a complete independent safety
> net](#fourteenth-review-evidence-based-containment-classification-fully-guarded-cleanup-and-a-complete-independent-safety-net-2026-08-05)
> below and
> [PHASE5_VERIFICATION.md § Fourteenth exit
> review](PHASE5_VERIFICATION.md#fourteenth-exit-review-evidence-based-containment-classification-fully-guarded-cleanup-and-a-complete-independent-safety-net-2026-08-05).
> Phase 5 production correctness and the five-invariant concurrency suite
> remain complete throughout; no schema, migration, or production-code change
> was needed or made. Formal verification is complete and locally verified
> (93 tests in `test_entity_type_change_protection.py`, 1,189 in the full
> suite); the Phase 6 correctness entry gate remains blocked until [PR
> #15](https://github.com/NemesisGhost/dnd_ai/pull/15)'s own final-head CI run
> — the actual final pushed head, not an earlier implementation commit —
> confirms. See [PHASE5_VERIFICATION.md § Current formal-closeout
> status](PHASE5_VERIFICATION.md#current-formal-closeout-status).
>
> **Previously closed (2026-08-04), reopened above.** An eleventh review of
> the tenth pass's merged commit found the redesigned worker process could
> still report false success and silently discard cleanup failures:
> `_worker_main` marked an outcome `"committed"` before `connection.commit()`
> was ever attempted, a commit failure only reached `problems` (which was
> only ever surfaced when the status was already `"failed"`), and `__exit__`
> never drained an outcome nobody explicitly consumed via
> `resume_and_get_outcome()`. A controller-side verification error could also
> replace an already-propagating exception outright, and process/IPC
> lifecycle gaps (unhandled `Process()`/`start()` failure, a bare `assert`
> instead of a collected problem, unclosed queues and `Process` object)
> remained. The eleventh pass fixed the worker outcome protocol, made every
> controller-side cleanup path failure-safe, and completed process/IPC
> cleanup — see
> [§ Eleventh review: worker outcome protocol, controller cleanup, and
> process/IPC hardening](#eleventh-review-worker-outcome-protocol-controller-cleanup-and-processipc-hardening-2026-08-04)
> below and
> [PHASE5_VERIFICATION.md § Eleventh exit review](PHASE5_VERIFICATION.md#eleventh-exit-review-worker-outcome-protocol-controller-cleanup-and-processipc-hardening-2026-08-04).
> This review also found the token-reduction verification tooling
> (`scripts/verify.sh`) was committed non-executable, breaking its own
> documented entry point — fixed first, then used for the remainder of this
> pass. Its own final documentation-closing commit `e173c21` was
> independently confirmed by run
> [`30966346368`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30966346368)
> — the eleventh pass's own text below cites `30964183959`, which tested
> implementation commit `8c3a2cd` immediately before it; that distinction is
> preserved here as the historical record, corrected going forward by the
> twelfth pass's own citations.
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
> Python thread, closed by replacing the thread with an independently
> terminable worker process; and an eleventh review found that process-based
> redesign could still report false success and silently discard cleanup
> failures, closed by this reopening's worker-outcome and controller-cleanup
> hardening.

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

## Eleventh review: worker outcome protocol, controller cleanup, and process/IPC hardening (2026-08-04)

The tenth pass correctly replaced the worker thread with an independently
terminable process, and its pushed PR head passed all 1,106 tests in GitHub
Actions
[`30955234630`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30955234630).
Review of the merged commit
(`4ef78375d7dbf2c57341c12d4b8c5dd92572d00b`) — after first fixing the
token-reduction tooling's own broken executable-bit entry point, per this
pass's explicit instruction to repair and use that tooling before touching
the helper itself — found the redesigned worker could still report false
success and silently discard cleanup failures:

1. **A commit failure could still be reported as `"committed"`.**
   `_worker_main` set its outcome tuple to `("committed", None)` immediately
   after the statement succeeded, before `connection.commit()` was ever
   attempted. A commit failure only appended to `problems`, which
   `resume_and_get_outcome()` only turned into a note when the status was
   *already* `"failed"` — so a commit, close, or dispose failure after an
   otherwise-successful statement was silently absorbed into an apparently
   successful outcome.
2. **An outcome nobody explicitly consumed could be lost.** `__exit__` only
   ran `_force_stop()` when the process was still alive; a worker that
   finished before the `with` block exited, without the caller ever calling
   `resume_and_get_outcome()`, left its outcome sitting unread forever.
3. **A verification error could replace an already-propagating exception.**
   `_verify_backend_gone()`'s per-poll connection let a connection or query
   failure propagate straight out of `_force_stop()`/`__exit__` uncaught,
   silently replacing whatever exception the `with` block's body had already
   raised.
4. **The regression tests never exercised the final termination call or
   backend verification themselves failing** — every prior pass's
   fault-injection tests left both operational.
5. **Process/IPC lifecycle gaps:** `Process()` construction and
   `process.start()` failures were unhandled; the final "process survived
   forcible termination" case raised a bare `assert` (the same
   replace-an-already-propagating-exception risk as finding 3) instead of a
   collected problem; IPC queues and the `Process` object itself were never
   explicitly closed.

Acceptance criteria, all test-infrastructure-only (do not change a
production trigger or add a migration unless a separate review finds a
concrete production defect):

- `"committed"` is emitted only once the statement, its commit, and every
  other cleanup step (rollback-after-commit-failure, close, dispose) have
  all succeeded; a cleanup-only failure after a genuine commit still fails
  the caller.
- `__exit__` always drains and processes any outcome nobody explicitly
  consumed, so it can never be silently lost.
- No controller-side verification or signaling error can replace an
  already-propagating exception; every controller-side connection is closed
  through a failure-safe construct regardless of what the operation itself
  did.
- `Process()`/`process.start()` failures are handled without ever treating
  a never-started process as a live resource; every escalation step
  (terminate → kill) is followed by a bounded join, and a genuine survival
  is reported as a collected problem, never a bare `assert`.
- Every IPC queue and the `Process` object itself are explicitly closed,
  bounding `Queue.join_thread()` (which has no timeout of its own).
- New regression tests inject failure into the final termination call and
  backend verification themselves, not only the earlier graceful paths, and
  into process construction/start/escalation and IPC/process-object close.
- The five production concurrency-invariant tests are preserved unweakened.
- Re-run the focused helper tests, all five invariant concurrency tests, the
  complete test suite, migration checks, and final pushed-head CI.

**Fix — no schema or migration change; all changes confined to
`tests/database/test_entity_type_change_protection.py`, plus fixing
`scripts/verify.sh`'s and `scripts/aws-db-allow-my-ip.sh`'s tracked file
mode:**

- `_worker_main` now tracks `statement_error` and `commit_error`
  separately; `commit()` only runs after a successful statement, and
  `"committed"` is reported only if the statement succeeded, the commit
  succeeded, and no other cleanup step reported a problem. A shared
  `_build_outcome_exception()` is used by both `resume_and_get_outcome()`
  and a new `_drain_unread_outcome()` (called unconditionally from
  `__exit__`), so nothing consumed by neither is ever lost.
- A new `_with_isolated_connection()` helper guarantees every controller
  connection closes regardless of what the operation did, without a close
  failure replacing the operation's own error. `_verify_backend_gone()` was
  rewritten around it to classify gone / present-idle / present-active via
  `pg_stat_activity.state`/`xact_start`, and to never itself raise.
- `__enter__` wraps `Process()` construction and `process.start()` in their
  own failure-safe handling, leaving `self._process` `None` on either
  failure. `_force_stop`'s bare `assert` became a collected problem.
  `_reap()` and `__exit__` both close every IPC queue (bounding
  `Queue.join_thread()` via a short-lived wrapper thread) and the `Process`
  object once confirmed not-alive — which required a new
  `worker_confirmed_stopped` property, since `Process.is_alive()` raises
  once the object is closed, breaking every test's established
  `assert not blocked._process.is_alive()` post-`__exit__` idiom.
- Eleven new regression tests (twelve collected items, since one is
  parametrized over two stages) cover: a bare statement failure; commit
  failure after a successful statement (the follow-on `rollback()` turned
  out to be a safe no-op once `commit()` already failed against a closed
  connection — the same SQLAlchemy bookkeeping behavior the tenth pass found
  for the pre-`begin()` case); a cleanup-only failure (`close`/`dispose`,
  parametrized) after a successful commit; an outcome drained by `__exit__`
  that nobody consumed; the final termination call itself failing; backend
  verification itself failing; `Process()` construction failure;
  `process.start()` failure; `terminate()` not stopping the process with
  `kill()` escalating; and a queue/Process-object close failure. Writing the
  queue-close test surfaced one more bug: `_close_queues` was unconditionally
  attempting `Queue.join_thread()` even when `Queue.close()` had already
  failed, violating `join_thread()`'s own precondition and leaking an
  unhandled-thread-exception warning instead of a reported problem — fixed
  by skipping `join_thread()` when `close()` failed and relaying an
  exception raised inside the bounded-wait wrapper thread back to the
  caller.
- **Tooling defect, found and fixed first:** `scripts/verify.sh` was
  committed as `100644`; `core.filemode=false` in this repository means a
  local `chmod +x` never propagates into the tracked git mode, so the
  documented `scripts/verify.sh <mode>` form failed with `Permission
  denied` on a fresh checkout. `scripts/aws-db-allow-my-ip.sh` — invoked
  directly by `verify.sh`'s AWS-touching modes and documented as a bare
  command in `docs/DEVELOPMENT.md` §3 — had the identical defect. Both fixed
  via `git update-index --chmod=+x`; both confirmed via a genuinely fresh
  clone. `scripts/verify.sh` was then used for every quality check for the
  remainder of this pass.

**Results:** 39 tests in `test_entity_type_change_protection.py` (9
sequential, 25 helper regression tests — up from 13 — and 5 unweakened
concurrency tests) pass locally against AWS `dev`, confirmed stable across
three repeated runs; the full suite is 1,118 tests (up from 1,106). See the
verification commands and results in
[PHASE5_VERIFICATION.md § Eleventh exit review](PHASE5_VERIFICATION.md#eleventh-exit-review-worker-outcome-protocol-controller-cleanup-and-processipc-hardening-2026-08-04).

## Twelfth review: verification-tooling correctness, worker outcome protocol totality, and Pipe-based IPC (2026-08-04)

The eleventh pass correctly redesigned the worker outcome protocol and made
controller-side cleanup failure-safe, and — once its own documentation-closing
commit `e173c21` is used as the final head rather than the earlier
implementation commit `8c3a2cd` — its pushed PR head passed all 1,118 tests in
GitHub Actions
[`30966346368`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30966346368).
Review of merged commit `7ec0945` found the eleventh pass's own tooling claim
did not hold up to its exit code, the worker outcome protocol it had just
redesigned still had a gap, `_worker_main`'s own cleanup was not itself
failure-safe, and the IPC redesign it added to close a Queue-cleanup gap in
the tenth pass still relied on the same class of abandonable-thread bug:

1. **`scripts/verify.sh --help`/`-h` did not exit 0 when given as the first
   argument.** The eleventh pass's fix (restoring the tracked executable bit)
   was real and necessary, and its own verification correctly proved the
   permission error was gone — but `--help`/`-h` handling only ran inside the
   trailing-argument loop, after `MODE="$1"` had already consumed the flag
   itself, so `scripts/verify.sh --help` alone fell through to the
   invalid-mode case and exited 2, not 0. Nothing in the eleventh pass's
   verification table checked the exit code, only that the command ran
   without `Permission denied`.
2. **Ingress-revocation failure was silently swallowed.**
   `scripts/aws-db-allow-my-ip.sh close >/dev/null 2>&1 || true` discarded
   both the failure and its output; an otherwise fully successful
   AWS-touching run would still print `All requested stages passed.` even if
   the security-group rule it had opened was never actually closed.
3. **The worker outcome protocol was not total.** `_drain_unread_outcome()`
   returned `None` in three structurally different situations — the outcome
   was already consumed, the worker was deliberately terminated before it
   could produce one, or the worker exited on its own having never published
   one at all — and `__exit__` treated all three identically as "nothing to
   report." Only the second is a legitimate no-outcome case; the third is a
   worker that silently failed its one mandatory duty, previously
   indistinguishable from success — the exact bug this register's acceptance
   criteria have named since the ninth review as the thing a genuinely
   airtight design must not allow.
4. **`_worker_main`'s cleanup `finally` block began with an unprotected
   `control_queue.put(None)`.** A failure signaling the watcher to stop would
   skip joining it, closing the connection, disposing the engine, and
   publishing the outcome.
5. **`_bounded_join_thread()` wrapped an abandonable resource in another
   abandonable resource.** `multiprocessing.Queue.join_thread()` has no
   timeout of its own, so the eleventh pass wrapped it in a daemon thread to
   add one — but when that wrapper's own deadline expired, the wrapper thread
   itself remained alive, reproduced directly during this review.
6. **Partial IPC construction was unhandled.** A failure constructing the
   second or third of the three `ctx.Queue()` calls in `__enter__` would leak
   whichever queue(s) had already been created, with no cleanup attempt and no
   `self` attribute even set to find them by.

Acceptance criteria, all test-infrastructure-only (do not change a
production trigger or add a migration unless a separate review finds a
concrete production defect):

- `scripts/verify.sh --help`/`-h` exits 0 when given as the first argument;
  invalid modes/arguments still exit 2.
- Ingress-revocation failure is never swallowed: it fails an otherwise
  successful run, and is visibly reported (without overriding) alongside an
  already-failed stage. `All requested stages passed.` is printed only when
  every requested check and required cleanup operation succeeded. Deterministic
  automated tests cover this without contacting AWS.
- A normally exited worker must produce exactly one outcome; a worker that
  exits without one is a reported protocol failure, never silent success. A
  duplicate outcome is also a reported protocol failure. The one accepted
  no-outcome case is deliberate controller-side termination before outcome
  production, recorded explicitly as such.
- `_worker_main`'s cleanup steps (signaling the watcher, joining it, closing,
  disposing, publishing the outcome) are attempted independently; a watcher
  still alive after its bounded join is itself a reported cleanup problem.
- No IPC design solves bounded cleanup by creating another thread that
  cannot itself be terminated. Partial IPC construction closes whatever
  already exists and reports every cleanup failure.
- Every helper regression test has independent, bounded, `finally`-scoped
  containment; the five production-invariant concurrency tests are preserved
  unweakened.
- Re-run the focused helper tests, all five invariant concurrency tests, the
  complete test suite, migration checks, and final pushed-head CI — the actual
  final head, not an earlier implementation commit a later documentation
  commit supersedes.

**Fix — confined to `scripts/verify.sh`, a new `tests/unit/test_verify_sh.py`,
and `tests/database/test_entity_type_change_protection.py`:**

- `scripts/verify.sh`: `--help`/`-h` checked as the first argument before
  `MODE` is assigned; `close_ingress()` returns success/failure explicitly (no
  `|| true`); `cleanup()`, invoked via `trap 'cleanup "$?"' EXIT`, always
  attempts revocation, preserves an already-failed stage's exit code as
  primary while visibly reporting an additional revocation failure, and fails
  an otherwise-successful run if revocation alone fails. Seventeen new
  deterministic tests exercise this against a stubbed `uv` and a stubbed
  ingress script, including a parametrized test proving every documented
  invocation behaves exactly as written.
- A new `outcome_protocol_state` attribute and `_finalize_worker_outcome()`
  method (replacing `_drain_unread_outcome()`) distinguish `"consumed"`,
  `"unread"`, `"missing-after-forced-termination"` (the one legitimate case),
  and `"missing-after-natural-exit"` (now a reported protocol failure). A
  second outcome appearing after the first is also reported, regardless of
  whether the first was consumed or drained here.
- `_worker_main`'s `finally` block now attempts signaling the watcher to stop,
  joining it, closing, and disposing as independent steps; a watcher still
  alive after its own bounded join is recorded as a cleanup problem. Outcome
  publication's own failure is detected by the controller's now-total
  protocol instead of being made failure-safe at the source, since there is no
  second channel to report a first-channel failure through.
- IPC redesigned around `multiprocessing.Pipe(duplex=False)`: three one-way
  pipes replace the three queues; `Connection.close()` has no background
  feeder thread at all, removing finding 5's bug class by construction. The
  worker's own watcher-thread stop signal moved off IPC entirely onto a local
  `threading.Event`, since that signal was always same-process. `__enter__`
  constructs all three pipes inside one try/except, closing whichever
  already-created pipe(s) exist if a later one fails; parametrized tests cover
  both the second and third pipe failing. A genuine cross-platform bug
  surfaced proving this on Windows: `PipeConnection.poll()` raises
  `BrokenPipeError` once its peer has closed, rather than deferring to
  `recv()` raising `EOFError` the way POSIX does — both are now guarded
  against `(EOFError, OSError)`.
- The six tests that call `__enter__()` directly (bypassing the `with`
  statement's own `__exit__` guarantee) gained a `finally`-scoped safety net
  reaping a still-alive worker if `__enter__` ever unexpectedly fails to
  raise. The five production concurrency-invariant tests and the `with`-block-
  based helper tests were reviewed and left unmodified — their existing
  guarantees (Python's `with` statement, and SQLAlchemy's
  `Connection.close()` rolling back an in-progress transaction) already make
  them failure-safe.
- Nine new regression tests (eight new functions, one parametrized over two
  cases) cover: natural exit without an outcome; a duplicate outcome; the
  happy-path `"consumed"` state; forced termination recording
  `"missing-after-forced-termination"` with no spurious protocol noise; a
  failure signaling the watcher to stop; a watcher that ignores its stop
  signal; partial IPC construction failure on the second and third pipe; and
  the absence of any `QueueFeederThread` after a normal run.

**Results:** 48 tests in `test_entity_type_change_protection.py` (9
sequential, 34 helper regression tests — up from 25 — and 5 unweakened
concurrency tests) pass locally against AWS `dev`, confirmed stable across
three repeated runs. 17 new tests in `tests/unit/test_verify_sh.py`. The full
suite is 1,144 tests (up from 1,118). See the verification commands and
results in
[PHASE5_VERIFICATION.md § Twelfth exit review](PHASE5_VERIFICATION.md#twelfth-exit-review-verification-tooling-correctness-worker-outcome-protocol-totality-and-pipe-based-ipc-2026-08-04).

## Thirteenth review: accurate missing-outcome classification, universal backend verification, and Process.start() failure ownership (2026-08-05)

The twelfth pass correctly fixed the verification tooling, made the worker
outcome protocol total, made `_worker_main`'s cleanup independently
failure-safe, and replaced the queue-based IPC with `multiprocessing.Pipe`,
and its pushed PR head (commit `f3ed98a`) passed all 1,144 tests in GitHub
Actions
[`30972855981`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30972855981).
Review of the same open PR's follow-up commit (`d0032dc`, which closed the
register on top of `f3ed98a` without its own CI run being checked first)
found the twelfth pass's own outcome-protocol, backend-verification, and
process-ownership fixes were themselves still incomplete:

1. **The missing-outcome classification was not accurate.** `__exit__()` set
   `worker_was_forcibly_stopped = True` whenever the process was merely
   *alive* when cleanup began — not whenever this controller's own
   `terminate()`/`kill()` was what actually ended it. A gracefully stopped
   worker (via `pg_terminate_backend()`, `pg_cancel_backend()`, driver
   cancellation, or the `lock_timeout` backstop) still reaches its own
   outcome-publication step before exiting; if that publish then failed, the
   missing outcome was wrongly accepted as the legitimate forced-termination
   exemption instead of reported as a protocol failure.
2. **Backend verification ran only on the forced-stop path.** A worker that
   exited naturally skipped fresh-connection backend verification entirely,
   relying on the Python process having exited as an unverified proxy for
   PostgreSQL itself having noticed.
3. **A `Process.start()` failure was not always "nothing was spawned."**
   `__enter__` never stored the constructed `Process` object until after
   `start()` had already succeeded, on the assumption a raised `start()`
   always meant no OS process existed — not a general guarantee: `start()`
   can fail after partial (or full) initialization, and the code never
   stored or closed the `Process` object in that case regardless.
4. **Startup-cleanup failures on the redundant controller-side pipe copies
   were silently discarded** once the handshake succeeded, since the local
   list collecting them was used only by the handshake-failure/timeout raise
   paths.

Acceptance criteria, all test-infrastructure-only (do not change a
production trigger or add a migration unless a separate review finds a
concrete production defect):

- `worker_was_forcibly_stopped` is derived from which mechanism actually
  ended the process (`_force_stop`'s own classification), never from whether
  the process merely happened to be alive when `__exit__` began.
- Backend verification runs exactly once on every `__exit__()` path — the
  forced-stop path's own internal verification, or an explicit call on the
  natural-completion path — never zero times and never twice.
- Ownership of the constructed `Process` object begins at construction;
  every `start()` failure is classified (never-started vs. partially
  started) via `pid`/`is_alive()` rather than assumed, and cleaned up
  accordingly.
- No startup-cleanup problem is silently discarded once `__enter__` returns
  successfully; it is retained and reported by `__exit__`.
- Every regression test's safety net operates independently of
  `_BackgroundStatement.__exit__()`/`_force_stop()` — the implementation
  many of these tests exercise — rather than relying on it.
- Re-run the focused helper tests, all five invariant concurrency tests, the
  complete test suite, migration checks, and the actual final pushed-head CI.

**Fix — no schema or migration change; all changes confined to
`tests/database/test_entity_type_change_protection.py`:**

- `_force_stop()` now returns `(problems, containment_reason)`, one of
  `"graceful"`, `"forced"`, or `"survived"`; `__exit__()` derives
  `worker_was_forcibly_stopped` from that reason. A new regression test
  blocks a worker on a genuine advisory lock, lets the real, unmocked
  `pg_terminate_backend()` gracefully end it, and proves a subsequent
  missing outcome (via `outcome_publish_fails`) is still reported as
  `"missing-after-natural-exit"`, not misclassified as forced termination.
- `__exit__()` now calls `_verify_backend_gone()` directly on the
  natural-completion path (previously skipped entirely), while the
  forced-stop path's own internal call is unchanged — exactly one
  verification per `__exit__()` call. Two new regression tests mock
  verification to fail for a worker that completes entirely on its own, one
  with no original exception and one with the body raising first, proving
  both the raise-directly and attach-as-note branches now also cover natural
  completion.
- `self._process` is assigned immediately after `Process()` construction
  succeeds, before `start()` is called. A new
  `_cleanup_process_after_start_failure()` classifies what a raised
  `start()` left behind via `pid`/`is_alive()` (both safe to call
  regardless of whether the process ever started, confirmed empirically)
  and either closes the `Process` object directly or terminates, escalates
  to `kill()`, reaps, and then closes it. Four new regression tests cover
  the never-started case (with direct proof `close()` was attempted), a
  genuinely partially-started case (a wrapped `start()` calls the real
  implementation before injecting a failure), the `Process` object's own
  `close()` failing during that cleanup, and an IPC channel's `close()`
  failing during that same cleanup.
- `self._startup_cleanup_problems` is now instance-owned, populated in
  `__enter__`, and unconditionally folded into `__exit__`'s own problems at
  the start of every call. Three new parametrized regression tests (one per
  redundant copy) prove a successful handshake and statement still surface
  an earlier close failure.
- `_ensure_background_statement_torn_down()` (which called
  `blocked.__exit__()` — the implementation many of these tests exercise) is
  replaced by `_emergency_teardown()`, which operates directly on the real
  `Process` and, when a backend pid was recorded, an independent
  `pg_terminate_backend()` call. Applied to every regression test that
  creates a process, backend, transaction, advisory lock, watcher, or IPC
  resource, including the five production-invariant concurrency tests
  (restructured to construct `_BackgroundStatement` as its own statement
  before the `with` block so it stays reachable from the existing
  `finally: _cleanup_world(...)`) — none of their assertions or evidence
  changed.
- Trimmed a duplicated docstring passage in `_worker_main` that repeated the
  class docstring's own outcome-publication explanation almost verbatim.

**Results:** 57 tests in `test_entity_type_change_protection.py` (9
sequential, 43 helper regression tests — up from 34 — and 5 unweakened
concurrency tests) pass locally against AWS `dev`, confirmed stable across
three repeated runs; the full suite is 1,153 tests (up from 1,144). See the
verification commands and results in
[PHASE5_VERIFICATION.md § Thirteenth exit review](PHASE5_VERIFICATION.md#thirteenth-exit-review-accurate-missing-outcome-classification-universal-backend-verification-and-processstart-failure-ownership-2026-08-05).

## Fourteenth review: evidence-based containment classification, fully guarded cleanup, and a complete independent safety net (2026-08-05)

The thirteenth pass correctly introduced `containment_reason`, ran backend
verification on every path, and gave `Process.start()` failures real
ownership, and its pushed PR head (commit `267ac1d`) passed all 1,153 tests
in GitHub Actions
[`30977657034`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30977657034).
Review of that same open PR found each of the three fixes was itself still
incomplete:

1. **Forced-termination classification was still not evidence-based.**
   `_force_stop()` classified containment as `"forced"` whenever the process
   was no longer alive after the post-`terminate()`/`kill()` join — regardless
   of whether that specific call actually raised, or merely no-opped and the
   process happened to end for an unrelated reason during the same join
   window. Reproduced deterministically with a fake process (`terminate()`
   raising, `is_alive()` then reporting `False`): `_force_stop()` still
   returned `"forced"`. A worker that survives every graceful attempt, whose
   `terminate()` then fails or no-ops, that happens to finish naturally during
   the subsequent join, and whose outcome publication then fails, could still
   have that missing outcome wrongly excused as the legitimate
   forced-termination case.
2. **Partial-start cleanup was not completely failure-safe.** `terminate()`,
   `kill()`, and `close()` in `_cleanup_process_after_start_failure()` were
   protected, but its `join()`/`is_alive()` calls were not. A deterministic
   probe against a fake process reproduced a `join()` failure escaping the
   method uncaught, replacing the original `Process.start()` exception
   entirely and skipping subsequent cleanup — including the IPC-channel
   cleanup `__enter__`'s except block runs immediately afterward. The same
   unguarded-call pattern was present in `_force_stop()`'s graceful-phase
   loop, `_reap()`, and two checks in `__exit__()` itself.
3. **The regression-test safety net did not fulfill its own stated
   contract.** `_emergency_teardown()` no longer called
   `_BackgroundStatement.__exit__()` (an improvement), but a deterministic
   probe showed it left the `Process` object unclosed, left all six IPC
   endpoints untouched, and suppressed every termination/backend-cleanup
   failure it encountered (`contextlib.suppress(Exception)` and a bare
   `except Exception: pass`) instead of collecting and reporting them — able
   to hide a genuine survivor or resource leak, invisibly, precisely because
   it no longer relies on the implementation under test to surface one.

Acceptance criteria, all test-infrastructure-only (do not change a
production trigger or add a migration unless a separate review finds a
concrete production defect):

- `"missing-after-forced-termination"` is reachable only when there is
  positive evidence a successful, controller-owned `terminate()`/`kill()`
  actually ended the process — a raised or no-op forcible call followed by
  the process merely no longer being alive must not produce it.
- No cleanup-path `join()`/`is_alive()` call can itself raise and replace an
  already-propagating startup, statement, or outcome exception.
- Partial-start cleanup preserves the original `Process.start()` exception in
  every case, attempts every independently valid containment step regardless
  of an earlier one's failure, and still closes every IPC endpoint afterward.
- The independent safety net directly and independently attempts process
  status/terminate/kill/join/close, backend termination and confirmation,
  and closure of every IPC endpoint — collecting every failure, never
  suppressing one — and preserves a test-body exception as primary rather
  than replacing or hiding it behind its own findings.
- Re-run the focused helper tests (including new ones for the safety net
  itself), all five invariant concurrency tests, the complete test suite,
  migration checks, and the actual final pushed-head CI.

**Fix — no schema or migration change; all changes confined to
`tests/database/test_entity_type_change_protection.py`:**

- A new `_attempt_forced_termination()` requires *positive* evidence before
  returning `"forced"`: the `terminate()`/`kill()` call itself must complete
  without raising, **and** `Process.exitcode` afterward must be negative
  (confirmed empirically to hold for both calls on this platform, and true by
  definition on POSIX) — distinct from the `0` a natural/graceful exit
  reports. A new `"indeterminate"` containment reason covers "not alive, but
  without evidence this controller's own call caused it," treated identically
  to `"graceful"`/`"survived"` by `_finalize_worker_outcome` (never exempting
  a missing outcome). Ten new deterministic, fake-process-driven tests cover
  every combination of failed/no-op/successful `terminate()` and `kill()`
  against every combination of subsequent liveness/exitcode evidence, plus a
  table-driven proof that a missing outcome is a protocol failure for every
  containment reason except `"forced"`.
- Two new shared helpers, `_safe_read()` and `_process_liveness()`, guard
  every `join()`/`is_alive()`/`pid`/`exitcode` read across `_force_stop()`,
  `_reap()`, `_cleanup_process_after_start_failure()`, and `__exit__()` —
  collecting a failure rather than letting it propagate, and treating an
  unreadable status as "might still be alive," never as "already gone."
  `_cleanup_process_after_start_failure()` also now collects `pid`-read and
  initial-`is_alive()`-read failures instead of silently defaulting them to
  "never started." Nine new fake-process-driven tests cover pid-inspection,
  initial-status, `terminate()`, first-join, post-terminate-status, `kill()`,
  second-join, final-status, and process-close failures individually; one new
  integration test (a genuinely spawned, startup-delayed process whose
  `start()` fails after spawning) proves a `terminate()` failure and an IPC
  endpoint's close failure are both reported together without replacing the
  original `Process.start()` exception.
- `_emergency_teardown()` is rewritten around a new `_run_emergency_teardown()`
  that directly and independently attempts process status/terminate/kill/join,
  a final status check before closing the `Process` object, independent
  backend termination *and* polled confirmation the backend disappeared,
  closure of all six IPC endpoints, and (via a new `extra_connections`
  parameter) release of a test-controlled lock-holding connection — replacing
  the five call sites that previously paired a separate `first.rollback()`
  alongside it. Every failure is collected, none suppressed. `_emergency_teardown()`
  itself uses `sys.exc_info()` to attach found problems as notes to an
  already-propagating test-body exception, or raise them directly when
  nothing else is failing — including when an expected failure was already
  fully handled by an enclosing `pytest.raises`, which leaves nothing
  propagating by the time the `finally` block runs. Sixteen new unit tests,
  built entirely from fake process/pipe/backend-connection objects (no real
  process or database), cover the happy path, successful termination, kill
  escalation, survival after both forcible operations fail, both joins
  failing, status-inspection failure, process-close failure, all six IPC
  endpoints failing independently, `pg_terminate_backend` itself failing,
  verification-query failure, the backend never disappearing, a clean
  confirmation, an extra connection's rollback failing, and the three states
  of the exception-preservation contract.
- Two of the newly touched fault-injection test doubles (`_FakeConnection`
  and the `close()` seams patched via `_raise_injected_failure`) previously
  raised on *every* call, unlike a real `Process`/`Connection`'s idempotent
  `close()` (confirmed empirically) — which meant the redesigned safety net's
  own redundant close attempt would observe a second, spurious failure from a
  problem the test already fully proved once. A new `_raise_once_then_succeed()`
  helper and `_FakeConnection`'s own idempotent-after-first-call `close()`
  fix this without weakening any existing assertion.

**Results:** 93 tests in `test_entity_type_change_protection.py` (up from 57:
36 new — 10 forced-termination-classification tests, 10 partial-start-cleanup
tests, and 16 safety-net unit tests) pass locally against AWS `dev`; the full
suite is 1,189 tests (up from 1,153). See the verification commands and
results in
[PHASE5_VERIFICATION.md § Fourteenth exit review](PHASE5_VERIFICATION.md#fourteenth-exit-review-evidence-based-containment-classification-fully-guarded-cleanup-and-a-complete-independent-safety-net-2026-08-05).

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

## At a glance (all blockers resolved, pending final-head CI confirmation)

Phase 5's documented gameplay capabilities were implemented, merged, and
verified. All production, concurrency-verification, and test-infrastructure
blockers are resolved and locally verified; the test-infrastructure blocker's
formal closure additionally awaits PR #15's own final-head CI confirmation
(see item 3):

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
   unconditionally, forcibly stopped — closed by the tenth pass replacing
   the worker thread with an independently terminable OS process
   (`multiprocessing.Process`), confirmed by PR #13's push-triggered CI run
   [`30955234630`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30955234630).
   An eleventh review then found that process-based redesign could still
   report false success (a commit failure reported as `"committed"`) and
   silently discard cleanup failures (an outcome nobody explicitly consumed
   could be lost, and a controller-side verification error could replace an
   already-propagating exception). Fixed by the eleventh pass's worker-outcome
   protocol fix, controller-side failure-safe cleanup, and completed
   process/IPC lifecycle handling, confirmed by its final documentation head's
   own CI run
   [`30966346368`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30966346368).
   A twelfth review then found the eleventh pass's own `scripts/verify.sh
   --help` claim did not hold up to its exit code, the worker outcome
   protocol still let a naturally exited worker with an empty outcome channel
   pass as success, `_worker_main`'s cleanup was not itself independently
   failure-safe, and the IPC redesign still relied on an abandonable wrapper
   thread to bound `multiprocessing.Queue`'s own unbounded `join_thread()`.
   Fixed by the twelfth pass's verification-tooling fix, total worker
   outcome protocol, independently failure-safe worker cleanup, and
   `multiprocessing.Pipe`-based IPC, confirmed by PR #15's push-triggered CI
   run
   [`30972855981`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30972855981)
   for implementation commit `f3ed98a`. A thirteenth review of that same
   open PR's follow-up commit (`d0032dc`) then found the twelfth pass's own
   outcome-protocol, backend-verification, and process-ownership fixes were
   themselves still incomplete — see [§ Thirteenth
   review](#thirteenth-review-accurate-missing-outcome-classification-universal-backend-verification-and-processstart-failure-ownership-2026-08-05)
   above. Fixed by the thirteenth pass's accurate missing-outcome
   classification, universal (non-redundant) backend verification, and
   `Process.start()` failure ownership, confirmed by PR #15's push-triggered
   CI run
   [`30977657034`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30977657034)
   for that same commit (`267ac1d`). A fourteenth review of that commit then
   found the thirteenth pass's own forced-termination classification,
   partial-start cleanup, and regression-test safety net were themselves
   still incomplete — see [§ Fourteenth
   review](#fourteenth-review-evidence-based-containment-classification-fully-guarded-cleanup-and-a-complete-independent-safety-net-2026-08-05)
   above. **Resolved** by the fourteenth pass's evidence-based containment
   classification, fully guarded cleanup, and complete independent safety
   net, verified locally (93 tests in `test_entity_type_change_protection.py`,
   1,189 total), pending confirmation from PR #15's own final-head CI run.
   See
   [PHASE5_VERIFICATION.md § Fourteenth exit review](PHASE5_VERIFICATION.md#fourteenth-exit-review-evidence-based-containment-classification-fully-guarded-cleanup-and-a-complete-independent-safety-net-2026-08-05).

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
