/**
 * DndAiApiError — the one error shape every DndAiApiClient method throws.
 *
 * Mirrors the server's fixed error envelope
 * (`src/dnd_ai/api/errors.py`): `{"error": {"code", "message",
 * "correlation_id", "error_codes"?}}`. `retryable` classifies the failure
 * once, at construction time, so callers (retry.mjs) never re-derive it
 * from a raw HTTP status scattered across call sites — a network failure
 * or a 5xx is retryable; every 4xx (unauthorized, forbidden, not_found,
 * conflict, validation_failed, invalid_request) is not, since retrying an
 * identical request cannot change an authorization or validation outcome.
 */
export class DndAiApiError extends Error {
  /**
   * @param {object} params
   * @param {number} params.status - HTTP status code, or 0 for a network
   *   failure that never reached the server (no response at all).
   * @param {string} params.code - stable error code from the response
   *   envelope (e.g. "forbidden", "conflict"), or "network_error" for a
   *   failure with no response.
   * @param {string} params.message - safe-to-display message from the
   *   response envelope, or a generic network-failure message.
   * @param {string|null} [params.correlationId]
   * @param {string[]|null} [params.errorCodes] - present only for 422
   *   validation failures.
   */
  constructor({ status, code, message, correlationId = null, errorCodes = null }) {
    super(message);
    this.name = "DndAiApiError";
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
    this.errorCodes = errorCodes;
    this.retryable = status === 0 || status >= 500;
  }
}

/** True for the small set of failures item 5 of the sync spec forbids
 * retrying: an authorization failure (401/403/404 — the server's own
 * disclosure-avoiding convention maps "not authorized to know this
 * exists" to 404 too) or a conflicting-payload failure (409). Kept
 * separate from `DndAiApiError.retryable` (which only distinguishes
 * "could a retry ever help" for network/5xx vs. everything else) because
 * callers that want to distinguish *why* a request was rejected — to
 * surface a specific GM-facing message — need the finer classification;
 * `retryable` alone already tells retry.mjs everything it needs. */
export function isAuthorizationOrConflictFailure(error) {
  return (
    error instanceof DndAiApiError &&
    (error.status === 401 || error.status === 403 || error.status === 404 || error.status === 409)
  );
}
