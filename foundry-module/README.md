# D&D AI Adapter (FoundryVTT module)

Connects a FoundryVTT **dnd5e** world to a [D&D AI platform](../README.md)
campaign: submits combat turns and non-combat HP/condition/resource changes
through the platform's application API, and restores synchronized state on
reconnect. Compatibility: FoundryVTT minimum `13`, verified `13.351`.

This module never talks to PostgreSQL, and never writes canonical state
itself — every change goes through the same application API and
per-device pairing authorization the rest of this repository documents
(`docs/architecture/DATABASE_MODEL.md`'s Foundry hybrid pairing section,
`src/dnd_ai/domain/access.py`'s `AuthenticatedPrincipal`,
`src/dnd_ai/domain/foundry_pairing.py`). See "Trust boundary" below for
what a paired device actually authenticates as, and why — a Critical
defect in an earlier version of this module (a single shared `FoundrySystem`
credential) let any connected player who extracted it authenticate as the
GM; the corrected, individually-paired-device model is described there in
full.

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
- **One writer per world — the GM's own client.** Only the GM's own
  connected client drives sync (`scripts/hooks.mjs`); every other connected
  client only ever observes the result. Pairing itself, however, is
  per-device and per-campaign-member (see "Trust boundary" below) — any
  campaign member can pair their own browser/device, not only the GM.

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
   directory) and enable it for your world (FoundryVTT v13+ required — this
   module uses a `scope: "user"` game setting, only available from v13).

## Pairing a device

The platform has no portal UI yet (that's Phase 13) to drive pairing-code
creation, so a pairing code is currently obtained with a direct API call
against a local-account session — this will move to the portal's own "Pair
a Foundry device" screen once it exists, with no change to the Foundry
module's own side of the flow.

1. **Create a local account session**, if you don't already have one
   (`docs/DEVELOPMENT.md`'s local-auth section covers account creation):

   ```sh
   curl -c cookies.txt -X POST https://dnd-ai.example.com/auth/login \
       -H "Content-Type: application/json" \
       -d '{"email": "you@example.com", "password": "<your password>"}'
   ```

2. **Create a pairing code**, scoped to the campaign and the Foundry
   external system this world was registered as (any active campaign member
   with `campaign.view` can do this for themselves — not only the GM):

   ```sh
   curl -b cookies.txt -X POST \
       https://dnd-ai.example.com/campaigns/<campaign-uuid>/foundry/pairing-codes \
       -H "Content-Type: application/json" \
       -d '{"external_system_id": "<external-system-uuid>", "requested_scopes": ["combat.write"]}'
   # -> {"raw_code": "...", "expires_at": "...", ...} — the code is single-use
   #    and short-lived (5-10 minutes); note it down, it is not shown again.
   ```

3. **In Foundry, on the device being paired**, open **Settings → D&D AI
   Pairing** and enter: the API base URL and the pairing code from step 2.
   Submitting the form exchanges the code for this device's own credential
   (stored `scope: "client"`, this browser profile only — see "Trust
   boundary" below) and reloads the world. A device with no complete
   pairing is also prompted for this automatically on `ready`.

Every other campaign member who wants their own client to drive sync (or,
for a GM, every additional browser/machine they use) repeats steps 2-3 for
themselves — pairing is per-device, not shared.

If the stored device credential is wrong, rotated, or revoked, or the
paired user lacks the needed capability in this campaign, the module
surfaces the server's own specific rejection reason
(`DNDAI.Notifications.SyncFailed`) rather than a silent failure — see
`scripts/errors.mjs`/`scripts/api-client.mjs`.

### Managing paired devices

- **Self-service:** `GET /foundry/devices` lists a user's own paired
  devices; `DELETE /foundry/devices/{id}` revokes one; `POST /foundry/
  devices/{id}/rotate` issues a replacement credential for one (optionally
  with an overlap window so the old secret keeps working briefly while every
  client picks up the new one).
- **GM administration:** `GET /campaigns/{id}/foundry/devices` and `DELETE
  /campaigns/{id}/foundry/devices/{id}` (`access.manage`) let a GM see and
  revoke any device paired within their own campaign — for example, to
  remove a departed player's access. `DELETE /campaigns/{id}/foundry/
  connections/{id}` revokes an entire connection (every device paired under
  it) at once.

All four routes are documented in `src/dnd_ai/api/foundry_pairing.py`.

### Trust boundary

**Each paired device authenticates as exactly the one platform user and
campaign it was paired for — never a caller-selected identity, and never
shared across users.** This is a corrected design, not the original one.
The first cut stored a single `FoundrySystem` credential as a Foundry
**world**-scoped `game.settings` value and let the caller select *which*
linked Foundry user a request authenticated as, via an `X-Foundry-Actor-Id`
header. That combination was a Critical defect: Foundry distributes every
world-scope setting to *every* connected client regardless of `config:
false` (which only hides a setting from the UI, never narrows who receives
it) — so any connected player who inspected their own client's settings (an
ordinary, unprivileged capability; Foundry does not access-control world
settings per client) could extract the shared credential, then simply name
the GM's own, publicly-visible Foundry user id in that header and
authenticate as the GM. `game.user.isGM` checks in this module's own code
only ever suppressed the module's *own* client-side behavior — they were
never, and could never be, enforced server-side against an arbitrary HTTP
request.

Fixed at the credential model, server-side, not with additional
client-side checks:

- **Two credentials, two Foundry `game.settings` scopes, neither shared.**
  Pairing produces non-secret connection metadata (`scripts/pairing.mjs`'s
  `connectionMetadata`, `scope: "user"` — portable across that same D&D AI
  user's own browsers, since it carries no bearer secret) and a device
  credential (`deviceCredential`, `scope: "client"` — this one browser
  profile only, exactly the boundary the old `systemCredential` setting
  needed and didn't have).
- **The access token used on every ordinary request is never persisted at
  all** — `FoundryAccessTokenCache` (`scripts/pairing.mjs`) holds it in an
  in-memory variable only, re-exchanging the stored device credential for a
  fresh one after a page reload rather than ever writing it to
  `game.settings`, any scope included.
- **A device credential authenticates as exactly the user and campaign it
  was paired for** (`dnd_ai.commands.foundry_pairing.consume_foundry_
  pairing_code`) — there is no `X-Foundry-Actor-Id`-equivalent header for
  this scheme, and no code path where a client can claim a different
  identity than the one the pairing code was issued to.
- **Exact-campaign scoping.** A `FoundryAccess` credential authorizes only
  the one campaign its connection was paired against
  (`require_campaign_capability`'s `allow_foundry_access` gate) — narrower
  than the legacy credential's world-wide scope.

Revoke a device (`DELETE /foundry/devices/{id}`, or a GM's `DELETE
/campaigns/{id}/foundry/devices/{id}`) if you suspect it has been exposed;
the device stops minting new access tokens immediately, and any
already-issued access token expires on its own short lifetime shortly
after. Rotating (`POST /foundry/devices/{id}/rotate`) replaces a device's
credential without revoking the connection it belongs to.

### Transport security

Two more corrections, both about how a request actually travels over the
network rather than who it authenticates as — `scope: "client"`/`"user"`
and exact-identity binding above stop a *user* from misusing a credential;
these stop the *network* from ever seeing it.

**HTTPS is mandatory for the API base URL, except on your own machine.**
`scripts/settings.mjs`'s `isSecureApiBaseUrl` (used by the pairing form's
own validation) requires `https://` for `apiBaseUrl` unless the host is a
recognized loopback address (`localhost`, `127.0.0.1`, `[::1]`) — a
private/LAN address (`192.168.x.x`, `10.x.x.x`, ...) is **not** treated as
automatically safe, since anyone else on that network can still observe
plaintext traffic. Both the raw pairing code and the long-lived device
credential travel over this same connection during pairing, and the
short-lived access token on every request after — password-masking or
`scope: "client"` storage protect a credential from other Foundry *users*;
neither protects it from a network observer if the connection itself is
plain HTTP, which is why this check exists independently of both.

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

This module's request-construction, pairing, identifier-binding, retry,
reconnect, and loop-suppression logic is covered by `test/` (`node --test`),
run against the real backend contract via `tests/scenario/test_foundry_
adapter_e2e.py` — but neither substitutes for actually installing this
module in a real FoundryVTT client. Whoever has a licensed FoundryVTT
instance available should run this procedure once and record the result in
`docs/PHASE11_VERIFICATION.md`:

1. Package and install the module (see "Install" above) in a fresh
   FoundryVTT v13 world running the dnd5e system.
2. Register the world as an external system and create a pairing code (see
   "Pairing a device" above) against a real, running instance of this
   platform's API + PostgreSQL 18, then pair the GM's own client.
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
   exchanges the stored device credential for a fresh access token and
   restores the linked actor's HP from the server without submitting any
   write request (check server access logs: one `POST /foundry/token`, then
   only `GET` calls, during reload).
6. Configure a second Foundry world against a *different* registered
   external system in a different platform campaign, then pair a device
   there using a pairing code created for the *first* campaign.
   **Expect:** the pairing itself succeeds (the code is valid), but every
   subsequent sync request from that device fails with a clear "sync
   failed" notification (the server rejects with 404, per `require_
   campaign_capability`'s `allow_foundry_access` exact-campaign check).
7. From this module (or a raw HTTP client using its exact stored device
   credential/access token), attempt to call `POST .../integration/
   external-systems` (register) directly. **Expect:** 403 — the bounded
   adapter-facing route set rejects it regardless of the paired user's own
   capabilities.
8. **Trust-boundary correction, specific to this pass.** In a second
   browser profile (a different player's actual client, or Foundry's own
   "log in as a different user" flow) that has never paired, open the
   Settings sheet for this module. **Expect:** no device credential is
   present and the pairing form is shown — a `scope: "client"` setting is
   never delivered to a browser that didn't set it, unlike the world-scoped
   setting this replaced.
9. From a raw HTTP client, attempt `POST /foundry/token` using one paired
   device's `Authorization: FoundryDevice <id>.<secret>` header but with the
   device id from a *different* paired device appended instead. **Expect:**
   401 — the exchange only succeeds for the exact device/secret pair issued
   together; check `audit.change_log.acting_foundry_device_id` on any
   resulting write to confirm it is always the device that actually
   authenticated, never one merely named in a header.
10. **Transport-security correction, specific to this pass.** With
    FoundryVTT and the platform API served from two different real origins
    (not `localhost` for either), open this module's pairing form in a real
    browser, pair a device, and submit a sync action from the "D&D AI Sync"
    panel. **Expect:** the browser's own network inspector shows a
    successful `OPTIONS` preflight (status 200,
    `Access-Control-Allow-Origin` matching FoundryVTT's exact origin)
    immediately before the real request, and the real request succeeds.
    Then remove that origin from the deployment's
    `DND_AI_FOUNDRY_ALLOWED_ORIGINS` and repeat. **Expect:** the browser
    console reports a CORS error and the request never reaches the
    server's own authentication check.
11. In the pairing form, attempt to save a plain `http://` API base URL
    pointed at the real (non-loopback) deployment host. **Expect:** the
    form rejects it (`DNDAI.Errors.InsecureApiBaseUrl`) without saving or
    submitting the pairing code.

Record: FoundryVTT version, dnd5e system version, platform commit hash,
and the observed result of each step.
