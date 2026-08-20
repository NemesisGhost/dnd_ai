import { getConnectionSettings, setConnectionSettings, validateConnectionSettings } from "../settings.mjs";

/**
 * The pure, Foundry-Application-independent half of the connection-setup
 * form — deliberately split from `connection-setup-app.mjs` (which
 * `extends foundry.applications.api.ApplicationV2`) so this logic is
 * importable and testable under Node without a real Foundry runtime.
 * Merely importing a file whose class heritage clause references the
 * global `foundry` object evaluates that reference immediately at
 * module-load time, before any test ever instantiates anything — so the
 * Application subclass itself must live in a file this module's test
 * suite never imports.
 */

/** Masks a stored credential for display — never re-shows the value
 * that was saved, only how many characters it has and its last 4, so a
 * GM can confirm *something* is configured without the full secret
 * being visible on screen (or captured in a screenshot) every time the
 * form is opened. */
export function maskCredential(rawCredential) {
  if (!rawCredential) {
    return "";
  }
  if (rawCredential.length <= 4) {
    return "*".repeat(rawCredential.length);
  }
  return `${"*".repeat(rawCredential.length - 4)}${rawCredential.slice(-4)}`;
}

/** Builds the template context from current settings — pure function,
 * directly testable. */
export function prepareConnectionSetupContext({ settingsApi = game.settings } = {}) {
  const settings = getConnectionSettings({ settingsApi });
  return {
    apiBaseUrl: settings.apiBaseUrl,
    externalSystemId: settings.externalSystemId,
    campaignId: settings.campaignId,
    maskedCredential: maskCredential(settings.systemCredential),
    hasCredential: Boolean(settings.systemCredential),
  };
}

/** Validates and persists a submitted form's data. `formData` is a plain
 * object with the four field values as strings (Foundry's own
 * `FormDataExtended#object` shape) — `newCredential` is only present
 * when the GM actually typed a new value; an empty/absent value leaves
 * the previously-stored credential untouched, since the masked display
 * field is never round-tripped back into the setting itself. Returns
 * `{ok: true}` or `{ok: false, problems: string[]}` (localization keys,
 * matching `settings.mjs`'s `validateConnectionSettings`) — the caller
 * decides how to surface `problems` (form field errors in Foundry; a
 * plain array in tests). */
export async function submitConnectionSetup(formData, { settingsApi = game.settings } = {}) {
  const current = getConnectionSettings({ settingsApi });
  const candidate = {
    apiBaseUrl: formData.apiBaseUrl?.trim() ?? "",
    externalSystemId: formData.externalSystemId?.trim() ?? "",
    campaignId: formData.campaignId?.trim() ?? "",
    systemCredential: formData.newCredential ? formData.newCredential.trim() : current.systemCredential,
  };
  const problems = validateConnectionSettings(candidate);
  if (problems.length > 0) {
    return { ok: false, problems };
  }
  await setConnectionSettings(candidate, { settingsApi });
  return { ok: true };
}
