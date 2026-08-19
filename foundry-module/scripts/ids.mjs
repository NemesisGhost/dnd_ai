/**
 * Deterministic idempotency-key derivation.
 *
 * Every retry of the *same logical operation* (a given combat turn, a
 * given HP/condition/resource change) must submit the identical
 * `external_operation_id` (combat-sync) or `Idempotency-Key` header
 * (the other four write routes) — that is the whole point of the
 * server's exactly-once contract (`dnd_ai.commands.integration`'s own
 * docstring; `dnd_ai.api.idempotency`). Generating a fresh
 * `crypto.randomUUID()` per HTTP attempt would defeat that: a retried
 * request would look like a brand-new operation to the server and could
 * double-apply. `stableOperationId` instead hashes the operation's own
 * semantic identity (which never changes across retries, only across
 * genuinely different operations) into a short, stable string.
 *
 * Not a security boundary — a fast, non-cryptographic hash (FNV-1a) is
 * deliberate: nothing here needs to resist forgery (the server's own
 * authorization checks do that); this only needs to be stable and
 * collision-unlikely for one campaign's operation volume.
 */

const FNV_OFFSET_BASIS = 0x811c9dc5;
const FNV_PRIME = 0x01000193;

function fnv1a(text) {
  let hash = FNV_OFFSET_BASIS;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, FNV_PRIME);
  }
  // Unsigned 32-bit, hex-encoded — always 8 lowercase hex characters.
  return (hash >>> 0).toString(16).padStart(8, "0");
}

/** Canonicalizes `parts` (a flat object of primitive values) into a
 * stable string: keys sorted, `null`/`undefined` normalized to the
 * literal string "null" so a value that's absent one attempt and
 * explicitly null the next still hashes identically. Never a JSON
 * `stringify` of the object directly — plain `JSON.stringify` does not
 * sort keys, so insertion order (which can differ between two call sites
 * building "the same" operation) would silently change the hash. */
function canonicalize(parts) {
  const keys = Object.keys(parts).sort();
  return keys.map((key) => `${key}=${parts[key] ?? "null"}`).join("&");
}

/**
 * @param {string} tag - a short, human-readable operation-kind prefix
 *   (e.g. "combat", "hp", "condition-apply") — purely for readability in
 *   server-side logs/idempotency-store rows; carries no meaning to the
 *   hash itself.
 * @param {Record<string, string|number|boolean|null|undefined>} parts -
 *   every field that makes this operation *this specific operation* and
 *   not a different one — e.g. for a combat turn: encounterId,
 *   roundNumber, turnOrder, actorEntityId, targetEntityId, actionKind.
 *   Must NOT include anything that varies between retries of the same
 *   operation (a timestamp, a fresh random value) — including one would
 *   defeat the whole point of this function.
 * @returns {string} 1-255 chars, matches `^[A-Za-z0-9._~-]+$` — safe as
 *   both `external_operation_id` and an `Idempotency-Key` header value.
 */
export function stableOperationId(tag, parts) {
  const safeTag = String(tag).replace(/[^A-Za-z0-9._~-]/g, "-");
  const digest = fnv1a(canonicalize(parts));
  return `${safeTag}-${digest}`;
}
