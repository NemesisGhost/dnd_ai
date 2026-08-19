import { MODULE_ID } from "../settings.mjs";
import { prepareConnectionSetupContext, submitConnectionSetup } from "./connection-setup-logic.mjs";

/**
 * GM-only connection settings form (`settings.mjs`'s `registerSettings`
 * registers this as a settings *menu*, not an ordinary setting, so the
 * credential field is never displayed inline with every other module's
 * plain-text settings on the default sheet).
 *
 * Thin by design: all the actual validation/masking/persistence logic
 * lives in `connection-setup-logic.mjs`, which has no dependency on the
 * real Foundry `Application` runtime and is what `test/*.test.mjs`
 * exercises directly. This file is Foundry-only wiring around it — not
 * covered by the automated test suite, since `foundry.applications.
 * api.ApplicationV2`'s own rendering pipeline only exists inside a real
 * Foundry client (see `foundry-module/README.md`'s "Manual live-Foundry
 * verification" section).
 */
export class ConnectionSetupApp extends foundry.applications.api.HandlebarsApplicationMixin(
  foundry.applications.api.ApplicationV2,
) {
  static DEFAULT_OPTIONS = {
    id: `${MODULE_ID}-connection-setup`,
    tag: "form",
    window: { title: "DNDAI.Settings.ConnectionSetup.Name", icon: "fa-solid fa-plug" },
    form: { handler: ConnectionSetupApp.#onSubmit, submitOnChange: false, closeOnSubmit: true },
    position: { width: 480 },
  };

  static PARTS = {
    form: { template: `modules/${MODULE_ID}/templates/connection-setup.hbs` },
  };

  async _prepareContext() {
    return prepareConnectionSetupContext();
  }

  static async #onSubmit(_event, _form, formData) {
    const result = await submitConnectionSetup(formData.object);
    if (!result.ok) {
      const message = result.problems.map((key) => game.i18n.localize(key)).join(" ");
      ui.notifications.error(message);
      throw new Error(message);
    }
    ui.notifications.info(game.i18n.localize("DNDAI.Notifications.ConnectionSaved"));
  }
}
