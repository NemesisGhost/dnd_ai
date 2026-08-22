# Phase 11 Verification Checklist

Records verification for Phase 11 (Foundry MVP) and its required revision, Workstream 11R (local-authenticated hybrid Foundry pairing), per [PLAN.md §24](PLAN.md#24-delivery-phases). The seven original Phase 11 workstreams and their green CI proved the tactical adapter (combat/state sync, retry/idempotency, reconnect restoration, loop suppression, CORS/HTTPS enforcement) works; they did not prove the authentication design, which [PLAN.md's Workstream 11R entry](PLAN.md#phase-11-foundry-mvp) required to be replaced. This file covers Workstream 11R's nine bounded workstreams (A-I) and what they collectively prove.

## What 11R replaced and why

The original Phase 11 authentication model was a single, world-scoped `FoundrySystem` credential shared by every connected Foundry client, with the caller free to name which linked Foundry user a request authenticated as via an `X-Foundry-Actor-Id` header. That combination was a Critical defect: Foundry distributes every world-scope `game.settings` value to every connected client regardless of `config: false`, so any connected player who inspected their own client's settings could extract the shared credential and then simply claim the GM's own Foundry user id to authenticate as the GM. `game.user.isGM` checks in the module's own code only ever suppressed the module's *own* client-side behavior — never enforced server-side against an arbitrary HTTP request. `foundry-module/README.md`'s "Trust boundary" section (as it stood before this revision) documented this defect and the MVP-scoped mitigation that shipped instead of a real fix.

Workstream 11R replaces this with individually paired devices and short-lived, in-memory-only access tokens — no shared secret, no caller-selected identity, exact-campaign authorization scoping narrower than the legacy credential's world-wide scope.

## Workstreams delivered

| Workstream | Commit | What it delivered |
|---|---|---|
| A+B | `8dd688f` | Local account/password authentication (`security.local_credentials`, activation/reset tokens) and browser-session security (CSRF, rate limiting) — migration `099_local_authentication`. |
| D | `5190d82` | Foundry pairing schema (`security.foundry_connections`/`.foundry_pairing_codes`/`.foundry_devices`/`.foundry_access_tokens`) and commands — migration `100_foundry_pairing`. |
| C | `71e5f49` | `AuthenticatedPrincipal` extended with `FOUNDRY_ACCESS_AUTH_METHOD`; `get_authenticated_user_id` resolves `Authorization: FoundryAccess <token>` via `resolve_foundry_access_principal`. |
| E | `0a0da2c` | Pairing-code creation, self-service device list/revoke/rotate, and `access.manage`-gated campaign device/connection administration endpoints (`dnd_ai.api.foundry_pairing`). |
| F | `f475aa2` | Converted the bounded adapter route surface (`character_state`, `characters`, `integration`) to accept `allow_foundry_access` alongside the still-live `allow_foundry_system` gate. |
| G | `f25850f` | Audit attribution extended: `audit.change_log.acting_foundry_connection_id`/`.acting_foundry_device_id` — migration `101_change_log_foundry_pairing`. |
| H | `ae91df2` | `foundry-module/` converted to per-device pairing: FoundryVTT minimum raised to v13, `scope: "user"`/`scope: "client"` pairing settings, in-memory-only access-token cache, new pairing UI replacing the legacy connection-setup form. |
| I | `026fd0d`, `7e90d96` | `scripts/foundry_provision.py`'s legacy `FoundrySystem`-issuing subcommands removed (not merely deprecated, per item 6's literal requirement); `pairing-code` subcommand added over the same public pairing API; legacy transition sequence documented. |

Workstream ordering deviated from the letter sequence: D (pairing schema) was implemented before C (principal wiring), since C's `resolve_foundry_access_principal` wiring depends on D's tables existing first. This is a scheduling change only — every workstream's own scope is as specified.

## Non-negotiable boundaries preserved

- **PostgreSQL remains the only source of truth**; no new cache/derived-authority store was introduced.
- **Forward-only migrations.** `099`→`100`→`101` are pure additions; no already-merged migration was edited. `alembic check` reports a single clean head at `101_change_log_foundry_pairing` with no drift from the SQLAlchemy models.
- **No new client bypasses the application API.** FoundryVTT's pairing/token/adapter calls all go through `dnd_ai.api.foundry_pairing`/the existing adapter routers.
- **OIDC remains optional; local authentication works with every OIDC setting absent** — unchanged by this workstream, and exercised throughout `tests/database/test_api_auth.py`.
- **No Pocket ID/Cognito/OAuth server/OIDC provider was introduced.**
- **Raw secrets are never stored or logged.** Pairing codes, device secrets, and access tokens are stored only as sha256 hashes (`code_hash`/`device_secret_hash`/`token_hash`); the Foundry module holds the access token in a module-level in-memory variable only (`FoundryAccessTokenCache`), never in any `game.settings` value.
- **No legacy `FoundrySystem` secret was auto-converted** into the new model — `security.foundry_connections`/`.foundry_devices` start empty for every pre-existing external system; pairing is always a fresh, explicit action.
- **One transaction per request, idempotency, sanitized errors, audience filtering, and non-disclosure are all unchanged** — every new command follows the same `_..._impl(connection, ...)` composable-command pattern as the rest of the codebase, and every new route calls its command directly on the request's own transaction (`dnd_ai.api.foundry_pairing`'s own module docstring).
- **No production React UI code was written.** The management/pairing HTTP contract is backend-only; the Foundry module's own pairing form is FoundryVTT `ApplicationV2`, not a web-portal component.

## Bugs found and fixed during this work (not present in the shipped result)

Recorded here because each was a real security- or correctness-relevant defect caught before merge, not after:

- **Cross-campaign GM-authorization gap**: `revoke_foundry_device`/`revoke_foundry_connection` originally had no way to scope a GM's revocation action to their own authorized campaign, so a GM authorized for one campaign could in principle revoke a device belonging to a different one by guessing its id. Fixed by adding an `expected_campaign_id` parameter mirroring the existing `expected_owner_user_id` self-service pattern.
- **False-positive "foreign owner" rejection on an already-revoked row**: the ownership-check fallback query checked "does this row exist at all for a different owner" instead of "does this row belong to a different owner," misreporting an already-revoked-but-correctly-owned row as foreign.
- **Clock-skew bug in rotation overlap**: `_rotate_foundry_device_impl` originally computed the old device's revocation timestamp in Python (`datetime.now(UTC) + overlap`) rather than in the same SQL statement `exchange_foundry_device_credential`'s comparison query uses, which could disagree with PostgreSQL's own `now()` under real clock skew. Fixed by computing the value entirely in SQL and reading it back via `RETURNING`.
- **Immediate-revocation logic bug**: `exchange_foundry_device_credential` checked `revoked_at IS NULL`, which is wrong once `revoked_at` is used as an effective-revocation-*time* (as an in-overlap rotation sets it to a future instant) rather than a boolean flag — fixed to `revoked_at IS NULL OR revoked_at > now()`.
- **Three missing FK-supporting indexes** and **eight tables missing from `test_role_grants.py`'s `MANAGED_TABLES` completeness list** (four from workstream A/B, four from workstream D) — both caught only by a genuine full-suite run, not the faster targeted runs used between workstreams.

## Verification commands and results

Run against the project's local PostgreSQL 18 (`localhost:5433`, per `.env`'s `DATABASE_URL`):

```bash
alembic -c database/alembic.ini current --verbose   # 101_change_log_foundry_pairing (head)
alembic -c database/alembic.ini check                # No new upgrade operations detected.
alembic -c database/alembic.ini heads                 # 101_change_log_foundry_pairing (head) — single head
ruff format --check .                                 # 361 files already formatted
ruff check .                                           # All checks passed!
mypy src                                                # Success: no issues found in 101 source files
pytest -q                                               # full tree, ephemeral from-empty database (no DND_AI_TEST_DATABASE_URL override)
```

**Migration chain:** `099_local_authentication` → `100_foundry_pairing` → `101_change_log_foundry_pairing`, each added this session, none editing an already-merged migration. `alembic check` against the local dev database (already at head) reports no drift. The full-suite run below builds its own database from empty and runs `alembic upgrade head` as part of every test session's setup, which is the from-empty replay verification for the complete chain (`094`→`101` inclusive) — a genuinely separate database each time, not the persistent dev instance.

**Quality gates:** `ruff format --check .`, `ruff check .`, and `mypy src` all clean across the whole source tree (one formatting-only drift found and fixed in `099_local_authentication.py`/`scripts/foundry_provision.py`, committed separately — no semantic change).

**Full Python suite result:** `pytest -q` (whole `tests/` tree, fresh ephemeral database, no `DND_AI_TEST_DATABASE_URL` override) — **3755 passed, 2 failed, in 1:27:49**. Both failures are pre-existing and unrelated to this branch, confirmed by reproducing each in isolation against unmodified `main` (via a throwaway `git worktree`, deleted after use):

- `tests/database/test_seed_idempotency.py::test_rerunning_the_seed_migration_does_not_duplicate_rows` — fails on `main` identically; migration `024_campaign_ruleset_version`'s downgrade path (`ALTER TABLE campaign.campaigns ALTER COLUMN ruleset_id SET NOT NULL`) fails when re-run against already-seeded data, predating this branch entirely.
- `tests/scenario/test_foundry_sync_commands.py::test_two_operations_on_the_same_target_do_not_starve_a_small_pool` — fails on `main` identically, in isolation, independent of system load (`QueuePool limit of size 1 overflow 0 reached, connection timed out, timeout 15.00`); a pre-existing timing-sensitive concurrency test unrelated to any Workstream 11R change (last touched in Phase 9, commit `b743181`, and not modified since).

Neither failure touches any file this branch changed. No workstream's own regression suite (run individually, between each commit, per the working method) showed any failure at the time it was delivered.

**FoundryVTT module suite:** `cd foundry-module && node --test` — **77/77 passing**, including new coverage for `pairing.mjs` (pairing-code consumption, device-credential exchange, `FoundryAccessTokenCache` refresh/expiry/clear behavior) and `pairing-logic.mjs` (form validation, successful pairing persisting connection metadata + device credential, server-rejection handling without partial persistence).

**CI status:** Not checked for this head — this environment has no `gh` CLI available, and the branch's last 9 commits (workstreams C through the formatting fix) have not been pushed to `origin/phase11r/auth-retrofit`. Verification above is entirely local. Push and CI confirmation are left to the repository owner.

## What remains before Phase 11 can close

Per [PLAN.md §1902](PLAN.md#phase-11-foundry-mvp): *"Phase 11 remains 'Partially implemented' until 11R is delivered, its focused regression suite is green, and `docs/PHASE11_VERIFICATION.md` records a real Foundry v13 run covering same-device restart, second-device pairing, independent revocation, cross-origin transport, and canonical synchronization without duplicate events."*

11R's own code and automated-test delivery is complete (this file's evidence above). **Not performed, and not possible from this environment:** the real Foundry v13 client run itself. This requires a licensed FoundryVTT installation, which this session had no access to. `foundry-module/README.md`'s "Manual live-Foundry verification" section lists the exact eleven-step procedure (module install, pairing, duplicate-turn replay, reload-restores-without-write, cross-campaign device rejection, direct-route rejection, cross-device-credential rejection, CORS preflight success/failure, plain-HTTP rejection) that must be run and recorded here before this checkbox can close. Until that run happens, Phase 11 stays "Partially implemented" per the plan's own exit condition — this is a deliberate, accurate status, not an oversight.

## Deviations from the literal workstream text, with justification

- **Workstream ordering (D before C):** D's schema is a hard prerequisite for C's `resolve_foundry_access_principal` wiring; implementing them in specification order was not possible. No scope changed.
- **`FOUNDRY_DEVICE_AUTH_METHOD` was not built as a general `AuthenticatedPrincipal` type.** The device-credential-to-access-token exchange (`POST /foundry/token`) has exactly one caller and parses its own `Authorization: FoundryDevice <id>.<secret>` header directly rather than going through `get_authenticated_user_id`, since a device credential's only valid action is this one exchange — a principal type would exist to serve a second caller that doesn't exist.
- **`scripts/foundry_provision.py`'s legacy subcommands were removed, not merely deprecated**, per Workstream I item 6's literal "must not... issue the superseded credential." The backend commands they drove (`issue_foundry_system_key`/`link_foundry_identity`) are untouched and still reachable by a direct authenticated API call during any deployment's compatibility window — only this one CLI's surface changed.
