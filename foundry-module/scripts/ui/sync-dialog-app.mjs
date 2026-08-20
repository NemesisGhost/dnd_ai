import { MODULE_ID } from "../settings.mjs";
import { getSyncEngine } from "../hooks.mjs";
import { dispatchSyncAction, prepareSyncDialogContext } from "./sync-dialog-logic.mjs";

/**
 * "D&D AI Sync" manual action panel — submit a combat turn, apply/remove
 * a condition, or adjust a resource for a linked actor. Thin wiring
 * around `sync-dialog-logic.mjs`'s testable dispatch function; see that
 * file's own docstring for why combat/condition/resource sync is always
 * an explicit action here rather than inferred automatically.
 */
export class SyncDialogApp extends foundry.applications.api.HandlebarsApplicationMixin(
  foundry.applications.api.ApplicationV2,
) {
  static DEFAULT_OPTIONS = {
    id: `${MODULE_ID}-sync-dialog`,
    tag: "form",
    window: { title: "DNDAI.SyncDialog.Title", icon: "fa-solid fa-dice-d20" },
    form: { handler: SyncDialogApp.#onSubmit, submitOnChange: false, closeOnSubmit: false },
    position: { width: 420 },
  };

  static PARTS = {
    form: { template: `modules/${MODULE_ID}/templates/sync-dialog.hbs` },
  };

  async _prepareContext() {
    const engine = getSyncEngine();
    return prepareSyncDialogContext(engine, game.actors.contents);
  }

  static async #onSubmit(_event, _form, formData) {
    const engine = getSyncEngine();
    if (!engine) {
      ui.notifications.warn(game.i18n.localize("DNDAI.Notifications.NotConfigured"));
      return;
    }
    const values = formData.object;
    const actor = game.actors.get(values.actorId);
    const target = values.targetId ? game.actors.get(values.targetId) : null;
    try {
      await dispatchSyncAction(engine, values.actionType, {
        actor,
        target,
        combat: game.combat,
        formValues: values,
        worldTimeId: game.time.worldTime,
      });
      ui.notifications.info(game.i18n.localize("DNDAI.Notifications.SyncSubmitted"));
    } catch (error) {
      ui.notifications.error(error.message);
    }
  }
}
