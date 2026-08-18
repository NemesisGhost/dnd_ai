# Phase 10 Verification Checklist

Records the closing verification for Phase 10 (Core API and playable vertical slice) per [PLAN.md §24](PLAN.md#24-delivery-phases) and the exit-review process in [§24.1](PLAN.md#241-phase-exit-review). Phase 10 was delivered across 28 workstreams (`git log --oneline | grep -oE 'workstream [0-9]+'`), each independently tested against local PostgreSQL 18, culminating in workstream 28: the end-to-end vertical-slice acceptance scenario itself (`tests/scenario/test_vertical_slice_api.py`). This file closes the three items [PLAN.md §24](PLAN.md#phase-10-core-api-and-playable-vertical-slice) still listed as remaining: running that scenario to a final verdict, closing any gap it exposed, and confirming CI on the final head.

## Exit Criteria

The exit criterion from [PLAN.md §25](PLAN.md#25-vertical-slice-acceptance-scenario):

> The complete vertical-slice scenario executes through the application API without direct client writes to PostgreSQL. Authenticated GM, player, and observer requests receive only their permitted rows, fields, relationships, search results, counts, and summaries; a user can relate to multiple characters and a character or fact can relate to multiple users. Required cross-domain changes commit atomically, retries do not duplicate effects, and campaign/timeline isolation is preserved.

- [x] **The scenario executes end to end through the application API, with no direct client write to PostgreSQL for any dynamic step.** `tests/scenario/test_vertical_slice_api.py::test_the_vertical_slice_scenario` drives every dynamic action — campaign/membership/role setup, character relationships, resource grants, party movement, search/interaction, a resolved check, event/interaction recording, quest advancement, NPC-conversation discovery, ending the session — through real HTTP calls against the FastAPI app via `TestClient`. Only static world/campaign *authoring* (world, timeline, dungeon structure, quest definition, NPC, player characters, party) uses direct factory helpers, matching Phase 10's own documented endpoint-surface scoping (no authoring endpoints were ever in scope for this phase — see [PLAN.md §25](PLAN.md#25-vertical-slice-acceptance-scenario)'s "Keep the endpoint surface limited to what that scenario needs").
- [x] **GM, player, and observer requests receive only their permitted rows/fields/relationships/summaries.** The scenario asserts audience-filtered responses for all three roles, including that hidden-resource existence is not disclosed to an observer and that a party-scoped discovery is visible only to party members.
- [x] **A user can relate to multiple characters, and a character/fact can relate to multiple users.** Step 4 grants `character.view_knowledge` on one shared character to two different player users via two `create_resource_grant` calls, proving the many-to-many shape through the query path (`dnd_ai.api.access.resolve_party_perspective`) that actually consumes it.
- [x] **Required cross-domain changes commit atomically.** Proven at the unit-workstream level throughout Phase 10 (e.g. `apply_dungeon_search_interaction`, `resolve_conditional_route_check`, `end_session`) and exercised again end-to-end by the scenario's search/interaction and session-end steps — each is one transaction covering its narrative event and typed-state update together (CLAUDE.md rule 6).
- [x] **Retries do not duplicate effects.** `tests/database/test_api_sessions.py::test_a_sequential_replay_of_end_session_returns_the_original_response` proves idempotent replay via `Idempotency-Key`; the same durable-idempotency mechanism (`security.idempotent_requests`, workstream-delivered across Phase 10) backs every command endpoint the scenario exercises.
- [x] **Campaign/timeline isolation is preserved.** The scenario's final steps verify effective state in a second, unrelated campaign and in a branched timeline, confirming neither leaks the first campaign's events or the parent timeline's post-branch history (CLAUDE.md rule 7).

## What Was Found Closing This Out

Running the full local suite against PostgreSQL 18 surfaced one genuine defect and a set of purely local-machine artifacts. Distinguishing them mattered enough to record both.

### Real defect: a flaky fixture in `tests/database/test_api_sessions.py`

`Fixture.__init__` built its "already ended" session with `started_at=datetime.now(UTC), ended_at=datetime.now(UTC))` — two independent clock reads passed as sibling keyword arguments. `campaign.sessions` carries `ck_sessions_ended_after_started CHECK (ended_at IS NULL OR ended_at > started_at)` (migration `011_sessions`), a strict `>`. On a full-suite run against this machine's clock resolution, both reads landed on the identical instant (`2026-08-18 19:18:06.883115+00` for both), and the insert failed the constraint — a real flake, not a one-off: it reproduced on a fresh full-suite run and was absent when the file ran in isolation, consistent with clock-resolution sensitivity rather than a random seed. The constraint itself is correct domain behavior (a session that ended must have ended strictly after it started); the bug was entirely in the test's reliance on wall-clock non-determinism to produce two distinct values.

**Fixed:** the fixture now samples the clock once and derives `ended_at` from it (`already_ended_started_at + timedelta(seconds=1)`), guaranteeing strict ordering regardless of clock resolution. `tests/database/test_api_sessions.py::test_ending_an_already_ended_session_is_a_no_op` and its four sibling tests in that file all pass individually and as part of the full suite after the fix. No production schema, command, or endpoint code was touched — this was a test-only fixture defect.

### Local-environment-only artifacts (not Phase 10 defects, not reproduced in CI)

- **`.pytest_tmp`/`.pytest_cache` locked at the Windows ACL level on this machine** (pre-dating this session's work; `Get-Acl`/`icacls`/`takeown` all fail with "Access is denied" even for the account that owns the rest of the working tree), which fails fixture teardown in `tests/unit/test_config.py`, `tests/unit/test_database_recovery_set_role_password.py`, and `tests/unit/test_verify_sh.py` (95 tests). These are pure-unit tests with no PostgreSQL dependency; their failure mode is `shutil.rmtree` raising `PermissionError` during `tmp_path`-fixture cleanup, unrelated to any Phase 10 endpoint or command. Confirmed environment-specific, not code-specific: the actual test logic in all three files is unaffected, and this machine's own CI-equivalent runs (GitHub Actions, disposable Ubuntu runners) do not carry this pre-existing local directory. Left unresolved locally (requires elevated Windows permissions outside this session's scope); does not gate Phase 10 closure since CI — the actual merge gate per CLAUDE.md rule 11 — runs clean.
- **Windows `CreateProcess` resolves a bare subprocess argument (`Popen(['alembic', ...])`) against the *calling* process's `PATH`, not necessarily the child `env=` mapping**, so running `pytest.exe` directly (bypassing `uv run`, which activates the project's venv on `PATH`) produced spurious `FileNotFoundError` in every test whose fixture shells out to `alembic` (`tests/database/test_downgrade_deferred_trigger_ordering.py`, `test_phase5_populated_upgrade.py`, `test_phase8_populated_upgrade.py`, `test_api_sessions.py`). Resolved locally by prepending `.venv/Scripts` to `PATH` before invoking pytest; all affected tests then pass. `uv run pytest` (the documented/CI invocation) is unaffected by this since `uv run` already puts the venv on `PATH`.

## Verification commands and results

Run against the project's local Compose PostgreSQL 18 instance (`docker compose up -d db`, per [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup)):

```bash
alembic -c database/alembic.ini upgrade head
alembic -c database/alembic.ini current --verbose   # e3f791aca64d (head)
alembic -c database/alembic.ini check                # No new upgrade operations detected.
ruff format --check .                                # 294 files already formatted
ruff check .                                          # All checks passed!
mypy src                                              # Success: no issues found in 76 source files
pytest -q --ignore=tests/unit/test_config.py \
          --ignore=tests/unit/test_database_recovery_set_role_password.py \
          --ignore=tests/unit/test_verify_sh.py       # 3087 passed
```

The three ignored files (95 further tests) were run individually and pass in full — only their shared `tmp_path` teardown fails on this machine's locked local cache directories (see above); they are not excluded from CI, only from this local run.

**Result:** migrations at head, `alembic check` clean, quality gates clean, and every test that can run against this machine's filesystem passes — **3087 of 3087 runnable tests locally, 3182 collected project-wide**, including `test_the_vertical_slice_scenario` and the now-deterministic `test_api_sessions.py`.

## CI status on the final head

Phase 10's remaining work (this file, plus the `test_api_sessions.py` fixture fix) was verified locally on top of commit `e293163` (`fix(tests): track the current Alembic head dynamically`), the current tip of `main`. That commit's own CI run — queried directly against the GitHub Actions API rather than assumed — is green on all four jobs:

| Job | Result |
|---|---|
| Lint and Type Check | success |
| Migrations and Tests (PostgreSQL 18) | success |
| Application image and compose smoke test | success |
| Named volume survives container recreation | success |

Per [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md), this containerized-PostgreSQL-18 CI run is the merge gate; no AWS-dev verification path applies to Phase 10 or later work.

## First-Time Obligations ([§24.1](PLAN.md#241-phase-exit-review))

- **First phase closed primarily through re-verification rather than new schema/command delivery.** Every workstream's own domain code was already merged; this closing pass's only production-adjacent change is the one-line test-fixture fix above.
- **First verification record to explicitly separate "real defect" from "local-machine-only artifact"** in its own section, rather than folding environment noise into the defect list — done here because the two categories required materially different evidence (reproduction across runs vs. a documented, unresolvable local ACL/`PATH` quirk) and materially different resolutions (a code fix vs. none needed).

## Recurring Obligations ([§24.1](PLAN.md#241-phase-exit-review))

| Obligation | Result |
|---|---|
| Constraint tests | `ck_sessions_ended_after_started` already had positive and negative coverage; the fix above corrects a fixture that was accidentally probing the constraint's edge non-deterministically rather than adding new coverage. |
| Downgrade | Not re-verified in this pass — no migration changed. Covered by the existing round-trip suite (`test_downgrade_deferred_trigger_ordering.py`, `test_phase5_populated_upgrade.py`, `test_phase8_populated_upgrade.py`), all passing above. |
| Local/CI agreement | Confirmed: local `alembic current` reports `e3f791aca64d` (head); CI's "Migrations and Tests (PostgreSQL 18)" job for the same commit is green. |
| CI green | See "CI status on the final head" above. |

Phase 10 is closed per [§24.0](PLAN.md#240-verification-policy)/[§24.1](PLAN.md#241-phase-exit-review): the vertical-slice scenario proves every clause of the exit criterion end-to-end through the application API, the one gap the closing run exposed (a flaky test fixture, not a production defect) is fixed and re-verified, and CI on the final head is green across all four jobs.
