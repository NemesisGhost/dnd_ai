# Platform Administrator Recovery

Authoritative operator reference for recovering from the loss of the
platform's last active administrator, and for the standing practice that
makes that recovery unnecessary in the first place: promoting a second
administrator early. See
[PHASE13E_ACCESS_CONTRACT.md](../PHASE13E_ACCESS_CONTRACT.md) for the
account-lifecycle contract this recovery path sits underneath.

## Why this exists (D-10)

The system `admin` role (`security.user_system_roles`, [ADR 0020](../adr/0020-scoped-system-world-and-campaign-roles.md)) is granted to an *existing*
account by exactly one path by default: **`scripts/grant_platform_administrator.py`**.
No API route and no portal control ever promotes an account — the same
"trusted infrastructure, never over HTTP" boundary
[`scripts/bootstrap_admin.py`](../../scripts/bootstrap_admin.py) and
`security.timeline_bootstrap_grants` already establish for their own
analogous first-campaign entitlement.

Without this script, the platform's administrator population has a bus
factor of whoever currently holds an unrevoked `admin` assignment and
can still authenticate. Lose that (a forgotten passphrase with no second
administrator to reset it, or an accidental disable) and the only
recovery is direct SQL against the database. This script replaces that
direct-SQL step with a safe, idempotent, auditable command — it does not
add a new capability the platform lacked, only a supported way to reach
the state an operator would otherwise have to reach by hand.

**Standing recommendation: promote a second administrator as soon as the
platform has one you trust**, so this document is read as routine
practice, not as an incident response. The
[disable-account error](#recognizing-the-invariant-this-script-exists-for)
below is exactly what happens if that recommendation is skipped and the
sole administrator's account is then disabled.

## What the script does and does not do

Like `scripts/bootstrap_admin.py`, this is a **database** client, not an
HTTP client, run by an operator with direct database access:

- reads the connection string from `DND_AI_DATABASE_URL` (or the legacy
  unprefixed `DATABASE_URL`) only — never a command-line argument, since a
  connection string can embed a password and argv is visible in process
  listings and shell history on a shared host;
- resolves the target by **normalized login name** (`security.
  external_identities.subject`, issuer `local`, `revoked_at IS NULL`)
  against a currently-`active` account — never a raw `user_id`, which is
  easy to mistype into the wrong account at a shell prompt;
- acquires the same `platform_administrator_lifecycle` advisory lock every
  administrator-disable transaction already takes, for the whole
  transaction, so this can never race a concurrent disable that is
  mid-way through counting active administrators;
- is idempotent: promoting an already-administrator account is a
  documented no-op, not an error;
- writes one `audit.change_log` row (`command_name =
  'grant_platform_administrator'`, `actor_service` naming the script,
  no `actor_user_id` — there is no authenticated principal for an operator
  at a shell prompt) for a promotion that actually changed something;
  the idempotent no-op path writes nothing new;
- has **no `--apply`-free destructive mode and no demotion counterpart**.
  There is no `revoke_platform_administrator` command: the
  last-active-administrator invariant already blocks disabling the sole
  remaining administrator, and demotion has no recovery story that
  promotion does not already cover. If a real need for demotion appears,
  it is a new, separately-reviewed command — do not attempt it by hand
  against the database.

## Usage

Preview first — this changes nothing:

```bash
uv run python scripts/grant_platform_administrator.py --login-name gm2
```

```
Preview (no changes made):
  user_id: <uuid>
  login_name: gm2
  display_name: <current display name>
  currently_platform_administrator: False
  Re-run with --apply to promote this account.
```

Promote once the preview looks right:

```bash
uv run python scripts/grant_platform_administrator.py --login-name gm2 --apply
```

```
user_id: <uuid>
login_name: gm2
Promoted to platform administrator.
```

Re-running the same command against an account that is now an
administrator is a safe no-op:

```
user_id: <uuid>
login_name: gm2
Already a platform administrator -- no change made.
```

An unknown or platform-disabled login name, or one with no unrevoked
local identity, is refused with a generic "no active local account was
found" message and exit code `1` — this script does not disclose which of
those three applies, matching this codebase's existing non-disclosure
posture for account lookups.

## Recognizing the invariant this script exists for

If an operator attempts to disable the platform's only active
administrator (through `POST /admin/accounts/{id}/disable` or any future
portal control), the request is refused with:

> This is the platform's only active administrator account and cannot be
> disabled. Promoting a second administrator requires direct database
> access — see the platform administrator recovery runbook.

That message is this document. If you see it, either cancel the disable
and instead run this script against a *different* account to create a
second administrator first, or — if the disable is genuinely intended and
a second administrator already exists but wasn't the one attempting the
disable — retry from that second administrator's own session.

## Verifying a promotion took effect

Confirm the promoted account can now reach the admin surface:

```bash
uv run python scripts/grant_platform_administrator.py --login-name gm2
```

The preview should now report `currently_platform_administrator: True`.
Separately, sign in as that account through the portal and confirm
`GET /auth/session` lists `accounts.manage` in `global_capabilities` and that
`GET /admin/accounts` succeeds (200, not the non-disclosing 404 a
non-administrator receives).

## Automated coverage

`tests/database/test_grant_platform_administrator.py` covers: promoting
an active account; the idempotent no-op on an already-administrator
account; refusing an unknown login name, a platform-disabled account, and
an account with no unrevoked local identity — all with the identical
generic error; concurrent promotion and disablement serializing on the
shared advisory lock (real independent connections, real PostgreSQL
locks); and that `LastActivePlatformAdministratorError`'s message no
longer advises the impossible "activate another administrator" remedy.

## Related recoveries (scoped roles, ADR 0020)

The Administrator role grants no world or campaign access, so two further recoveries
exist. Each is an operator script that needs an active Administrator, a mandatory
reason, and writes one audit row with the Administrator as actor. Each refuses an
aggregate that is not actually stranded, so it can never take over a healthy world or
campaign, and neither reads any content.

- **A world nobody can manage** (its only Owner's account was disabled, or the Owner lost the system `gm` role):
  `uv run python scripts/recover_world_ownership.py --list-stranded`, then
  `--world-id <uuid> --admin-login <admin> --new-owner-login <gm> --reason "..."` (preview), and `--apply`.
  The new Owner must be an active account holding system GM.
- **A campaign with no access manager on an active account:**
  `uv run python scripts/recover_campaign_access_manager.py --campaign-id <uuid> --admin-login <admin> --new-manager-login <login> --reason "..."` (preview), and `--apply`.
  The new manager receives the `campaign_owner` role and a membership if they had none.

The disable response and the Platform Accounts list report the affected IDs and counts.
