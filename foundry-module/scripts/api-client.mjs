import { sendJsonRequest, stripTrailingSlash } from "./http.mjs";

/** Redacts a headers object for anything that might ever be logged —
 * used defensively even though no call site in this module currently
 * logs headers at all; the credential must never reach `console.*`
 * under any code path, now or after a future edit. */
export function redactHeaders(headers) {
  const redacted = { ...headers };
  if (redacted.Authorization) {
    redacted.Authorization = "FoundryAccess <redacted>";
  }
  return redacted;
}

/**
 * The one place every ordinary, campaign-scoped HTTP request to the D&D
 * AI platform is built — every route method below funnels through
 * `_request`, so `Authorization` construction, JSON encoding, and
 * error-envelope parsing happen exactly once, never duplicated per call
 * site. This is also what "preserve the campaign/system authorization
 * protections" means on the client side: nothing here can accidentally
 * omit a header or hit an unscoped path, because there is only one place
 * that builds a request at all. The actual enforcement is, and remains,
 * entirely server-side (`dnd_ai.api.access.require_campaign_capability`'s
 * `allow_foundry_access` gate, `assert_foundry_system_matches`) — this
 * client cannot weaken or substitute for that; it only has to not
 * accidentally defeat its own purpose by sending the wrong campaign/system.
 *
 * `Authorization: FoundryAccess <token>` (Phase 11R workstream H) replaces
 * the legacy `FoundrySystem <externalSystemId>.<systemCredential>` scheme
 * this client used to send. `getAccessToken` (typically `pairing.mjs`'s
 * `FoundryAccessTokenCache.getAccessToken`) resolves a fresh, valid token
 * on every request rather than this client ever holding or caching one
 * itself — the cache's own in-memory-only contract, and its own refresh-
 * on-expiry logic, live entirely in `pairing.mjs`. There is no
 * `X-Foundry-Actor-Id`-equivalent header for this credential type: a
 * paired connection already names its one Foundry user directly
 * (`security.foundry_connections.foundry_user_id`), so there is no
 * claimed-but-unverified actor to record the way the legacy shared
 * credential needed (see `dnd_ai.domain.access.AuthenticatedPrincipal`'s
 * own docstring for that credential's now-closed impersonation defect).
 */
export class DndAiApiClient {
  /**
   * @param {object} deps
   * @param {() => string} deps.getApiBaseUrl
   * @param {() => {campaignId: string, externalSystemId: string}}
   *   deps.getConnection - the paired connection's own campaign/system,
   *   from `pairing.mjs`'s `getConnectionMetadata()`.
   * @param {() => Promise<string>} deps.getAccessToken - resolves a fresh,
   *   valid opaque access token (never the raw device credential).
   * @param {typeof fetch} [deps.fetchImpl] - injectable for tests.
   */
  constructor({ getApiBaseUrl, getConnection, getAccessToken, fetchImpl = fetch }) {
    this._getApiBaseUrl = getApiBaseUrl;
    this._getConnection = getConnection;
    this._getAccessToken = getAccessToken;
    this._fetch = fetchImpl;
  }

  _buildUrl(path, query) {
    const url = new URL(stripTrailingSlash(this._getApiBaseUrl()) + path);
    if (query) {
      for (const [key, value] of Object.entries(query)) {
        if (value !== undefined && value !== null) {
          url.searchParams.set(key, String(value));
        }
      }
    }
    return url.toString();
  }

  async _buildHeaders({ idempotencyKey } = {}) {
    const token = await this._getAccessToken();
    const headers = {
      "Content-Type": "application/json",
      Authorization: `FoundryAccess ${token}`,
    };
    if (idempotencyKey) {
      headers["Idempotency-Key"] = idempotencyKey;
    }
    return headers;
  }

  async _request(method, path, { body, idempotencyKey, query } = {}) {
    const url = this._buildUrl(path, query);
    const headers = await this._buildHeaders({ idempotencyKey });
    return sendJsonRequest(this._fetch, url, { method, headers, body });
  }

  // -- integration routes ---------------------------------------------

  mapExternalIdentifier({ entityId, externalKind, externalId }) {
    const { campaignId, externalSystemId } = this._getConnection();
    return this._request(
      "POST",
      `/campaigns/${campaignId}/integration/external-systems/${externalSystemId}/identifiers`,
      { body: { entity_id: entityId, external_kind: externalKind, external_id: externalId } },
    );
  }

  applyCombatSync(payload) {
    const { campaignId } = this._getConnection();
    return this._request("POST", `/campaigns/${campaignId}/integration/foundry/combat-sync`, {
      body: payload,
    });
  }

  getSyncState({ targetEntityId, targetEncounterId }) {
    const { campaignId, externalSystemId } = this._getConnection();
    return this._request(
      "GET",
      `/campaigns/${campaignId}/integration/external-systems/${externalSystemId}/sync-state`,
      { query: { target_entity_id: targetEntityId, target_encounter_id: targetEncounterId } },
    );
  }

  // -- character-state routes ------------------------------------------

  getCharacter(characterId) {
    const { campaignId } = this._getConnection();
    return this._request("GET", `/campaigns/${campaignId}/characters/${characterId}`);
  }

  adjustHitPoints(characterId, body, idempotencyKey) {
    const { campaignId } = this._getConnection();
    return this._request("POST", `/campaigns/${campaignId}/characters/${characterId}/hit-points`, {
      body,
      idempotencyKey,
    });
  }

  applyCondition(characterId, body, idempotencyKey) {
    const { campaignId } = this._getConnection();
    return this._request("POST", `/campaigns/${campaignId}/characters/${characterId}/conditions`, {
      body,
      idempotencyKey,
    });
  }

  removeCondition(characterId, conditionId, body, idempotencyKey) {
    const { campaignId } = this._getConnection();
    return this._request(
      "POST",
      `/campaigns/${campaignId}/characters/${characterId}/conditions/${conditionId}/remove`,
      { body, idempotencyKey },
    );
  }

  adjustResource(characterId, body, idempotencyKey) {
    const { campaignId } = this._getConnection();
    return this._request("POST", `/campaigns/${campaignId}/characters/${characterId}/resources`, {
      body,
      idempotencyKey,
    });
  }
}
