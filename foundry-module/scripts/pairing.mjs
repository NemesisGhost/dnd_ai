import { MODULE_ID } from "./settings.mjs";
import { sendJsonRequest, stripTrailingSlash } from "./http.mjs";

/**
 * Phase 11R hybrid Foundry pairing (docs/PLAN.md §23.5) — replaces the
 * single shared `FoundrySystem` credential (`scripts/settings.mjs`'s
 * former `externalSystemId`/`campaignId`/`systemCredential`) with an
 * individually paired device and a short-lived, in-memory access token.
 *
 * Two `game.settings` values, deliberately different scopes:
 *
 * - `connectionMetadata` (`scope: "user"`, Foundry v13 — `module.json`'s
 *   `compatibility.minimum` is raised to `"13"` specifically for this)
 *   holds non-secret binding metadata: which connection, campaign,
 *   external system, and Foundry user this D&D AI user is paired as.
 *   Portable across this same user's own browsers/devices, since it
 *   carries no bearer secret of its own — `dnd_ai.commands.foundry_
 *   pairing`'s own "portable user-scoped setting contains no bearer
 *   secret" design (docs/PLAN.md §23.5).
 * - `deviceCredential` (`scope: "client"`, this browser profile only,
 *   never distributed to any other connected client — the identical
 *   security boundary `settings.mjs`'s former `systemCredential` already
 *   established, see that module's own docstring for the full Critical
 *   defect a *world*-scoped credential would reopen) holds the one real
 *   secret this module stores at all: the device's own long-lived
 *   credential, obtained once at pairing time and exchanged for fresh
 *   access tokens afterward.
 *
 * The access token itself is never written to any `game.settings` value,
 * `scope: "client"` included — `FoundryAccessTokenCache` below holds it
 * only in a module-level (in-memory) variable, per docs/PLAN.md §23.5:
 * "It holds the access token in memory only." A page reload always
 * re-exchanges the stored device credential for a new token
 * (`FoundryAccessTokenCache.getAccessToken`) rather than ever persisting
 * one.
 */

const CONNECTION_METADATA_KEY = "connectionMetadata";
const DEVICE_CREDENTIAL_KEY = "deviceCredential";

/** Registers the two pairing-related settings, plus the pairing-form
 * settings menu when `pairingAppClass` is supplied. Call once, alongside
 * `settings.mjs`'s own `registerSettings`, from `Hooks.once("init", ...)`. */
export function registerPairingSettings({ settingsApi = game.settings, pairingAppClass } = {}) {
  settingsApi.register(MODULE_ID, CONNECTION_METADATA_KEY, {
    scope: "user",
    config: false,
    type: Object,
    default: {},
  });
  settingsApi.register(MODULE_ID, DEVICE_CREDENTIAL_KEY, {
    scope: "client",
    config: false,
    type: Object,
    default: {},
  });

  if (pairingAppClass) {
    settingsApi.registerMenu(MODULE_ID, "pairing", {
      name: "DNDAI.Settings.Pairing.Name",
      label: "DNDAI.Settings.Pairing.Label",
      hint: "DNDAI.Settings.Pairing.Hint",
      icon: "fa-solid fa-plug",
      type: pairingAppClass,
      restricted: false,
    });
  }
}

/** `{foundryConnectionId, campaignId, externalSystemId, foundryUserId,
 * grantedScopes, pairedAt}`, or `{}` if this user has never paired. */
export function getConnectionMetadata({ settingsApi = game.settings } = {}) {
  return settingsApi.get(MODULE_ID, CONNECTION_METADATA_KEY) ?? {};
}

export async function setConnectionMetadata(metadata, { settingsApi = game.settings } = {}) {
  await settingsApi.set(MODULE_ID, CONNECTION_METADATA_KEY, metadata);
}

/** `{foundryDeviceId, rawDeviceSecret}`, or `{}` if this specific
 * browser/device has never paired — never migrated from a legacy
 * `systemCredential` world setting under any circumstance (docs/PLAN.md
 * Workstream 11R item 6: "Never migrate a raw FoundrySystem secret into
 * user scope"), since only a hash of any old secret ever existed
 * server-side to migrate from in the first place. */
export function getDeviceCredential({ settingsApi = game.settings } = {}) {
  return settingsApi.get(MODULE_ID, DEVICE_CREDENTIAL_KEY) ?? {};
}

export async function setDeviceCredential(credential, { settingsApi = game.settings } = {}) {
  await settingsApi.set(MODULE_ID, DEVICE_CREDENTIAL_KEY, credential);
}

export async function clearPairing({ settingsApi = game.settings } = {}) {
  await setConnectionMetadata({}, { settingsApi });
  await setDeviceCredential({}, { settingsApi });
}

/** True only when both settings carry a complete pairing — a connection
 * with no device credential (or vice versa) is not usable. */
export function isPaired({ settingsApi = game.settings } = {}) {
  const metadata = getConnectionMetadata({ settingsApi });
  const credential = getDeviceCredential({ settingsApi });
  return Boolean(
    metadata.foundryConnectionId &&
      metadata.campaignId &&
      metadata.externalSystemId &&
      credential.foundryDeviceId &&
      credential.rawDeviceSecret,
  );
}

/** `POST /foundry/pair` (docs/PLAN.md §23.5 steps 3-4) — consumes a raw
 * pairing code the user obtained from the D&D AI portal. Public: no
 * `Authorization` header at all, since the code itself is the credential
 * and no device/session exists yet to authenticate with. Returns the
 * server's full response body (`foundry_connection_id`, `foundry_
 * device_id`, `raw_device_secret`, `raw_access_token`, `campaign_id`,
 * `external_system_id`, `granted_scopes`, ...) — the caller is
 * responsible for persisting the connection/device halves via
 * `setConnectionMetadata`/`setDeviceCredential` and seeding
 * `FoundryAccessTokenCache` with the initial access token, exactly once,
 * since this raw device secret is never shown again after this call. */
export async function consumeFoundryPairingCode({
  apiBaseUrl,
  rawCode,
  foundryUserId,
  foundryOrigin,
  deviceLabel,
  moduleVersion = null,
  foundryVersion = null,
  fetchImpl = fetch,
}) {
  const url = `${stripTrailingSlash(apiBaseUrl)}/foundry/pair`;
  return sendJsonRequest(fetchImpl, url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: {
      raw_code: rawCode,
      foundry_user_id: foundryUserId,
      foundry_origin: foundryOrigin,
      device_label: deviceLabel,
      module_version: moduleVersion,
      foundry_version: foundryVersion,
    },
  });
}

/** `POST /foundry/token` (docs/PLAN.md §23.5 step 6) — exchanges the
 * stored device credential for a fresh access token.
 * `Authorization: FoundryDevice <foundryDeviceId>.<rawDeviceSecret>`, the
 * one scheme this module ever sends the long-lived device secret with;
 * every ordinary campaign-scoped request instead sends the short-lived
 * access token this call returns (`Authorization: FoundryAccess <token>`,
 * `api-client.mjs`'s own concern). */
export async function exchangeFoundryDeviceCredential({
  apiBaseUrl,
  foundryDeviceId,
  rawDeviceSecret,
  fetchImpl = fetch,
}) {
  const url = `${stripTrailingSlash(apiBaseUrl)}/foundry/token`;
  return sendJsonRequest(fetchImpl, url, {
    method: "POST",
    headers: { Authorization: `FoundryDevice ${foundryDeviceId}.${rawDeviceSecret}` },
  });
}

// A token is treated as expired this far ahead of its real expiry, so a
// request already in flight when the token is close to expiring never
// races the server's own clock — better to refresh a little early than
// to have a request fail mid-flight with a credential that expired while
// it was still on the wire.
const ACCESS_TOKEN_REFRESH_MARGIN_MS = 60_000;

/** Holds the current Foundry access token in memory only — never in any
 * `game.settings` value, per this module's own docstring above. One
 * instance per Foundry session (created in `hooks.mjs`'s `ready` handler,
 * discarded on page reload along with everything else in memory), shared
 * by every `DndAiApiClient` request through `getAccessToken`. */
export class FoundryAccessTokenCache {
  constructor() {
    this._token = null; // {rawAccessToken, expiresAtMs} | null
  }

  _isValid(nowMs) {
    return this._token !== null && this._token.expiresAtMs - ACCESS_TOKEN_REFRESH_MARGIN_MS > nowMs;
  }

  /** Returns a still-valid access token, exchanging the stored device
   * credential for a fresh one first if the cached token is missing or
   * within its refresh margin of expiring. Throws a plain `Error` (not a
   * `DndAiApiError` — this is a local precondition failure, not a server
   * response) if no device credential is stored at all; the caller (`ready`
   * hook) is responsible for requiring pairing before this is ever
   * reached in practice. */
  async getAccessToken({ apiBaseUrl, settingsApi = game.settings, fetchImpl = fetch, now = Date.now } = {}) {
    const nowMs = now();
    if (this._isValid(nowMs)) {
      return this._token.rawAccessToken;
    }
    const { foundryDeviceId, rawDeviceSecret } = getDeviceCredential({ settingsApi });
    if (!foundryDeviceId || !rawDeviceSecret) {
      throw new Error("D&D AI adapter is not paired on this device — no device credential is stored.");
    }
    const result = await exchangeFoundryDeviceCredential({
      apiBaseUrl,
      foundryDeviceId,
      rawDeviceSecret,
      fetchImpl,
    });
    this._token = {
      rawAccessToken: result.raw_access_token,
      expiresAtMs: Date.parse(result.expires_at),
    };
    return this._token.rawAccessToken;
  }

  clear() {
    this._token = null;
  }
}
