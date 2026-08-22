import { MODULE_ID, getApiBaseUrl, setApiBaseUrl, validateApiBaseUrl } from "../settings.mjs";
import { consumeFoundryPairingCode, setConnectionMetadata, setDeviceCredential } from "../pairing.mjs";

/**
 * The pure, Foundry-Application-independent half of the pairing form —
 * deliberately split from `pairing-app.mjs` (which `extends foundry.
 * applications.api.ApplicationV2`) so this logic is importable and
 * testable under Node without a real Foundry runtime. Merely importing a
 * file whose class heritage clause references the global `foundry` object
 * evaluates that reference immediately at module-load time, before any
 * test ever instantiates anything — so the Application subclass itself
 * must live in a file this module's test suite never imports.
 *
 * Replaces `connection-setup-logic.mjs` (Phase 11R workstream H): the GM
 * no longer pastes a shared system credential — any campaign member
 * enters a per-user, single-use pairing code obtained from the D&D AI
 * portal, and this module pairs itself as one specific device.
 */

function defaultGenerateDeviceId() {
  if (typeof foundry !== "undefined" && foundry.utils?.randomID) {
    return foundry.utils.randomID();
  }
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `device-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Builds the template context from current settings — pure function,
 * directly testable. Never reflects any paired secret back into the
 * form: pairing is a one-time action per device, not an editable field
 * the way the legacy credential setup allowed rotation from this same
 * form. */
export function preparePairingContext({ settingsApi = game.settings } = {}) {
  return {
    apiBaseUrl: getApiBaseUrl({ settingsApi }),
  };
}

/** Validates and submits a pairing code. `formData` is a plain object
 * with `apiBaseUrl`/`pairingCode` string fields (Foundry's own
 * `FormDataExtended#object` shape). On success, persists the resulting
 * connection metadata (user-scoped) and device credential (client-scoped)
 * and returns `{ok: true}`; on a local validation failure returns
 * `{ok: false, problems: string[]}` (localization keys); on a server-
 * rejected code (unknown, expired, already consumed — all
 * indistinguishable by design, see `dnd_ai.commands.foundry_pairing.
 * PairingCodeNotAcceptableError`'s own docstring) returns `{ok: false,
 * problems: [], error}` so the caller can surface the server's own
 * message. */
export async function submitPairingCode(
  formData,
  { settingsApi = game.settings, gameApi = game, fetchImpl = fetch, generateDeviceId = defaultGenerateDeviceId } = {},
) {
  const apiBaseUrl = formData.apiBaseUrl?.trim() ?? "";
  const rawCode = formData.pairingCode?.trim() ?? "";

  const problems = validateApiBaseUrl(apiBaseUrl);
  if (!rawCode) {
    problems.push("DNDAI.Errors.MissingPairingCode");
  }
  if (problems.length > 0) {
    return { ok: false, problems };
  }

  await setApiBaseUrl(apiBaseUrl, { settingsApi });

  const deviceId = generateDeviceId();
  const foundryVersion = gameApi.release?.display ?? String(gameApi.version ?? "");
  const moduleVersion = gameApi.modules?.get?.(MODULE_ID)?.version ?? null;
  const foundryOrigin = typeof location !== "undefined" ? location.origin : "";

  let result;
  try {
    result = await consumeFoundryPairingCode({
      apiBaseUrl,
      rawCode,
      foundryUserId: gameApi.user.id,
      foundryOrigin,
      deviceLabel: `Foundry ${foundryVersion} device ${deviceId}`,
      moduleVersion,
      foundryVersion,
      fetchImpl,
    });
  } catch (error) {
    return { ok: false, problems: [], error };
  }

  await setConnectionMetadata(
    {
      foundryConnectionId: result.foundry_connection_id,
      campaignId: result.campaign_id,
      externalSystemId: result.external_system_id,
      foundryUserId: gameApi.user.id,
      grantedScopes: result.granted_scopes,
      pairedAt: new Date().toISOString(),
    },
    { settingsApi },
  );
  await setDeviceCredential(
    { foundryDeviceId: result.foundry_device_id, rawDeviceSecret: result.raw_device_secret },
    { settingsApi },
  );

  return { ok: true };
}
