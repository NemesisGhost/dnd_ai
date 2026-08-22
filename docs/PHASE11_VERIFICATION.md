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
- **Forward-only migrations.** `099`→`100`→`101`→`102` are pure additions (`102` is data-only — an `UPDATE`, no `ALTER TABLE`); no already-merged migration was edited. `alembic check` reports a single clean head at `102_revoke_foundry_system_keys` with no drift from the SQLAlchemy models.
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

## High-severity findings closed after initial delivery

A follow-up review of the delivered 11R code found two High-severity gaps between what was documented/intended and what was actually enforced. Both are now closed; this section is the record of what was found and how.

### Finding 1: Foundry scopes were persisted but never enforced

`security.foundry_connections.granted_scopes` was written correctly at pairing time, but `resolve_foundry_access_principal` never selected it, `AuthenticatedPrincipal` had no field to carry it, and `require_campaign_capability` never checked it — every `allow_foundry_access=True` route was reachable by any paired connection regardless of what scopes it actually held, silently defeating the entire point of `docs/PLAN.md §23.5`'s "closed and narrow" initial scope set.

Fixed:

- `AuthenticatedPrincipal.foundry_scopes: frozenset[str] | None` (`src/dnd_ai/domain/access.py`) — present if, and only if, `auth_method == FOUNDRY_ACCESS_AUTH_METHOD`, enforced by `__post_init__` as its own independent invariant (deliberately *not* folded into the existing `campaign_id`/`foundry_connection_id`/`foundry_device_id` trio's shared `_FOUNDRY_SYSTEM_WORLD_AUTH_METHODS` gate, so the legacy `FOUNDRY_SYSTEM_AUTH_METHOD` principal can never carry a scope set even by accident).
- `resolve_foundry_access_principal` (`src/dnd_ai/domain/foundry_pairing.py`) now selects `fc.granted_scopes` and populates it fresh on every call — never cached, never frozen onto the access-token row, so narrowing a connection's granted scopes takes effect on its very next request even if the presented access token has not itself expired.
- `require_campaign_capability` (`src/dnd_ai/api/access.py`) gained a `foundry_scope: str | None` parameter, required whenever `allow_foundry_access=True` — enforced by a `ValueError` raised the moment the dependency is constructed (application-startup time, not per-request), so a route added with `allow_foundry_access=True` and no declared scope fails the app's own startup rather than silently granting unscoped access. At request time, a principal whose `foundry_scopes` does not contain the declared `foundry_scope` gets the identical `ForbiddenError` an insufficient application capability already produces — scope is an additional restriction, never a replacement for the ordinary campaign-capability check.
- Every existing `allow_foundry_access=True` route now also declares its scope: `get_character_endpoint` → `encounter_read`; the four `character_state.py` routes → `character_state_sync`; `map_external_identifier_endpoint`/`apply_foundry_combat_sync_endpoint` → `combat_sync`; `sync_state_endpoint` → `sync_status_read`. `location_read` is defined in the closed vocabulary but not yet mapped to any route (no dedicated location-detail Foundry route exists).
- `tests/unit/test_foundry_scope_route_mapping.py` (new): walks the real `create_app()` route tree and asserts the discovered `{(method, path): scope}` set matches a hand-maintained table exactly, in both directions — the explicit, human-reviewed mapping requirement 10 of this correction asked for, independent of the startup-time `ValueError` guardrail.

### Finding 2: FoundrySystem remained permanently accepted and issuable

The legacy `FoundrySystem` credential — meant to be fully superseded by paired-device `FoundryAccess` — was still unconditionally accepted at `get_authenticated_user_id`, every bounded-adapter route still passed `allow_foundry_system=True` alongside the new `allow_foundry_access=True`, and `issue_foundry_system_key_endpoint` remained reachable over HTTP, with no deployment-configurable disabled-by-default switch or deadline anywhere. A still-valid legacy key could bypass every per-device protection (listing, expiry, exact-campaign binding, individual revocation) the pairing model exists to provide, indefinitely.

This repository found no evidence of a real deployed client still depending on `FoundrySystem` — the sole first-party client, `foundry-module/`, was already fully converted to pairing by workstream H before this correction, and this is a pre-release, single-developer project with no evidence of a production tenant. A compatibility window was therefore deliberately not built; the preferred, full-rejection correction was applied instead:

- `get_authenticated_user_id` (`src/dnd_ai/api/auth.py`) now rejects the `FoundrySystem` scheme keyword with `UnauthorizedError()` immediately — before any database lookup, and before the OIDC path's own `get_jwks_client()` is ever reached (which matters: a naive "just fall through to OIDC" fix would reintroduce an unrelated 500 in an OIDC-unconfigured, local-auth-only deployment, instead of the plain 401 a retired scheme must always produce).
- `require_campaign_capability`'s `allow_foundry_system` parameter is removed entirely (not merely defaulted off), along with its world-comparison branch; every route's `allow_foundry_system=True` argument is removed.
- `issue_foundry_system_key_endpoint` (`POST .../foundry-system-key`) is removed from `src/dnd_ai/api/integration.py` entirely — not merely left un-opted-into `allow_foundry_access`. The underlying `dnd_ai.commands.integration.issue_foundry_system_key`/`resolve_foundry_system_principal`/`hash_foundry_system_key` and the `system_key_hash`/`system_key_principal_user_id` columns they read remain defined (expand-and-contract: no schema change, no command deletion), but nothing in the API layer calls any of them any more.
- Migration `102_revoke_foundry_system_keys` (new, forward-only, no schema change): `UPDATE integration.external_systems SET system_key_hash = NULL, system_key_principal_user_id = NULL WHERE system_key_hash IS NOT NULL` — revokes every already-issued legacy key at the data level, defense in depth independent of the code-level rejection above. Downgrade is a deliberate no-op (a cleared key is never restored — see the migration's own docstring).
- `tests/database/test_api_auth.py`, `test_api_integration.py`, `test_api_character_state.py`, `test_api_characters.py`, and `tests/scenario/test_foundry_adapter_e2e.py` all updated: every test that used to prove `FoundrySystem` *succeeded* somewhere is replaced by one proving it is rejected — including with a genuinely valid, fully-bound legacy credential minted through the still-present domain commands directly, and including with OIDC entirely unconfigured (the specific regression a partial fix could reintroduce).

## Verification commands and results

Run against the project's local PostgreSQL 18 (`localhost:5433`, per `.env`'s `DATABASE_URL`):

```bash
alembic -c database/alembic.ini current --verbose   # 102_revoke_foundry_system_keys (head)
alembic -c database/alembic.ini check                # No new upgrade operations detected.
alembic -c database/alembic.ini heads                 # 102_revoke_foundry_system_keys (head) — single head
alembic -c database/alembic.ini downgrade -1          # round-trips 102 -> 101 cleanly (data-only, no schema change)
alembic -c database/alembic.ini upgrade head          # round-trips 101 -> 102 cleanly
ruff format --check .                                 # all files already formatted
ruff check .                                           # All checks passed!
mypy src                                                # Success: no issues found
pytest -q                                               # full tree, ephemeral from-empty database (no DND_AI_TEST_DATABASE_URL override)
```

**Migration chain:** `099_local_authentication` → `100_foundry_pairing` → `101_change_log_foundry_pairing` → `102_revoke_foundry_system_keys`, none editing an already-merged migration. `102` is the High-severity-finding-2 correction (data-only: clears every existing legacy key). `alembic check` against the local dev database (already at head) reports no drift; the downgrade/upgrade round trip for `102` was run explicitly (in addition to the from-empty replay every ephemeral test database performs via `alembic upgrade head` in its own setup, covering the complete chain `094`→`102`).

**Quality gates:** `ruff format --check .`, `ruff check .`, and `mypy src` all clean across the whole source tree.

**Focused Foundry/auth regression suite** (`tests/unit/test_authenticated_principal.py`, `test_foundry_scope_route_mapping.py`; `tests/database/test_api_auth.py`, `test_api_character_state.py`, `test_api_characters.py`, `test_api_integration.py`, `test_foundry_pairing_commands.py`, `test_api_foundry_pairing.py`, `test_foundry_provision.py`; `tests/unit/test_foundry_provision.py`; `tests/scenario/test_foundry_adapter_e2e.py`, `test_foundry_sync_commands.py`) — **219 passed, 1 failed** (the pre-existing pool-starvation flake below; every test touching the two findings' own code passed).

**Full Python suite result:** `pytest -q` (whole `tests/` tree, fresh ephemeral database, no `DND_AI_TEST_DATABASE_URL` override) — **3738 passed, 2 failed, in 1:27:50**. Both failures are the identical pre-existing, unrelated ones recorded at 11R's initial delivery, confirmed by reproducing each in isolation against unmodified `main` (via a throwaway `git worktree`, deleted after use):

- `tests/database/test_seed_idempotency.py::test_rerunning_the_seed_migration_does_not_duplicate_rows` — fails on `main` identically; migration `024_campaign_ruleset_version`'s downgrade path (`ALTER TABLE campaign.campaigns ALTER COLUMN ruleset_id SET NOT NULL`) fails when re-run against already-seeded data, predating this branch entirely.
- `tests/scenario/test_foundry_sync_commands.py::test_two_operations_on_the_same_target_do_not_starve_a_small_pool` — fails on `main` identically, in isolation, independent of system load (`QueuePool limit of size 1 overflow 0 reached, connection timed out, timeout 15.00`); a pre-existing timing-sensitive concurrency test unrelated to any Workstream 11R change (last touched in Phase 9, commit `b743181`, and not modified since).

Neither failure touches any file this branch (including the High-severity findings correction) changed.

**FoundryVTT module suite:** `cd foundry-module && node --test` — **77/77 passing**, unaffected by the High-severity findings correction (backend-only change; no `foundry-module/` source touched).

**CI status:** Not checked for this head — this environment has no `gh` CLI available. Verification above is entirely local. Push and CI confirmation are left to the repository owner.

## What remains before Phase 11 can close

Per [PLAN.md §1902](PLAN.md#phase-11-foundry-mvp): *"Phase 11 remains 'Partially implemented' until 11R is delivered, its focused regression suite is green, and `docs/PHASE11_VERIFICATION.md` records a real Foundry v13 run covering same-device restart, second-device pairing, independent revocation, cross-origin transport, and canonical synchronization without duplicate events."*

11R's own code and automated-test delivery is complete (this file's evidence above), including the two High-severity findings' corrections. **Not performed, and not possible from this environment:** the real Foundry v13 client run itself. This requires a licensed FoundryVTT installation, which this session had no access to. `foundry-module/README.md`'s "Manual live-Foundry verification" section lists the exact thirteen-step procedure (module install, pairing, duplicate-turn replay, reload-restores-without-write, cross-campaign device rejection, direct-route rejection, Foundry-scope enforcement, legacy-credential rejection, cross-device-credential rejection, CORS preflight success/failure, plain-HTTP rejection) that must be run and recorded here before this checkbox can close. Until that run happens, Phase 11 stays "Partially implemented" per the plan's own exit condition — this is a deliberate, accurate status, not an oversight.

## Deviations from the literal workstream text, with justification

- **Workstream ordering (D before C):** D's schema is a hard prerequisite for C's `resolve_foundry_access_principal` wiring; implementing them in specification order was not possible. No scope changed.
- **`FOUNDRY_DEVICE_AUTH_METHOD` was not built as a general `AuthenticatedPrincipal` type.** The device-credential-to-access-token exchange (`POST /foundry/token`) has exactly one caller and parses its own `Authorization: FoundryDevice <id>.<secret>` header directly rather than going through `get_authenticated_user_id`, since a device credential's only valid action is this one exchange — a principal type would exist to serve a second caller that doesn't exist.
- **`scripts/foundry_provision.py`'s legacy subcommands were removed, not merely deprecated**, per Workstream I item 6's literal "must not... issue the superseded credential." At the time of Workstream I, the backend commands they drove (`issue_foundry_system_key`/`link_foundry_identity`) remained reachable by a direct authenticated API call. The subsequent High-severity findings correction went further: `issue_foundry_system_key_endpoint`'s HTTP route is now removed entirely (not merely un-opted-into `allow_foundry_access`), and every existing legacy key was revoked at the data level (migration `102`) — `link_foundry_identity_endpoint` remains reachable, since identity linking is not itself a credential-issuance action.
- **No compatibility-window setting was added for the legacy `FoundrySystem` scheme**, even though the original task framing offered that as an alternative to full rejection. This repository found no evidence of a real deployed client depending on it (the only first-party client was already converted before this correction), so the "no active deployment requires compatibility" branch was taken deliberately, per the explicit instruction not to assume a window is needed merely because tests covered the legacy scheme.
