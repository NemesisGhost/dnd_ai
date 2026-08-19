import assert from "node:assert/strict";
import { test } from "node:test";
import { DndAiApiClient } from "../scripts/api-client.mjs";
import { DndAiApiError } from "../scripts/errors.mjs";
import { createFetchStub } from "./harness/fetch-stub.mjs";

const SETTINGS = {
  apiBaseUrl: "https://dnd-ai.example.com",
  externalSystemId: "11111111-1111-1111-1111-111111111111",
  campaignId: "22222222-2222-2222-2222-222222222222",
  systemCredential: "super-secret-key",
};

function makeClient(fetchImpl, settings = SETTINGS) {
  return new DndAiApiClient({
    getSettings: () => settings,
    fetchImpl,
    getFoundryActorId: () => "foundry-user-42",
  });
}

test("mapExternalIdentifier sends the correct method, path, headers, and body", async () => {
  const fetchImpl = createFetchStub([{ status: 200, body: { external_identifier_id: "id-1" } }]);
  const client = makeClient(fetchImpl);

  const result = await client.mapExternalIdentifier({
    entityId: "entity-1",
    externalKind: "actor",
    externalId: "foundry-actor-1",
  });

  assert.deepEqual(result, { external_identifier_id: "id-1" });
  assert.equal(fetchImpl.calls.length, 1);
  const [{ url, init }] = fetchImpl.calls;
  assert.equal(
    url,
    "https://dnd-ai.example.com/campaigns/22222222-2222-2222-2222-222222222222/integration/external-systems/11111111-1111-1111-1111-111111111111/identifiers",
  );
  assert.equal(init.method, "POST");
  assert.equal(
    init.headers.Authorization,
    "FoundrySystem 11111111-1111-1111-1111-111111111111.super-secret-key",
  );
  assert.equal(init.headers["X-Foundry-Actor-Id"], "foundry-user-42");
  assert.equal(init.headers["Idempotency-Key"], undefined);
  assert.deepEqual(JSON.parse(init.body), {
    entity_id: "entity-1",
    external_kind: "actor",
    external_id: "foundry-actor-1",
  });
});

test("adjustHitPoints sends the Idempotency-Key header when supplied", async () => {
  const fetchImpl = createFetchStub([
    { status: 200, body: { event_id: "e1", previous_hit_points: 10, new_hit_points: 16, changed: true } },
  ]);
  const client = makeClient(fetchImpl);

  await client.adjustHitPoints("char-1", { world_time_id: "wt1", delta: 6 }, "hp-abc123");

  const [{ url, init }] = fetchImpl.calls;
  assert.ok(url.endsWith("/characters/char-1/hit-points"));
  assert.equal(init.headers["Idempotency-Key"], "hp-abc123");
});

test("applyCombatSync never sends an Idempotency-Key header (uses external_operation_id instead)", async () => {
  const fetchImpl = createFetchStub([
    {
      status: 201,
      body: {
        sync_job_id: "j1",
        encounter_turn_id: "t1",
        combat_action_id: "a1",
        event_id: "e1",
        previous_hit_points: 20,
        new_hit_points: 13,
        replayed: false,
      },
    },
  ]);
  const client = makeClient(fetchImpl);

  const payload = { external_system_id: SETTINGS.externalSystemId, external_operation_id: "combat-abc" };
  await client.applyCombatSync(payload);

  const [{ init }] = fetchImpl.calls;
  assert.equal(init.headers["Idempotency-Key"], undefined);
  assert.deepEqual(JSON.parse(init.body), payload);
});

test("getSyncState encodes exactly the supplied target as a query parameter", async () => {
  const fetchImpl = createFetchStub([{ status: 200, body: { sync_status: "synced" } }]);
  const client = makeClient(fetchImpl);

  await client.getSyncState({ targetEncounterId: "enc-1" });

  const [{ url }] = fetchImpl.calls;
  const parsed = new URL(url);
  assert.equal(parsed.searchParams.get("target_encounter_id"), "enc-1");
  assert.equal(parsed.searchParams.has("target_entity_id"), false);
});

test("a 403 response is parsed into a DndAiApiError with the server's own code/message", async () => {
  const fetchImpl = createFetchStub([
    {
      status: 403,
      body: {
        error: {
          code: "forbidden",
          message: "You do not have permission to perform this action.",
          correlation_id: "corr-1",
        },
      },
    },
  ]);
  const client = makeClient(fetchImpl);

  await assert.rejects(
    () => client.getCharacter("char-1"),
    (error) => {
      assert.ok(error instanceof DndAiApiError);
      assert.equal(error.status, 403);
      assert.equal(error.code, "forbidden");
      assert.equal(error.correlationId, "corr-1");
      assert.equal(error.retryable, false);
      return true;
    },
  );
});

test("a 5xx response is classified as retryable", async () => {
  const fetchImpl = createFetchStub([{ status: 500, body: { error: { code: "internal_error", message: "oops" } } }]);
  const client = makeClient(fetchImpl);

  await assert.rejects(
    () => client.getCharacter("char-1"),
    (error) => {
      assert.equal(error.retryable, true);
      return true;
    },
  );
});

test("a thrown network failure is classified as retryable with status 0", async () => {
  const fetchImpl = createFetchStub(() => {
    throw new TypeError("fetch failed");
  });
  const client = makeClient(fetchImpl);

  await assert.rejects(
    () => client.getCharacter("char-1"),
    (error) => {
      assert.ok(error instanceof DndAiApiError);
      assert.equal(error.status, 0);
      assert.equal(error.retryable, true);
      return true;
    },
  );
});

test("X-Foundry-Actor-Id never influences the Authorization header", async () => {
  // The server-side security property (dnd_ai.domain.access.
  // resolve_foundry_system_principal) is that this header is never an
  // authorization input at all — this is the client-side half: proving
  // this client itself builds Authorization purely from
  // externalSystemId/systemCredential, with no code path that could ever
  // let a different claimed actor id change what credential is sent.
  const fetchImpl = createFetchStub([
    { status: 200, body: { external_identifier_id: "id-1" } },
    { status: 200, body: { external_identifier_id: "id-1" } },
  ]);
  const client = new DndAiApiClient({
    getSettings: () => SETTINGS,
    fetchImpl,
    getFoundryActorId: () => "gm-foundry-id",
  });
  const otherClient = new DndAiApiClient({
    getSettings: () => SETTINGS,
    fetchImpl,
    getFoundryActorId: () => "a-completely-different-claimed-actor",
  });

  await client.mapExternalIdentifier({
    entityId: "entity-1",
    externalKind: "actor",
    externalId: "foundry-actor-1",
  });
  await otherClient.mapExternalIdentifier({
    entityId: "entity-1",
    externalKind: "actor",
    externalId: "foundry-actor-1",
  });

  const [first, second] = fetchImpl.calls;
  assert.equal(first.init.headers.Authorization, second.init.headers.Authorization);
  assert.notEqual(
    first.init.headers["X-Foundry-Actor-Id"],
    second.init.headers["X-Foundry-Actor-Id"],
  );
});

test("the credential never appears in a thrown error", async () => {
  const fetchImpl = createFetchStub([{ status: 403, body: { error: { code: "forbidden", message: "no" } } }]);
  const client = makeClient(fetchImpl);

  try {
    await client.getCharacter("char-1");
    assert.fail("expected a rejection");
  } catch (error) {
    const serialized = JSON.stringify({ message: error.message, stack: String(error.stack) });
    assert.ok(!serialized.includes(SETTINGS.systemCredential));
  }
});
