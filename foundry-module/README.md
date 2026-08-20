# D&D AI Adapter (FoundryVTT module)

Connects a FoundryVTT **dnd5e** world to a [D&D AI platform](../README.md)
campaign: submits combat turns and non-combat HP/condition/resource changes
through the platform's application API, and restores synchronized state on
reconnect. Compatibility: FoundryVTT minimum `12`, verified `13.351`.

This module never talks to PostgreSQL, and never writes canonical state
itself — every change goes through the same application API and
`FoundrySystem`-credential authorization/authorization-scoping the rest of
this repository documents (`docs/architecture/DATABASE_MODEL.md` §19.1,
`src/dnd_ai/domain/access.py`'s `AuthenticatedPrincipal`). See "Trust
boundary" below for what that credential actually authenticates as, and
why — a Critical defect in an earlier version of this design let any
connected player who extracted it authenticate as the GM; the corrected
model is described there in full.

## Scope boundary

- **dnd5e only.** HP sync reads/writes `system.attributes.hp.value` — a
  different game system's actor data shape is not supported.
- **Combat turn / condition / resource submission is always an explicit
  action** through the "D&D AI Sync" panel (a token-controls button), not
  inferred automatically from dnd5e's own chat-card/damage-application
  internals. Those internals aren't stable or portable enough to integrate
  against without a live instance to verify against continuously; keeping
  this explicit keeps every code path in this module something the
  automated test suite (`test/`) actually proves correct, rather than a
  best-effort scrape that could silently drift.
- **HP sync is automatic** (the one exception): a GM's direct edit to a
  linked actor's HP on the actor sheet is detected via Foundry's own
  `updateActor` hook and submitted immediately, with loop suppression so
  the server's own confirmed value being written back never re-triggers a
  second submission (`scripts/hooks.mjs`, `scripts/sync-engine.mjs`).
- **One writer per world, and one credential per world — both the GM's.**
  Only the GM's own connected client drives sync (`scripts/hooks.mjs`);
  every other connected client only ever observes the result. This MVP
  deliberately does not deliver true per-player identity delegation — see
  "Trust boundary" below for what that means and why.

## Install

1. Build the distributable zip (reproducible, no network access, no
   dependencies beyond Node 20+):

   ```sh
   cd foundry-module
   node packaging/package.mjs
   # -> dist/foundry-dnd-ai-<version>.zip
   ```

2. In FoundryVTT's own module-management screen, install from that zip (or
   unzip it directly into your Foundry `Data/modules/dnd-ai-adapter/`
   directory) and enable it for your world.

## GM setup

The platform has no portal UI yet (that's Phase 13) to drive the
OIDC-authenticated management endpoints a GM needs before a Foundry world
can connect, so `scripts/foundry_provision.py` (at the repository root, not
inside this module) is the provisioning tool — a thin, OIDC-authenticated
HTTP client, run once per world and once per player:

```sh
# 1. Register this Foundry world as an external system (once per world).
#    Needs canon.edit in the target campaign.
export DND_AI_OIDC_TOKEN=<your OIDC bearer token>
uv run python scripts/foundry_provision.py register \
    --api-base-url https://dnd-ai.example.com \
    --campaign-id <campaign-uuid> \
    --display-name "My Foundry World"
# -> prints external_system_id

# 2. Link the GM's own Foundry account to their existing platform user.
#    Needs access.manage. Must happen BEFORE step 3 — a credential can
#    only be bound to an already-linked Foundry user id (see "Trust
#    boundary" below for why this module is GM-only, not "once per
#    player").
uv run python scripts/foundry_provision.py link-identity \
    --api-base-url https://dnd-ai.example.com \
    --campaign-id <campaign-uuid> \
    --external-system-id <external-system-id-from-step-1> \
    --foundry-user-id <gm-foundry-user-id> \
    --user-id <gm-platform-user-uuid>

# 3. Issue the credential, bound to the GM's platform user linked in step 2.
uv run python scripts/foundry_provision.py issue-key \
    --api-base-url https://dnd-ai.example.com \
    --campaign-id <campaign-uuid> \
    --external-system-id <external-system-id-from-step-1> \
    --foundry-user-id <gm-foundry-user-id>
# -> prints the raw_key, SHOWN ONCE

# (steps 1-3 in one call: `provision --display-name ... --foundry-user-id
# <gm-foundry-user-id> --user-id <gm-platform-user-uuid>`)
```

`<gm-foundry-user-id>` is the GM's own Foundry user id, visible in
Foundry's own Configure Users screen (or `game.user.id` in the GM's own
browser console).

4. In Foundry, **on the GM's own browser/client**, open **Settings → D&D
   AI Connection Setup** (GM only) and enter: the API base URL, the
   `external_system_id` and campaign id from step 1, and the raw key
   printed in step 3. The credential field is password-masked and never
   redisplayed in full once saved, and — see "Trust boundary" below —
   this setting is stored only in this one browser's own profile, never
   distributed to any other connected client.

If the stored credential is wrong/rotated, or the linked platform user
lacks the needed capability in this campaign, the module surfaces the
server's own specific rejection reason (`DNDAI.Notifications.SyncFailed`)
rather than a silent failure — see `scripts/errors.mjs`/
`scripts/api-client.mjs`.

### Trust boundary

**This is a GM-client-only MVP: one credential, bound to exactly one
platform principal (the GM), stored only in the GM's own browser.** True
per-player identity delegation — a Foundry credential that lets *each*
connected player's own actions attribute to their own platform account —
is **not delivered** by this module and is out of scope for this MVP.

This is a corrected design, not the original one. The first cut stored the
system credential as a Foundry **world**-scoped `game.settings` value and
let the caller select *which* linked Foundry user a request authenticated
as, via an `X-Foundry-User-Id` header. That combination was a Critical
defect: Foundry distributes every world-scope setting to *every* connected
client regardless of `config: false` (which only hides a setting from the
UI, never narrows who receives it) — so any connected player who inspected
their own client's settings (an ordinary, unprivileged capability; Foundry
does not access-control world settings per client) could extract the
shared credential, then simply name the GM's own, publicly-visible Foundry
user id in that header and authenticate as the GM. `game.user.isGM` checks
in this module's own code only ever suppressed the module's *own*
client-side behavior — they were never, and could never be, enforced
server-side against an arbitrary HTTP request.

Fixed at the credential model, server-side, not with additional
client-side checks:

- The system credential (`systemCredential`) is now registered `scope:
  "client"` (`scripts/settings.mjs`) — stored only in the one browser
  profile that ran the connection-setup form, never distributed by Foundry
  to any other connected client.
- A `FoundrySystem` credential now authenticates as exactly the one
  platform principal it was bound to when it was issued
  (`dnd_ai.commands.integration.issue_foundry_system_key`'s required
  `foundry_user_id` argument, which must already be linked via
  `link_foundry_identity`) — never a caller-selected identity. The client
  still sends a Foundry user id (renamed `X-Foundry-Actor-Id`, from
  `X-Foundry-User-Id`), but it is recorded only as descriptive
  `audit.change_log.acting_foundry_actor_id` metadata — the server never
  uses it to decide who is authenticated, so changing, omitting, or
  spoofing it cannot change that.
- Because only the GM's own client ever calls the API at all
  (`scripts/hooks.mjs`'s existing "exactly one client drives sync per
  world" design), binding the one issued credential to the GM's own
  platform user is not a new restriction this correction invented — it
  matches how the module already, always behaved. What changed is that the
  *server* now enforces it structurally, rather than the module's own
  `isGM` check merely happening to be the only thing that, in practice,
  ever called the API.

Rotate the credential (`foundry_provision.py issue-key`) if you suspect it
has been exposed; the previous key stops working immediately
(`dnd_ai.commands.integration.issue_foundry_system_key`'s own docstring —
rotation, not addition). Rotating can also re-bind the credential to a
*different* linked Foundry user id in the same call, by passing a
different `--foundry-user-id`.

### Transport security

Two more corrections, both about how a request actually travels over the
network rather than who it authenticates as — `scope: "client"` and
credential-binding above stop a *user* from misusing the credential; these
stop the *network* from ever seeing it.

**HTTPS is mandatory for the API base URL, except on your own machine.**
`scripts/settings.mjs`'s `isSecureApiBaseUrl` (used by the connection-setup
form's own validation) requires `https://` for `apiBaseUrl` unless the host
is a recognized loopback address (`localhost`, `127.0.0.1`, `[::1]`) — a
private/LAN address (`192.168.x.x`, `10.x.x.x`, ...) is **not** treated as
automatically safe, since anyone else on that network can still observe
plaintext traffic. `scripts/foundry_provision.py`'s `--api-base-url`
enforces the identical policy (`_validate_api_base_url`), since it sends an
OIDC bearer token and prints a long-lived `FoundrySystem` credential over
the same connection. Password-masking the credential field and storing it
`scope: "client"` (above) protect it from other Foundry *users*; neither
protects it from a network observer if the connection itself is plain
HTTP — this check exists independently of both, for that reason.

**CORS: the server only accepts browser requests from an explicitly
configured origin.** FoundryVTT and this platform's API are genuinely
separate browser origins in the documented deployment topology
(`docs/LOCAL_DEPLOYMENT.md` — e.g. `https://foundry.example.com` calling
`https://world.example.com/api`), so this module's `fetch()` calls trigger
a real CORS preflight (`OPTIONS`) before every authenticated request.
`src/dnd_ai/api/app.py` installs `CORSMiddleware` against the exact
allowlist in `DND_AI_FOUNDRY_ALLOWED_ORIGINS` (`.env.example`'s "Foundry
CORS" section) — never a wildcard, and never widened by `config: false` or
any client-side setting; if your deployment doesn't list this module's own
origin there, every request fails with a CORS error in the browser
console before it ever reaches the server's own authentication or
authorization checks (which is a *deployment configuration* problem, not a
credential/identity one — check the browser console's exact CORS error,
then your deployment's `DND_AI_FOUNDRY_ALLOWED_ORIGINS`, before assuming
the credential itself is wrong).

## Manual live-Foundry verification

This module's request-construction, identifier-binding, retry, reconnect,
and loop-suppression logic is covered by `test/` (`node --test test/`),
run against the real backend contract via `tests/scenario/test_foundry_
adapter_e2e.py` — but neither substitutes for actually installing this
module in a real FoundryVTT client. Whoever has a licensed FoundryVTT
instance available should run this procedure once and record the result in
`docs/PHASE11_VERIFICATION.md`:

1. Package and install the module (see "Install" above) in a fresh
   FoundryVTT v12 or v13 world running the dnd5e system.
2. Provision it (see "GM setup" above) against a real, running instance of
   this platform's API + PostgreSQL 18.
3. Create two linked actors (`linkActor` via this module's console API or
   a future dedicated UI — see `scripts/sync-engine.mjs`), start a combat
   encounter, and submit a turn through the "D&D AI Sync" panel.
   **Expect:** the target actor's HP updates in Foundry to the server's
   returned value, and `campaign.character_state`/`narrative.events` in
   PostgreSQL reflect the identical change.
4. Submit the exact same turn a second time (same round/turn/actor/target/
   damage). **Expect:** no new `narrative.events` row — `sync_jobs.status`
   shows `completed` with `replayed: true` in the server logs/response.
5. Reload the Foundry world (F5). **Expect:** the module's `ready` hook
   restores the linked actor's HP from the server without submitting any
   write request (check server access logs: only `GET` calls during
   reload).
6. Configure a second Foundry world against a *different* registered
   external system in a different platform world, then temporarily point
   this module's settings at the first world's `external_system_id`/key
   while leaving `campaignId` set to the second world's campaign.
   **Expect:** every request fails with a clear "sync failed" notification
   (the server rejects with 404, per `assert_foundry_system_matches`/
   `require_campaign_capability`'s world-binding check — `ae80a29`).
7. From this module (or a raw HTTP client using its exact stored
   credential/headers), attempt to call `POST .../integration/external-
   systems` (register) directly. **Expect:** 403 — the bounded
   adapter-facing route set rejects it regardless of the linked user's own
   capabilities.
8. **Trust-boundary correction, specific to this pass.** In a second
   browser profile (a different player's actual client, or Foundry's own
   "log in as a different user" flow), open the Settings sheet for this
   module. **Expect:** `systemCredential` is empty/unset — a `scope:
   "client"` setting is never delivered to a browser that didn't set it,
   unlike the world-scoped setting this replaced.
9. From a raw HTTP client, send a request using the real, currently-issued
   credential but with `X-Foundry-Actor-Id` set to some *other* value (a
   different linked Foundry user id, an unlinked/nonexistent one, or the
   header omitted entirely). **Expect:** every variant authenticates as the
   *same* platform user (the credential's own bound principal) — check
   `audit.change_log.actor_user_id` for the resulting row: it must never
   change based on this header, only `acting_foundry_actor_id` (recorded
   verbatim, purely as metadata) does.
10. **Transport-security correction, specific to this pass.** With
    FoundryVTT and the platform API served from two different real origins
    (not `localhost` for either), open this module's connection-setup form
    in a real browser, configure it, and submit a sync action from the "D&D
    AI Sync" panel. **Expect:** the browser's own network inspector shows a
    successful `OPTIONS` preflight (status 200,
    `Access-Control-Allow-Origin` matching FoundryVTT's exact origin)
    immediately before the real request, and the real request succeeds.
    Then remove that origin from the deployment's
    `DND_AI_FOUNDRY_ALLOWED_ORIGINS` and repeat. **Expect:** the browser
    console reports a CORS error and the request never reaches the
    server's own authentication check.
11. In the connection-setup form, attempt to save a plain `http://` API
    base URL pointed at the real (non-loopback) deployment host. **Expect:**
    the form rejects it (`DNDAI.Errors.InsecureApiBaseUrl`) without saving,
    and the same URL passed to `scripts/foundry_provision.py
    --api-base-url` is rejected before any request is sent.

Record: FoundryVTT version, dnd5e system version, platform commit hash,
and the observed result of each step.
