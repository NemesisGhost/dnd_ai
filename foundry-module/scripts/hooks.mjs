import { DndAiApiClient } from "./api-client.mjs";
import { DndAiApiError } from "./errors.mjs";
import { FoundryAccessTokenCache, getConnectionMetadata, isPaired, registerPairingSettings } from "./pairing.mjs";
import { getApiBaseUrl, registerSettings, validateApiBaseUrl } from "./settings.mjs";
import { SyncEngine } from "./sync-engine.mjs";

/**
 * Foundry hook wiring — the only file in this module that talks to
 * Foundry's global `Hooks`/`game`/`ui` objects directly. Everything it
 * decides ("should this update trigger a sync," "is this our own
 * write-back") is delegated to `SyncEngine`/`settings.mjs`/`pairing.mjs`,
 * which are unit-tested without Foundry at all; this file is
 * intentionally thin so the harness tests (`test/loop-suppression.test.mjs`,
 * `test/reconnect.test.mjs`) can exercise the same registration
 * functions against fake `Hooks`/`game`/`ui` objects.
 */

let syncEngine = null;
let accessTokenCache = null;

export function getSyncEngine() {
  return syncEngine;
}

function handleSyncError(error, { uiApi, gameApi }) {
  if (error instanceof DndAiApiError) {
    const prefix = gameApi.i18n?.localize?.("DNDAI.Notifications.SyncFailed") ?? "D&D AI sync failed";
    uiApi.notifications.error(`${prefix}: ${error.message}`);
  } else {
    uiApi.notifications.warn(error.message);
  }
}

/** Registers `init`/`ready` — settings registration and initial
 * connection + restoration. Call once from `main.mjs`.
 *
 * `pairingAppClass`, when supplied, is rendered when the GM's own client
 * has no complete pairing yet (docs/PLAN.md §23.5: "require pairing on
 * every new browser/device") — a new browser, a cleared client-scoped
 * setting, or a revoked/expired device credential (surfaced as a
 * `getAccessToken()` failure once an actual request is attempted) all
 * land here identically, since none of them can be told apart from "not
 * paired" without first trying to use whatever credential is stored. */
export function registerLifecycleHooks({
  hooksApi = Hooks,
  gameApi = game,
  uiApi = ui,
  pairingAppClass = null,
} = {}) {
  hooksApi.once("init", () => {
    registerSettings();
    registerPairingSettings({ pairingAppClass });
  });

  hooksApi.once("ready", async () => {
    // Exactly one client drives sync per world — the GM's. Every other
    // connected client only ever reads (character sheets already
    // reflect whatever the GM's client last wrote), so there is no
    // multi-writer race between simultaneously-connected players.
    if (!gameApi.user?.isGM) {
      return;
    }

    const apiBaseUrl = getApiBaseUrl({ settingsApi: gameApi.settings });
    if (validateApiBaseUrl(apiBaseUrl).length > 0) {
      uiApi.notifications.warn(
        gameApi.i18n?.localize?.("DNDAI.Notifications.NotConfigured") ??
          "D&D AI adapter is not configured — set its API base URL in Settings.",
      );
      return;
    }

    if (!isPaired({ settingsApi: gameApi.settings })) {
      uiApi.notifications.warn(
        gameApi.i18n?.localize?.("DNDAI.Notifications.NotPaired") ??
          "D&D AI adapter is not paired on this device — open D&D AI Pairing to enter a pairing code.",
      );
      if (pairingAppClass) {
        new pairingAppClass().render(true);
      }
      return;
    }

    accessTokenCache = new FoundryAccessTokenCache();
    const client = new DndAiApiClient({
      getApiBaseUrl: () => getApiBaseUrl({ settingsApi: gameApi.settings }),
      getConnection: () => getConnectionMetadata({ settingsApi: gameApi.settings }),
      getAccessToken: () =>
        accessTokenCache.getAccessToken({
          apiBaseUrl: getApiBaseUrl({ settingsApi: gameApi.settings }),
          settingsApi: gameApi.settings,
        }),
    });
    syncEngine = new SyncEngine({
      client,
      getSettings: () => getConnectionMetadata({ settingsApi: gameApi.settings }),
    });

    try {
      const linkedActors = gameApi.actors.filter((actor) => syncEngine.getLinkedEntityId(actor));
      await syncEngine.restoreFromServer(linkedActors);
      uiApi.notifications.info(
        gameApi.i18n?.localize?.("DNDAI.Notifications.Restored") ?? "D&D AI state restored.",
      );
    } catch (error) {
      handleSyncError(error, { uiApi, gameApi });
    }
  });
}

/** Registers the `preUpdateActor`/`updateActor` pair that drives
 * automatic HP sync with loop suppression. Split from
 * `registerLifecycleHooks` so tests can register just this pair against
 * a fake `Hooks`/`game`/`ui` and a pre-built `SyncEngine`, without
 * needing `init`/`ready` to have run first.
 *
 * Loop-suppression contract: `SyncEngine.applyHitPoints()` (called after
 * a successful server response) marks the actor "self-updating" for the
 * duration of its own `actor.update()` call, plus one macrotask after —
 * see that method's own docstring. This handler checks
 * `syncEngine.isSelfUpdating(actor.id)` first and returns immediately if
 * true, so the module's own write-back never re-triggers a second
 * outbound submit.
 *
 * Delta computation: Foundry's `updateActor` hook fires with the
 * *change* payload, not the previous value, so a `preUpdateActor`
 * handler stashes the pre-update HP for the same actor id; `updateActor`
 * consumes (and clears) that stash to compute a signed delta —
 * `adjust_hit_points`'s own contract, per `src/dnd_ai/api/character_
 * state.py`, takes a delta, not an absolute value.
 */
export function registerHpSyncHooks({ hooksApi = Hooks, gameApi = game, uiApi = ui, engine } = {}) {
  const pendingHpBefore = new Map();

  hooksApi.on("preUpdateActor", (actor, changes) => {
    if (hasProperty(changes, "system.attributes.hp.value")) {
      pendingHpBefore.set(actor.id, actor.system?.attributes?.hp?.value ?? null);
    }
  });

  hooksApi.on("updateActor", async (actor, changes) => {
    const activeEngine = engine ?? syncEngine;
    const before = pendingHpBefore.get(actor.id);
    pendingHpBefore.delete(actor.id);

    if (!activeEngine || !gameApi.user?.isGM) {
      return;
    }
    if (activeEngine.isSelfUpdating(actor.id)) {
      return;
    }
    const after = getProperty(changes, "system.attributes.hp.value");
    if (after === undefined || before === null || before === undefined) {
      return;
    }
    if (!activeEngine.getLinkedEntityId(actor)) {
      return;
    }
    const delta = after - before;
    if (delta === 0) {
      return;
    }

    try {
      await activeEngine.submitHpChange(actor, { worldTimeId: gameApi.time?.worldTime, delta });
    } catch (error) {
      handleSyncError(error, { uiApi, gameApi });
    }
  });
}

// Minimal, dependency-free stand-ins for `foundry.utils.hasProperty`/
// `getProperty` (dotted-path object access) — avoids depending on the
// full `foundry.utils` namespace being present in the test harness for
// what is, here, a single fixed path.
function getProperty(object, path) {
  return path.split(".").reduce((value, key) => (value === undefined ? undefined : value[key]), object);
}

function hasProperty(object, path) {
  return getProperty(object, path) !== undefined;
}
