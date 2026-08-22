import { MODULE_ID } from "../settings.mjs";
import { preparePairingContext, submitPairingCode } from "./pairing-logic.mjs";

/**
 * The pairing form every campaign member — not only the GM — opens to pair
 * this specific browser/device (docs/PLAN.md §23.5 steps 1-3), registered
 * as a settings menu (`hooks.mjs`'s `registerLifecycleHooks` also renders
 * this automatically on `ready` when the current device has no complete
 * pairing yet).
 *
 * Replaces `connection-setup-app.mjs` (Phase 11R workstream H). Thin by
 * design: all the actual validation/persistence logic lives in
 * `pairing-logic.mjs`, which has no dependency on the real Foundry
 * `Application` runtime and is what `test/*.test.mjs` exercises directly.
 * This file is Foundry-only wiring around it — not covered by the
 * automated test suite, since `foundry.applications.api.ApplicationV2`'s
 * own rendering pipeline only exists inside a real Foundry client (see
 * `foundry-module/README.md`'s "Manual live-Foundry verification" section).
 */
export class PairingApp extends foundry.applications.api.HandlebarsApplicationMixin(
  foundry.applications.api.ApplicationV2,
) {
  static DEFAULT_OPTIONS = {
    id: `${MODULE_ID}-pairing`,
    tag: "form",
    window: { title: "DNDAI.Settings.Pairing.Name", icon: "fa-solid fa-plug" },
    form: { handler: PairingApp.#onSubmit, submitOnChange: false, closeOnSubmit: true },
    position: { width: 480 },
  };

  static PARTS = {
    form: { template: `modules/${MODULE_ID}/templates/pairing.hbs` },
  };

  async _prepareContext() {
    return preparePairingContext();
  }

  static async #onSubmit(_event, _form, formData) {
    const result = await submitPairingCode(formData.object);
    if (!result.ok) {
      const message = result.error
        ? result.error.message
        : result.problems.map((key) => game.i18n.localize(key)).join(" ");
      ui.notifications.error(message);
      throw new Error(message);
    }
    ui.notifications.info(game.i18n.localize("DNDAI.Notifications.Paired"));
    // The connection/device settings just written are only picked up by
    // hooks.mjs's own ready handler, which already ran once this session —
    // reload so it re-runs against the newly paired state, the same
    // "settings that require a restart" pattern used elsewhere in the
    // Foundry ecosystem.
    window.location.reload();
  }
}
