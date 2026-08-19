# D&D AI Adapter (FoundryVTT module)

Connects a FoundryVTT **dnd5e** world to a [D&D AI platform](../README.md)
campaign: submits combat turns and non-combat HP/condition/resource changes
through the platform's application API, and restores synchronized state on
reconnect. Compatibility: FoundryVTT minimum `12`, verified `13.351`.

This module never talks to PostgreSQL, and never writes canonical state
itself — every change goes through the same application API and
`FoundrySystem`-credential authorization/authorization-scoping the rest of
this repository documents (`docs/architecture/DATABASE_MODEL.md` §19.1,
`src/dnd_ai/domain/access.py`'s `AuthenticatedPrincipal`).

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
- **One writer per world.** Only the GM's own connected client drives sync;
  every other connected client only ever observes the result.

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
uv run python scripts/foundry_provision.py provision \
    --api-base-url https://dnd-ai.example.com \
    --campaign-id <campaign-uuid> \
    --display-name "My Foundry World"
# -> prints external_system_id and a raw_key, SHOWN ONCE

# 2. Link every Foundry user who will connect (including the GM's own
#    account) to their existing platform user. Needs access.manage.
uv run python scripts/foundry_provision.py link-identity \
    --api-base-url https://dnd-ai.example.com \
    --campaign-id <campaign-uuid> \
    --external-system-id <external-system-id-from-step-1> \
    --foundry-user-id <foundry-user-id> \
    --user-id <platform-user-uuid>
```

`<foundry-user-id>` is that player's Foundry user id, visible in Foundry's
own Configure Users screen (or `game.user.id` in that player's own browser
console).

3. In Foundry, open **Settings → D&D AI Connection Setup** (GM only) and
   enter: the API base URL, the `external_system_id` and campaign id from
   step 1, and the raw key printed in step 1. The credential field is
   password-masked and never redisplayed in full once saved — see
   "Credential storage" below for what protection that actually provides.

If a player's Foundry account was never linked (step 2 skipped), or the
stored credential is wrong/rotated, or the linked platform user lacks the
needed capability in this campaign, the module surfaces the server's own
specific rejection reason (`DNDAI.Notifications.SyncFailed`) rather than a
silent failure — see `scripts/errors.mjs`/`scripts/api-client.mjs`.

### Credential storage

Foundry has no secret-vault primitive. The system credential is stored as
an ordinary world-scoped Foundry setting (`config: false`, so it does not
appear on the default settings list) — readable by anyone with server or
file access to the world, exactly like every other Foundry module's own
stored credentials today. Rotate it (`foundry_provision.py issue-key`)
if you suspect it has been exposed; the previous key stops working
immediately (`dnd_ai.commands.integration.issue_foundry_system_key`'s own
docstring — rotation, not addition).

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

Record: FoundryVTT version, dnd5e system version, platform commit hash,
and the observed result of each step.
