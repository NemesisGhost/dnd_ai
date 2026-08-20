import { DndAiApiClient } from "./api-client.mjs";
import { DndAiApiError } from "./errors.mjs";
import { getConnectionSettings, registerSettings, validateConnectionSettings } from "./settings.mjs";
import { SyncEngine } from "./sync-engine.mjs";

/**
 * Foundry hook wiring — the only file in this module that talks to
 * Foundry's global `Hooks`/`game`/`ui` objects directly. Everything it
 * decides ("should this update trigger a sync," "is this our own
 * write-back") is delegated to `SyncEngine`/`settings.mjs`, which are
 * unit-tested without Foundry at all; this file is intentionally thin so
 * the harness tests (`test/loop-suppression.test.mjs`,
 * `test/reconnect.test.mjs`) can exercise the same registration
 * functions against fake `Hooks`/`game`/`ui` objects.
 */

let syncEngine = null;

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
 * connection + restoration. Call once from `main.mjs`. */
export function registerLifecycleHooks({
  hooksApi = Hooks,
  gameApi = game,
  uiApi = ui,
  connectionSetupAppClass = null,
} = {}) {
  hooksApi.once("init", () => {
    registerSettings({ connectionSetupAppClass });
  });

  hooksApi.once("ready", async () => {
    // Exactly one client drives sync per world — the GM's. Every other
    // connected client only ever reads (character sheets already
    // reflect whatever the GM's client last wrote), so there is no
    // multi-writer race between simultaneously-connected players.
    if (!gameApi.user?.isGM) {
      return;
    }
    const settings = getConnectionSettings({ settingsApi: gameApi.settings });
    const problems = validateConnectionSettings(settings);
    if (problems.length > 0) {
      uiApi.notifications.warn(
        gameApi.i18n?.localize?.("DNDAI.Notifications.NotConfigured") ??
          "D&D AI adapter is not fully configured — open its connection settings.",
      );
      return;
    }

    const client = new DndAiApiClient({
      getSettings: () => getConnectionSettings({ settingsApi: gameApi.settings }),
      getFoundryActorId: () => gameApi.user.id,
    });
    syncEngine = new SyncEngine({
      client,
      getSettings: () => getConnectionSettings({ settingsApi: gameApi.settings }),
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
