/**
 * game.settings registration and typed accessors for the one remaining
 * ordinary, shared setting this module has: which D&D AI deployment to
 * talk to. Everything identity/credential-related — connection metadata,
 * device credentials, access tokens — moved to `pairing.mjs` (Phase 11R
 * workstream H) when the legacy shared `FoundrySystem` credential this
 * file used to also configure (`externalSystemId`/`campaignId`/
 * `systemCredential`) was replaced by individually paired devices; see
 * that module's own docstring for the full design.
 *
 * `apiBaseUrl` stays `scope: "world"` (shared by every client connected
 * to this world, set once by the GM) and `config: true` (visible on the
 * ordinary Foundry Settings sheet) — it names a deployment, not a
 * credential, so there is nothing here for a world-scoped setting's
 * "every connected client can read it" distribution to leak.
 */

export const MODULE_ID = "dnd-ai-adapter";

const SETTING_API_BASE_URL = "apiBaseUrl";

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

// Recognized loopback development hosts only — never a private/LAN
// address (10.0.0.0/8, 192.168.0.0/16, 172.16.0.0/12, ...), which is not
// automatically safe: a shared network can still observe plaintext
// traffic to it. This is a closed, explicit allowlist, not a heuristic.
// "[::1]" (bracketed) is deliberate, not a typo: WHATWG URL.hostname keeps
// the brackets for an IPv6 literal host, unlike Python's
// urllib.parse.urlsplit().hostname, which strips them — the Python-side
// equivalent (scripts/foundry_provision.py's _LOOPBACK_HOSTS) uses "::1"
// for exactly that reason.
const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

export function isLoopbackHost(hostname) {
  return typeof hostname === "string" && LOOPBACK_HOSTS.has(hostname.toLowerCase());
}

/** Transport-security policy for the configured API base URL, on top of
 * `isValidHttpUrl`'s plain shape check: `https:` is always accepted;
 * `http:` is accepted only for a recognized loopback host
 * (`isLoopbackHost`). Both the paired device secret (`pairing.mjs`) and
 * the short-lived access token it is exchanged for travel in the
 * `Authorization` header on every request this module makes — over plain
 * HTTP to any non-loopback host, a network observer can read either
 * outright, so this check applies regardless of which credential a given
 * request happens to carry. */
export function isSecureApiBaseUrl(value) {
  if (!isValidHttpUrl(value)) {
    return false;
  }
  const parsed = new URL(value);
  return parsed.protocol === "https:" || isLoopbackHost(parsed.hostname);
}

/** Registers every setting this module reads. Call once, from
 * `Hooks.once("init", ...)` — Foundry itself enforces "register during
 * init," so this is never called lazily on demand. */
export function registerSettings({ settingsApi = game.settings } = {}) {
  settingsApi.register(MODULE_ID, SETTING_API_BASE_URL, {
    name: "DNDAI.Settings.ApiBaseUrl.Name",
    hint: "DNDAI.Settings.ApiBaseUrl.Hint",
    scope: "world",
    config: true,
    type: String,
    default: "",
  });
}

export function getApiBaseUrl({ settingsApi = game.settings } = {}) {
  return settingsApi.get(MODULE_ID, SETTING_API_BASE_URL);
}

export async function setApiBaseUrl(value, { settingsApi = game.settings } = {}) {
  await settingsApi.set(MODULE_ID, SETTING_API_BASE_URL, value);
}

/** Validates the one setting needed before pairing (or any API call) can
 * be attempted, returning a list of human-readable problems (empty =
 * ready). Used both by the pairing form (before submitting a code) and by
 * `hooks.mjs` at ready-time. */
export function validateApiBaseUrl(apiBaseUrl) {
  const problems = [];
  if (!isValidHttpUrl(apiBaseUrl)) {
    problems.push("DNDAI.Errors.InvalidApiBaseUrl");
  } else if (!isSecureApiBaseUrl(apiBaseUrl)) {
    // Well-formed but plain HTTP to a non-loopback host — a real,
    // structural mismatch, not a malformed-URL problem, so it gets its
    // own message rather than reusing InvalidApiBaseUrl.
    problems.push("DNDAI.Errors.InsecureApiBaseUrl");
  }
  return problems;
}
