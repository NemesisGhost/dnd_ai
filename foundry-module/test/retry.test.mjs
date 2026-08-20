import assert from "node:assert/strict";
import { test } from "node:test";
import { withRetry } from "../scripts/retry.mjs";
import { DndAiApiError } from "../scripts/errors.mjs";

function noopSleep() {
  return Promise.resolve();
}

test("succeeds on the first attempt with no retries", async () => {
  let calls = 0;
  const result = await withRetry(
    async () => {
      calls += 1;
      return "ok";
    },
    { sleep: noopSleep },
  );
  assert.equal(result, "ok");
  assert.equal(calls, 1);
});

test("retries a retryable failure up to maxAttempts, then throws", async () => {
  let calls = 0;
  await assert.rejects(
    () =>
      withRetry(
        async () => {
          calls += 1;
          throw new DndAiApiError({ status: 503, code: "internal_error", message: "down" });
        },
        { sleep: noopSleep, maxAttempts: 3, jitter: false },
      ),
    /down/,
  );
  assert.equal(calls, 3);
});

test("succeeds after a transient failure, within the attempt bound", async () => {
  let calls = 0;
  const result = await withRetry(
    async () => {
      calls += 1;
      if (calls < 3) {
        throw new DndAiApiError({ status: 0, code: "network_error", message: "unreachable" });
      }
      return "recovered";
    },
    { sleep: noopSleep, maxAttempts: 4, jitter: false },
  );
  assert.equal(result, "recovered");
  assert.equal(calls, 3);
});

test("never retries an authorization failure (403)", async () => {
  let calls = 0;
  await assert.rejects(
    () =>
      withRetry(
        async () => {
          calls += 1;
          throw new DndAiApiError({ status: 403, code: "forbidden", message: "nope" });
        },
        { sleep: noopSleep, maxAttempts: 5 },
      ),
    /nope/,
  );
  assert.equal(calls, 1, "a 403 must not be retried at all");
});

test("never retries a conflicting-payload failure (409)", async () => {
  let calls = 0;
  await assert.rejects(
    () =>
      withRetry(
        async () => {
          calls += 1;
          throw new DndAiApiError({ status: 409, code: "conflict", message: "conflict" });
        },
        { sleep: noopSleep, maxAttempts: 5 },
      ),
    /conflict/,
  );
  assert.equal(calls, 1, "a 409 must not be retried at all");
});

test("never retries a validation failure (400/422)", async () => {
  let calls = 0;
  await assert.rejects(
    () =>
      withRetry(
        async () => {
          calls += 1;
          throw new DndAiApiError({ status: 422, code: "invalid_request", message: "bad request" });
        },
        { sleep: noopSleep, maxAttempts: 5 },
      ),
  );
  assert.equal(calls, 1);
});

test("delay grows by the configured factor between attempts", async () => {
  const delays = [];
  const sleep = async (ms) => {
    delays.push(ms);
  };
  let calls = 0;
  await assert.rejects(() =>
    withRetry(
      async () => {
        calls += 1;
        throw new DndAiApiError({ status: 500, code: "internal_error", message: "x" });
      },
      { sleep, maxAttempts: 4, baseDelayMs: 100, factor: 2, jitter: false },
    ),
  );
  assert.deepEqual(delays, [100, 200, 400]);
});
