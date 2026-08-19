/**
 * game.settings registration and typed accessors.
 *
 * Four settings, all `scope: "world"` (shared by every client connected
 * to this world, set once by the GM — not per-browser-profile):
 * `apiBaseUrl`, `externalSystemId`, `campaignId` are `config: true`
 * (visible on the ordinary Foundry Settings sheet, since none of them is
 * secret) — `systemCredential` is `config: false` and only ever set
 * through `ui/connection-setup-app.mjs`'s own form, never the default
 * settings list, so a value that looks like a password field doesn't sit
 * in plain text alongside every other module's ordinary settings. This
 * is "as safely as Foundry permits": Foundry has no secret-vault
 * primitive — a world-scope setting is stored in that world's own
 * `Setting` documents and is readable by anyone with server/file access
 * to the world, exactly like every other Foundry module credential
 * today. `foundry-module/README.md` documents this limitation
 * explicitly rather than silently implying stronger protection than
 * Foundry can actually provide.
 */

export const MODULE_ID = "dnd-ai-adapter";

const SETTING_API_BASE_URL = "apiBaseUrl";
const SETTING_EXTERNAL_SYSTEM_ID = "externalSystemId";
const SETTING_CAMPAIGN_ID = "campaignId";
const SETTING_SYSTEM_CREDENTIAL = "systemCredential";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isValidUuid(value) {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

export function isValidHttpUrl(value) {
  if (typeof value !== "string" || value.length === 0) {
    return false;
  }
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

/** Registers every setting this module reads. Call once, from
 * `Hooks.once("init", ...)` — Foundry itself enforces "register during
 * init," so this is never called lazily on demand. */
export function registerSettings({ settingsApi = game.settings, connectionSetupAppClass } = {}) {
  settingsApi.register(MODULE_ID, SETTING_API_BASE_URL, {
    name: "DNDAI.Settings.ApiBaseUrl.Name",
    hint: "DNDAI.Settings.ApiBaseUrl.Hint",
    scope: "world",
    config: true,
    type: String,
    default: "",
  });
  settingsApi.register(MODULE_ID, SETTING_EXTERNAL_SYSTEM_ID, {
    name: "DNDAI.Settings.ExternalSystemId.Name",
    hint: "DNDAI.Settings.ExternalSystemId.Hint",
    scope: "world",
    config: true,
    type: String,
    default: "",
  });
  settingsApi.register(MODULE_ID, SETTING_CAMPAIGN_ID, {
    name: "DNDAI.Settings.CampaignId.Name",
    hint: "DNDAI.Settings.CampaignId.Hint",
    scope: "world",
    config: true,
    type: String,
    default: "",
  });
  // config: false — deliberately not listed on the ordinary settings
  // sheet; see this module's own docstring above.
  settingsApi.register(MODULE_ID, SETTING_SYSTEM_CREDENTIAL, {
    scope: "world",
    config: false,
    type: String,
    default: "",
  });

  if (connectionSetupAppClass) {
    settingsApi.registerMenu(MODULE_ID, "connectionSetup", {
      name: "DNDAI.Settings.ConnectionSetup.Name",
      label: "DNDAI.Settings.ConnectionSetup.Label",
      hint: "DNDAI.Settings.ConnectionSetup.Hint",
      icon: "fa-solid fa-plug",
      type: connectionSetupAppClass,
      restricted: true,
    });
  }
}

/** Reads all four settings at once — the single accessor api-client.mjs
 * and the UI apps use, so there is exactly one place that knows the
 * setting keys/namespace. */
export function getConnectionSettings({ settingsApi = game.settings } = {}) {
  return {
    apiBaseUrl: settingsApi.get(MODULE_ID, SETTING_API_BASE_URL),
    externalSystemId: settingsApi.get(MODULE_ID, SETTING_EXTERNAL_SYSTEM_ID),
    campaignId: settingsApi.get(MODULE_ID, SETTING_CAMPAIGN_ID),
    systemCredential: settingsApi.get(MODULE_ID, SETTING_SYSTEM_CREDENTIAL),
  };
}

export async function setConnectionSettings(
  { apiBaseUrl, externalSystemId, campaignId, systemCredential },
  { settingsApi = game.settings } = {},
) {
  await settingsApi.set(MODULE_ID, SETTING_API_BASE_URL, apiBaseUrl);
  await settingsApi.set(MODULE_ID, SETTING_EXTERNAL_SYSTEM_ID, externalSystemId);
  await settingsApi.set(MODULE_ID, SETTING_CAMPAIGN_ID, campaignId);
  if (systemCredential !== undefined) {
    await settingsApi.set(MODULE_ID, SETTING_SYSTEM_CREDENTIAL, systemCredential);
  }
}

/** Validates the four settings needed before any API call can be made,
 * returning a list of human-readable problems (empty = ready to
 * connect). Used both by the connection-setup form (before saving) and
 * by main.mjs at ready-time (to surface a clear, specific error instead
 * of letting the first API call fail opaquely). */
export function validateConnectionSettings({
  apiBaseUrl,
  externalSystemId,
  campaignId,
  systemCredential,
}) {
  const problems = [];
  if (!isValidHttpUrl(apiBaseUrl)) {
    problems.push("DNDAI.Errors.InvalidApiBaseUrl");
  }
  if (!isValidUuid(externalSystemId)) {
    problems.push("DNDAI.Errors.InvalidExternalSystemId");
  }
  if (!isValidUuid(campaignId)) {
    problems.push("DNDAI.Errors.InvalidCampaignId");
  }
  if (!systemCredential) {
    problems.push("DNDAI.Errors.MissingCredential");
  }
  return problems;
}
