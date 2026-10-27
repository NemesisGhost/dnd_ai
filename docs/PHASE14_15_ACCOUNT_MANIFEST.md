# Phase 14/15 acceptance — account-preservation and rename manifest (CP-11)

Prepared 2026-10-26. Acceptance handoff record. No password, hash, token, cookie or connection secret appears here; sensitive comparisons are reported as pass/fail or counts.

## 1. Source and target identity

| | Source | Target (accounts-only acceptance database) |
|---|---|---|
| Database | `dnd_ai` (PostgreSQL 18.4, 127.0.0.1:5432, oid 16388) — the owner's working database, **not modified** | `dnd_ai_m1415_accept_clean_20261026` (new, created for CP-11; nothing dropped or overwritten) |
| Revision | `138_world_roles_and_use_grants` | `140_clock_advance_details` (migrated from empty, `alembic check`: no drift) |
| Code | — | `9ab549ddbc78cb9b5c1aac9c99f3a967112edc62` |

Source backup: `C:\Users\nemes\dnd_ai_evidence_20261026\cp11\dnd_ai_138_cp11_20261026T164103.dump` (`pg_dump -Fc`, client 18.4, 2,010,585 bytes, SHA-256 `67a53727ebde5692f2e23096b6279fbea4574d19288aa7977cff180a7a26b601`). Recoverability was proven, not assumed: the archive TOC was read (3,439 lines), the dump was restored into the disposable `dnd_ai_m1415_cp11_backupverify_20261026T164103`, and per-table fingerprints (row count + md5 of sorted row text, 218 tables, 2,989 rows) were **identical** to the source (`fp_source_pre.json` = `fp_backupverify.json`).

## 2. What was copied (and what each copy depends on)

Schema dependencies were inspected first (every foreign key into `security.users`). Only these tables received rows:

| Table | Rows | Notes |
|---|---|---|
| `security.users` | 12 | Same `user_id`s. Display names per §3. `lifecycle_status_id` mapped by stable **code** (`active`/`inactive`), not by id. `last_login_at` **not copied** (history). |
| `security.external_identities` | 11 | Local-provider mappings; subject renamed per §3 for the six mapped accounts; unlisted accounts unchanged. `last_authenticated_at` not copied; `claims_snapshot`, `linked_at`, `revoked_at` preserved. No unrelated external-provider identities existed. |
| `security.local_credentials` | 11 | Existing hashes copied verbatim (pass/fail compare: identical). Nothing created, reset or re-hashed. |
| `security.user_system_roles` | 13 | Role mapped by **code** (`admin`, `gm`, `player`). Attribution (`granted_by_user_id`, `revoked_by_user_id`) kept when the referenced user was in the manifest, else NULL. 1 account holds `admin`+`gm`; 11 hold `player`. |

**Not copied:** worlds, timelines, campaigns, memberships (campaign and world), scoped grants and use grants; character relationships and inventory permissions; authored content, game state, events, sources, revisions; invitations; browser sessions (source had 275); activation/reset tokens (source had 12 activation tokens); saved campaign selections and portal preferences; idempotency receipts; historical application audit rows. Development-content seed scripts were **not run**. Migration-managed reference data (system roles, world roles, lifecycle/rule/lookup tables) comes only from the migrations.

## 3. Rename map (applied only in the target)

Resolved through normalized local logins (`lower(trim(subject))`) before any change.

| Source login | Target login | Display name | Status (preserved) | System roles (preserved) |
|---|---|---|---|---|
| `admin` | `admin` | Administrator | active | `admin`, `gm` |
| `phase13e.gm2` | `gm` | Game Master | active | `player` |
| `phase13e.player_a` | `player_a` | Player A | active | `player` |
| `phase13e.observer_a` | `observer` | Observer | active | `player` |
| `phase13e.player_b` | `player_b` | Player B | active | `player` |
| `phase13e.disabled` | `disabled` | Disabled User | inactive | `player` |

Pre-checks passed before the import: all six sources present; no normalized-name collision with any other account; target empty of accounts. User ids, credential hashes, statuses and system-role assignments are unchanged by the rename (verified inside the same transaction; any failure would have rolled back).

**A role-like name does not grant authority.** `gm` holds only the `player` system role; `admin` holds Administrator + Game Master because the *source* administrator did. Neither fact comes from the name.

### Validation and constraints inspected (no product change needed)

| Question | Finding | Evidence |
|---|---|---|
| Is `gm` too short? | Yes **for account creation**: `commands/local_auth.py::_validate_login_name_format` requires 3–64 characters, and `security.user_activation_tokens.ck_..._login_name_format` is `^[a-z0-9._-]{3,64}$`. | `src/dnd_ai/commands/local_auth.py:111-135`; migration 099 |
| Are `admin`/`gm` reserved? | Yes **for creation** (`_RESERVED_LOGIN_NAMES` includes `admin`, `administrator`, `root`, `system`, `gm`, `dnd_ai`, `support`). | same |
| Does sign-in enforce the format? | **No.** `/auth/login` bounds length to 64 and looks up `security.external_identities(issuer='local', subject=…)`; it never calls the creation validator. | `api/local_auth.py:130-140, 339`; `commands/local_auth.py:546` |
| Does the identity table constrain the subject? | **No** check constraint on `external_identities.subject`; only the activation-token table has the format check, and no token exists for these accounts. | information_schema; migration 099 |
| Is there a rename command? | **No.** There is no supported rename path in the application. | grep of commands/API |
| Do the lookup surfaces accept `gm`? | Yes: campaign eligible-account lookup allows 1–64 characters; world-sharing login fields allow 1–200. | `api/access_overview.py:424-450`; `api/world_sharing.py:59-68` |

Conclusion: the renamed names work for sign-in and every membership/sharing lookup without changing validation, so **no prerequisite product change was made** (as the task directed for already-supported names). Because there is no rename command, the rename is an environment-preparation operation on a new disposable database, performed by the import script in the same transaction as the copy. It is not a supported product operation and must not be mistaken for one; creating new accounts with these names remains impossible through the product (by design).

## 4. Additional accounts preserved (reported, not deleted)

Six further accounts were in the source; all are `inactive`, hold only the `player` system role, and keep their ids, display names and (where present) credentials:

| Login | Display name | Notes |
|---|---|---|
| `contmurd528l`, `contmurdsgm9`, `contmurlnn89` | Continuation Tester (×3) | credential present; never signed in |
| `tester1` | Tester 1 | credential present |
| `invite_test` | Invite Test | credential present |
| *(pending activation)* | Testing 1 | no login identity and no credential (unactivated shell) |

## 5. Verification (target)

| Check | Result |
|---|---|
| 12 users with the source `user_id`s; 11 identities; 11 credentials; 13 system-role rows | Pass (counts) |
| Credential hashes identical to source (all 11) | Pass (boolean compare; never printed) |
| Lifecycle status identical per user (by code) | Pass |
| Active system roles identical per user (by code) | Pass |
| Six renamed logins present with the specified display names; none of the old logins remain | Pass |
| At least one usable administrator (`admin`: active, credential present, `admin`+`gm`) | Pass |
| No sessions, tokens, preferences, receipts, worlds, campaigns, world/campaign memberships, invitations, entities | Pass (all 0) |
| Migration reference data intact (4 system roles, 5 world roles; table row counts equal a fresh `140` migration for every table except the four account tables) | Pass |
| Source unchanged after the copy (fingerprints identical before/after; the source had no sessions or connections open) | Pass |
| Checkpoint of the untouched baseline | `accept_clean_baseline_140.dump`, SHA-256 `38f97db4c48e16b57b0d7636f9867bacfd1c046057424634ec05f766180e1825` (TOC read) |

Scripts and raw outputs (no secrets): `C:\Users\nemes\dnd_ai_evidence_20261026\cp11\tools\import_accounts.py`, `import_result.json`, `fp_*.json`.
