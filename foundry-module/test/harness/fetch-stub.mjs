/**
 * A `fetch`-shaped stub with a call recorder, standing in for the
 * browser `fetch` `api-client.mjs` wraps.
 *
 * @param {Array|Function} responder - either a fixed array of
 *   `{status, body}` responses (consumed in order; the last one repeats
 *   for any call beyond the array's length), or a function
 *   `(url, init, callNumber) => {status, body}` for dynamic behavior
 *   (e.g. fail twice then succeed, for retry tests). A responder
 *   function may also `throw` to simulate a network-level failure —
 *   real `fetch()` rejects the same way for a connection error.
 */
export function createFetchStub(responder) {
  const calls = [];
  const fn = async (url, init) => {
    const callNumber = calls.length + 1;
    calls.push({ url, init });
    const result = Array.isArray(responder)
      ? responder[Math.min(calls.length - 1, responder.length - 1)]
      : await responder(url, init, callNumber);
    return {
      ok: result.status >= 200 && result.status < 300,
      status: result.status,
      json: async () => result.body,
    };
  };
  fn.calls = calls;
  return fn;
}
