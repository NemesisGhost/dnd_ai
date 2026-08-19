/**
 * Bounded retry with exponential backoff, for transient failures only.
 *
 * "Bounded" is the whole design: a fixed maximum attempt count and a
 * capped delay, never an unbounded loop — a persistently-down backend
 * must eventually surface to the GM as a real error, not hang the
 * Foundry client forever. Retries are gated on the *caller-supplied*
 * `isRetryable` predicate (defaulting to `DndAiApiError.retryable`, see
 * errors.mjs) so a 401/403/404/409/400/422 — an authorization or
 * conflicting-payload failure, per this module's own sync spec — is
 * never retried; only a network failure or a 5xx is.
 */

const DEFAULT_MAX_ATTEMPTS = 4;
const DEFAULT_BASE_DELAY_MS = 500;
const DEFAULT_FACTOR = 2;

function defaultSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function defaultIsRetryable(error) {
  return Boolean(error && error.retryable);
}

/**
 * @param {() => Promise<T>} fn - the operation to attempt. Called fresh
 *   each attempt (never memoized) so a caller building a request from
 *   current state gets current state on every retry.
 * @param {object} [options]
 * @param {number} [options.maxAttempts] - total attempts, including the
 *   first — never unbounded.
 * @param {number} [options.baseDelayMs] - delay before the second
 *   attempt; each subsequent delay multiplies by `factor`.
 * @param {number} [options.factor]
 * @param {boolean} [options.jitter] - when true, each computed delay is
 *   scaled by a random factor in [0.5, 1.5) so many clients backing off
 *   from the same transient outage don't all retry in lockstep.
 * @param {(ms: number) => Promise<void>} [options.sleep] - injectable so
 *   tests never wait on real timers.
 * @param {(error: unknown) => boolean} [options.isRetryable]
 * @param {() => number} [options.random] - injectable for deterministic
 *   jitter in tests.
 * @returns {Promise<T>}
 * @template T
 */
export async function withRetry(fn, options = {}) {
  const maxAttempts = options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
  const baseDelayMs = options.baseDelayMs ?? DEFAULT_BASE_DELAY_MS;
  const factor = options.factor ?? DEFAULT_FACTOR;
  const jitter = options.jitter ?? true;
  const sleep = options.sleep ?? defaultSleep;
  const isRetryable = options.isRetryable ?? defaultIsRetryable;
  const random = options.random ?? Math.random;

  let attempt = 0;
  let delay = baseDelayMs;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    attempt += 1;
    try {
      return await fn();
    } catch (error) {
      const attemptsRemaining = maxAttempts - attempt;
      if (attemptsRemaining <= 0 || !isRetryable(error)) {
        throw error;
      }
      const thisDelay = jitter ? delay * (0.5 + random()) : delay;
      await sleep(thisDelay);
      delay *= factor;
    }
  }
}
