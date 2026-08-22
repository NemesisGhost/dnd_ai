import { DndAiApiError } from "./errors.mjs";

/**
 * The one place an HTTP request is sent and its response parsed into
 * either a plain JSON payload or a thrown `DndAiApiError` — shared by
 * `api-client.mjs` (ordinary campaign-scoped requests, already carrying a
 * bearer credential) and `pairing.mjs` (the pairing-code and device-token
 * exchange requests, which authenticate differently and run before any
 * ordinary credential exists). Factored out so both places parse the
 * server's fixed error envelope (`src/dnd_ai/api/errors.py`) identically,
 * rather than two independently-maintained copies of the same
 * try/catch-and-classify logic.
 */
export async function sendJsonRequest(fetchImpl, url, { method, headers, body } = {}) {
  let response;
  try {
    response = await fetchImpl(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    // fetch() itself throws for a network-level failure (DNS, TLS,
    // connection refused, ...) before any HTTP response exists at all —
    // status 0 distinguishes this from a real 5xx, though both are
    // equally retryable (DndAiApiError's own constructor).
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
    // No body, or a non-JSON body (e.g. a proxy's own HTML error page) —
    // payload stays null; the branch below already handles that (envelope
    // fields default to a generic message).
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

export function stripTrailingSlash(url) {
  return url.endsWith("/") ? url.slice(0, -1) : url;
}
