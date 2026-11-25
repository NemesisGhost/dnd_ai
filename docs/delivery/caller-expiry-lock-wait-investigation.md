# Caller expiry during a membership lock wait

2026-11-25 · Reliability support for draft PR #78 · Independent review pending. The C08 work-register row owns the investigation obligation. [Work register](work-register.md#p15-c08)

## Finding

The old test started a four-second database deadline before snapshots, lock setup, app construction and the HTTP request. Its two observations, a lock waiter somewhere in the test database and a subsequently expired assignment, could occur in the opposite order from the scenario it claimed to prove. Controlled delays demonstrated **both** an early refusal that failed the test and a late lock arrival that passed it. The evidence supports correcting test coordination. Production authorization continues to supply the decisions under test.

The starting worktree on `phase15/completion` was clean. HEAD, the local tracking ref, the live remote ref and the open draft PR all named `a057e0992bb8dba6d5ac7f4b2bbb6d5138741358`. The user-level Codex AGENTS.md was empty. The repository and applicable ancestor directories supplied no additional AGENTS.md. Repository guidance came from CLAUDE.md and the development and documentation standards. At this baseline and live main `fe560e7e0be5e6c6040d195782ed923d7f7ca6dc`, Git reported identical trees for all of `src/` and `tests/`, identical CI workflow and no lockfile difference. The old-setup experiment therefore exercises the same backend and harness source on both revisions.

## What each observation measures

| Stage | Execution and clock |
| --- | --- |
| Fixture and old diagnostic | `g` commits two owners, a player, a custom manager and an addable user. Only the caller's built-in owner assignment supplies this caller's `access.manage`. A fixture transaction sets `expires_at` from PostgreSQL `clock_timestamp()` and commits. Counts, unrevoked owner membership IDs and the pre-launch margin are separate checkouts. The margin is a database interval sampled before starting the client thread. |
| Launch and pool | A Python worker constructs the app, installs the engine and OIDC principal overrides, enters Starlette TestClient and its AnyIO lifespan, then posts. HTTPX measures transport dispatch through response stream close using Python `perf_counter()`. Thread scheduling, app construction and client entry precede that measurement. The transport includes ASGI dispatch, dependency scheduling, SQLAlchemy pool checkout/pre-ping, SQL and response handling. The test's `monotonic()` polling budget is another elapsed-time measurement. None timestamps an authorization decision. |
| HTTP entry | `get_connection` checks out the test engine's request connection and begins the transaction. The capability dependency resolves access on it, using PostgreSQL `now()` (transaction start), checks `access.manage`, then opens the route's plan and registers that capability as its first requirement. If the transaction starts after this caller's expiry, membership still exists but the capability is absent. The dependency raises generic `403 forbidden` before the handler locks anything. |
| Intended wait | The unkeyed POSTs use the API's pre-write plan implementations. All five prepare functions/branches lock actor role rows before the target row. Add member also locks the actor membership and the actor and target accounts before requesting the campaign row `FOR UPDATE`. Assign, change and both transfers block on the player's membership `FOR UPDATE`. The holder owns one specified row in its own transaction. The old probe counted any lock wait in the database over a 15-second polling budget. |
| Ownership and finalization | After acquiring the locks, the command checks D3 ownership as of the request transaction's `now()`. A finite assignment may pass that predicate even after its deadline. The DEF-013 `_recheck_owner` then reads `clock_timestamp()` on the same connection. An expired caller gets `403 campaign_owner_required`. On the successful path the separate `plan.finalize` reads a fresh authority snapshot and evaluates requirements in registration order, before protected writes. A DEF-013 refusal exits before finalization and before writes. The file's last, direct-command test exercises a different path, including rollback after recipient assignment. |
| Response and durable effects | The function-scoped request dependency rolls back on an exception and closes the connection before the mapped error is sent. Success commits before the response. After joining the HTTP worker, independent reads compare campaign membership and role counts, the world's audit count and unrevoked owner membership IDs, and check the player gained no ownership. Live controls check successful effects, including both audit rows for add member. |

Source entry points are the [gate fixture and state probes](../../tests/database/test_campaign_owner_gate.py), [original request/lock helpers](../../tests/database/test_campaign_owner_lock_order.py), [capability dependency](../../src/dnd_ai/api/access.py), [transaction owner](../../src/dnd_ai/api/deps.py), [HTTP routes](../../src/dnd_ai/api/memberships.py), [membership plans](../../src/dnd_ai/commands/membership_role_plans.py) and [finalization](../../src/dnd_ai/domain/authorization.py).

## Hosted history and attribution

- C08 run `45555510700`, head `695f60038af318dbd92102d1b2b203fe022d7ec7`. On each of attempts 1, 2 and 3, shard 5 reported the missing wait for `add_member`, 1 failed and 1,169 passed. The portal job also reached its then ten-minute cap on each attempt. Those shard failures precede the added diagnostic. [C08 run](https://github.com/NemesisGhost/dnd_ai/actions/runs/45555510700)
- Diagnostic commit `1c9cc3ac50132c6f854e5752c60e33154b595c55` preserved the assertions and added the margin query and response report. Fresh PR run `45604594755` on that head passed all 14 jobs on its first attempt. The subsequent main merge push also passed. Earlier isolated and shard-order local passes are separate from the hosted failures. [Fresh C08 run](https://github.com/NemesisGhost/dnd_ai/actions/runs/45604594755) · [Merge run](https://github.com/NemesisGhost/dnd_ai/actions/runs/45609184661)
- C09 run `45657533221`, attempt 1 on the starting SHA, again failed shard 5 on `add_member`. The other four refusal parameters passed. The diagnostic reported +3.995081 s immediately before launch, HTTP elapsed 4.608842 s, generic `403 forbidden`, no observed lock waiter and a margin of −11.019707 s at the failure report. Counts were 1 failed, 1,169 passed and 10,195 deselected. The portal job separately failed CharacterPublicProfilePage F2 release-button focus and CharacterRevelationsSection V19 double-404 read-back. [Shard 5](https://github.com/NemesisGhost/dnd_ai/actions/runs/45657533221/job/139358133090) · [Portal](https://github.com/NemesisGhost/dnd_ai/actions/runs/45657533221/job/139358133189)

The C09 error code and the continuously held campaign row are consistent with refusal before the intended wait. The logs lack a request PID, transaction-start instant, capability result and per-stage timings. Subtracting the margin from HTTP elapsed cannot locate the delay. The experiment below establishes a sufficient cause locally. Which stage consumed time on GitHub, and why this parameter recurred, remain unproven.

## Controlled experiments

Each run used a fresh test database on an isolated loopback PostgreSQL 18 cluster. A temporary pytest plugin delayed the request worker's SQLAlchemy checkout callback by five seconds after pool selection and before the connection reached the app. This models pre-transaction latency. It does not measure pool contention. The plugin let the real resolver return, then sampled `now()`, `clock_timestamp()` and `expires_at` on that request connection, inspected `has_capability("access.manage")` and recorded any real DEF-013 exception. For the second injection it delayed return from the successful resolver instead. Neither experiment added a capability or supplied an authorization decision.

| Setup and injection | Result |
| --- | --- |
| Old, five seconds at checkout, add member and assign | **2 failed**. Both transactions started after expiry and the resolver returned no manage capability. Neither reached the target wait or DEF-013. The pre-launch margins were +3.967029 and +3.996436 s, with HTTP elapsed 5.190774 and 5.315154 s respectively. Both returned generic 403. |
| Old, same probes without delay, same parameters | **2 passed**. Prompt controls reached the fresh owner refusal. |
| Old, five seconds after a successful entry read, add member | **1 passed incorrectly for the claimed ordering**. The entry snapshot was live, the delay kept execution before the handler until after expiry, and the later fresh check refused. The old test accepted a lock wait that started too late. |
| Development version, deadline first assigned at the gate | Checkout-delay pair **2 passed**, after-entry delay **1 passed** in a separate run. The final version also seeds a finite deadline before entry to retain that fixture condition. |
| Corrected, same five seconds at checkout, add member and assign | **2 passed**. Both entry reads had manage authority. For add member, request PID 30608 waited directly on 16500 on the campaign `FOR UPDATE`. Database times (local UTC−06) were wait start 11:54:17.840117, expiry 11:54:21.818030, still blocked 11:54:21.838951. For assign, PID 9844 waited on 30608 on the player membership. Wait start 11:54:27.266504, expiry 11:54:31.260913, still blocked 11:54:31.264949. Both took the real fresh refusal after release. |
| Corrected, same five seconds after the successful entry read, add member | **1 passed**, with the enforced wait/expiry ordering. |
| Corrected, five seconds immediately before dispatch of the target campaign lock | **1 failed as intended** on `waitstart < expires_at`. PostgreSQL recorded 11:54:59.508449 for lock arrival and 11:54:58.485587 for expiry. This deliberately exercises the remaining scheduling bound. |

To repeat the discriminating checkout experiment, install the following temporary pytest plugin on the test interpreter's import path. Run the refusal node for `[add_member]` and `[assign]` with `-p delay_checkout` on the baseline and on the correction. The injected delay is confined to this experiment.

```python
# delay_checkout.py
import threading
import time

import pytest
from sqlalchemy import event


@pytest.fixture(autouse=True)
def delay_request_checkout(postgres_engine):
    def delay(*_):
        if threading.current_thread().name == "AnyIO worker thread":
            time.sleep(5)

    event.listen(postgres_engine, "checkout", delay)
    try:
        yield
    finally:
        event.remove(postgres_engine, "checkout", delay)
```

## Correction and mutation

Test-only correction commit `2434990760007834d6df11a8bb157b749e45d77a` changes [test_campaign_owner_caller_expiry.py](../../tests/database/test_campaign_owner_caller_expiry.py).

Each caller enters with a finite one-hour assignment. The shared strict `StatementGate` signals when the real request is about to send its first actor role lock, after the capability decision. The expiry case commits the shortened four-second deadline on a fixture connection while the request is parked. Changing the role after the actor locks could block the fixture itself. The fixture commits before a separate holder takes the target row because the deferred access-manager retention trigger can lock the campaign. The live control keeps its long deadline and follows the same gate and target-lock path. [Corrected test](../../tests/database/test_campaign_owner_caller_expiry.py) · [HTTP synchronization helper](../../tests/http_race_support.py)

The observer identifies the request backend from the gate and the holder backend from its own transaction. The holder locks exactly one row. An ungranted lock for that request PID must name the holder in `pg_blocking_pids`. For the expiry case the same sample must satisfy `waitstart < expires_at < clock_timestamp()` before release. A late observer can still establish when the wait began. Scoped cleanup releases the holder and gate and waits for the tracked request even on an assertion failure. The response assertion checks the exact error code. The snapshot, ownership and live-control assertions remain in force.

Only the `prepare_add_member` call to `_recheck_owner` in `src/dnd_ai/commands/membership_role_plans.py` was omitted in the mutation. The target reached its real lock and passed the wait/expiry assertions, then **failed** because the later plan finalization judged the now-missing route capability first and returned generic `403 forbidden`. The status alone would have missed the mutation. A comment-only no-op at the identical call site **passed**. The mutation and control each ran in a fresh interpreter. Both restored the original working-file bytes in a `finally` block and compared them with the saved copy.

| Working-file SHA-256 | Value |
| --- | --- |
| Original, restored after mutation, restored again after control | `6e5f00df7d4850c8af8d73088615f1759298e91f3fefcdc3a8e469f589066692` |
| Mutated | `2b24ff87341be02d88166808cd1f90c76060f6c6f378e4fa4743486cdde2a515` |
| Comment-only control | `c4907d5fd560960ae081b5768ff9d858cb51b3b56baaa85a3aac089a7dd809ca` |

## Verification

Local sessions ran sequentially, with the repository interpreter, disposable PostgreSQL 18, the default-configuration isolation plugin and an empty working directory for the focused and shard-5 pytest runs. The counts below exclude the deliberately delayed experiments and mutations above.

| Invocation | Result |
| --- | --- |
| Target `[add_member]` alone | 1 passed in 9.65 s |
| All five refusal parameters | 5 passed in 26.61 s |
| Whole caller-expiry file, including all five live controls and the direct-command rollback | 11 passed in 31.58 s |
| Eight related files: campaign owner gate, lock order, expired recipient, membership role concurrency, R01 S5-E2 lock order, membership routes, transfer route and S5-F owner final authority | 341 passed in 361.58 s |
| `CI_TEST_SHARD=5/8`, full collection with the CI whole-file assignment | 1,170 passed, 10,195 deselected in 577.94 s |
| Non-pytest backend checks | Ruff format (990 files) and lint, mypy on `src` (300 files) and the CI helper, `uv lock --check`, isolated Alembic upgrade to head and schema comparison, documentation and whitespace checks passed. An initial file-only lint flagged import spacing during editing, corrected before these checks. |
| Full four-shard backend runner, with no competing portal run | **1 failed, 11,358 passed, 6 skipped**. All 11,365 collected tests across 485 files were accounted for in 31m14s. The caller-expiry file passed. |
| Single follow-up of the organization-reader failure on a fresh cluster | 1 passed in 7.13 s. The full backend run remains recorded as failed. |

The full-run failure was `test_api_organization_reader.py::test_a_faction_carries_its_ideology_and_a_business_none_of_its_structural_fields` on local shard 1/4. Its raw response substring assertion found `-77` in the returned shop UUID `88245852-77a0-4f93-b1b2-d54eec427d0b`. This is separate from caller expiry. [Organization reader assertion](../../tests/database/test_api_organization_reader.py)

## Remaining limits

Request startup, pool checkout and entry authorization precede the four-second window. The window still covers the fixture commit, holder acquisition and the request's remaining database work up to the intended wait. Several branches lock the caller's assignment before reaching that row, so an external update after observing that wait would itself block. The late-dispatch experiment demonstrates the failure the ordering assertion now reports. Existing bounded waits also require a responsive runner. These tests use the real database and HTTP routing with a fixture principal and in-process transport. The direct-command case retains its own timing setup. Historical runner attribution, independent review and the two portal investigations remain open.
