import { DndAiApiError } from "./errors.mjs";

/** Redacts a headers object for anything that might ever be logged —
 * used defensively even though no call site in this module currently
 * logs headers at all; the credential must never reach `console.*`
 * under any code path, now or after a future edit. */
export function redactHeaders(headers) {
  const redacted = { ...headers };
  if (redacted.Authorization) {
    redacted.Authorization = "FoundrySystem <redacted>";
  }
  return redacted;
}

function stripTrailingSlash(url) {
  return url.endsWith("/") ? url.slice(0, -1) : url;
}

/**
 * The one place every HTTP request to the D&D AI platform is built —
 * every route method below funnels through `_request`, so
 * `Authorization`/`X-Foundry-User-Id` construction, JSON encoding, and
 * error-envelope parsing happen exactly once, never duplicated per
 * call site. This is also what "preserve the world/system authorization
 * protections" means on the client side: nothing here can accidentally
 * omit a header or hit an unscoped path, because there is only one place
 * that builds a request at all. The actual enforcement is, and remains,
 * entirely server-side (`dnd_ai.api.access.require_campaign_capability`,
 * `assert_foundry_system_matches`) — this client cannot weaken or
 * substitute for that; it only has to not accidentally defeat its own
 * purpose by sending the wrong campaign/system.
 */
export class DndAiApiClient {
  /**
   * @param {object} deps
   * @param {() => {apiBaseUrl: string, externalSystemId: string,
   *   campaignId: string, systemCredential: string}} deps.getSettings
   * @param {typeof fetch} [deps.fetchImpl] - injectable for tests.
   * @param {() => string} deps.getFoundryUserId - returns the current
   *   Foundry user's own persistent id (`game.user.id` in production).
   */
  constructor({ getSettings, fetchImpl = fetch, getFoundryUserId }) {
    this._getSettings = getSettings;
    this._fetch = fetchImpl;
    this._getFoundryUserId = getFoundryUserId;
  }

  _buildUrl(path, query) {
    const { apiBaseUrl } = this._getSettings();
    const url = new URL(stripTrailingSlash(apiBaseUrl) + path);
    if (query) {
      for (const [key, value] of Object.entries(query)) {
        if (value !== undefined && value !== null) {
          url.searchParams.set(key, String(value));
        }
      }
    }
    return url.toString();
  }

  _buildHeaders({ idempotencyKey } = {}) {
    const { externalSystemId, systemCredential } = this._getSettings();
    const headers = {
      "Content-Type": "application/json",
      Authorization: `FoundrySystem ${externalSystemId}.${systemCredential}`,
      "X-Foundry-User-Id": this._getFoundryUserId(),
    };
    if (idempotencyKey) {
      headers["Idempotency-Key"] = idempotencyKey;
    }
    return headers;
  }

  async _request(method, path, { body, idempotencyKey, query } = {}) {
    const url = this._buildUrl(path, query);
    const headers = this._buildHeaders({ idempotencyKey });

    let response;
    try {
      response = await this._fetch(url, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch {
      // fetch() itself throws for a network-level failure (DNS, TLS,
      // connection refused, ...) before any HTTP response exists at
      // all — status 0 distinguishes this from a real 5xx, though both
      // are equally retryable (DndAiApiError's own constructor).
      throw new DndAiApiError({
        status: 0,
        code: "network_error",
        message: "Could not reach the D&D AI API.",
      });
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch {
      // No body, or a non-JSON body (e.g. a proxy's own HTML error
      // page) — payload stays null; the branches below already handle
      // that (envelope fields default to a generic message).
    }

    if (!response.ok) {
      const envelope = payload && typeof payload === "object" ? payload.error || {} : {};
      throw new DndAiApiError({
        status: response.status,
        code: envelope.code ?? "unknown_error",
        message: envelope.message ?? `Request failed with status ${response.status}.`,
        correlationId: envelope.correlation_id ?? null,
        errorCodes: envelope.error_codes ?? null,
      });
    }

    return payload;
  }

  // -- integration routes ---------------------------------------------

  mapExternalIdentifier({ entityId, externalKind, externalId }) {
    const { campaignId, externalSystemId } = this._getSettings();
    return this._request(
      "POST",
      `/campaigns/${campaignId}/integration/external-systems/${externalSystemId}/identifiers`,
      { body: { entity_id: entityId, external_kind: externalKind, external_id: externalId } },
    );
  }

  applyCombatSync(payload) {
    const { campaignId } = this._getSettings();
    return this._request("POST", `/campaigns/${campaignId}/integration/foundry/combat-sync`, {
      body: payload,
    });
  }

  getSyncState({ targetEntityId, targetEncounterId }) {
    const { campaignId, externalSystemId } = this._getSettings();
    return this._request(
      "GET",
      `/campaigns/${campaignId}/integration/external-systems/${externalSystemId}/sync-state`,
      { query: { target_entity_id: targetEntityId, target_encounter_id: targetEncounterId } },
    );
  }

  // -- character-state routes ------------------------------------------

  getCharacter(characterId) {
    const { campaignId } = this._getSettings();
    return this._request("GET", `/campaigns/${campaignId}/characters/${characterId}`);
  }

  adjustHitPoints(characterId, body, idempotencyKey) {
    const { campaignId } = this._getSettings();
    return this._request("POST", `/campaigns/${campaignId}/characters/${characterId}/hit-points`, {
      body,
      idempotencyKey,
    });
  }

  applyCondition(characterId, body, idempotencyKey) {
    const { campaignId } = this._getSettings();
    return this._request("POST", `/campaigns/${campaignId}/characters/${characterId}/conditions`, {
      body,
      idempotencyKey,
    });
  }

  removeCondition(characterId, conditionId, body, idempotencyKey) {
    const { campaignId } = this._getSettings();
    return this._request(
      "POST",
      `/campaigns/${campaignId}/characters/${characterId}/conditions/${conditionId}/remove`,
      { body, idempotencyKey },
    );
  }

  adjustResource(characterId, body, idempotencyKey) {
    const { campaignId } = this._getSettings();
    return this._request("POST", `/campaigns/${campaignId}/characters/${characterId}/resources`, {
      body,
      idempotencyKey,
    });
  }
}
