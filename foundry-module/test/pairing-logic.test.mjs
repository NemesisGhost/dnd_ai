import assert from "node:assert/strict";
import { test } from "node:test";
import { registerSettings, setApiBaseUrl } from "../scripts/settings.mjs";
import { registerPairingSettings, getConnectionMetadata, getDeviceCredential } from "../scripts/pairing.mjs";
import { preparePairingContext, submitPairingCode } from "../scripts/ui/pairing-logic.mjs";
import { FakeSettings, createFakeGame } from "./harness/foundry-globals.mjs";
import { createFetchStub } from "./harness/fetch-stub.mjs";

function makeSettingsApi() {
  const settingsApi = new FakeSettings();
  registerSettings({ settingsApi });
  registerPairingSettings({ settingsApi });
  return settingsApi;
}

test("preparePairingContext reflects the currently configured API base URL", async () => {
  const settingsApi = makeSettingsApi();
  await setApiBaseUrl("https://dnd-ai.example.com", { settingsApi });

  assert.deepEqual(preparePairingContext({ settingsApi }), { apiBaseUrl: "https://dnd-ai.example.com" });
});

test("submitPairingCode rejects a missing pairing code without contacting the server", async () => {
  const settingsApi = makeSettingsApi();
  const fetchImpl = createFetchStub([]);

  const result = await submitPairingCode(
    { apiBaseUrl: "https://dnd-ai.example.com", pairingCode: "" },
    { settingsApi, gameApi: createFakeGame(), fetchImpl },
  );

  assert.equal(result.ok, false);
  assert.deepEqual(result.problems, ["DNDAI.Errors.MissingPairingCode"]);
  assert.equal(fetchImpl.calls.length, 0);
});

test("submitPairingCode rejects an invalid API base URL without contacting the server", async () => {
  const settingsApi = makeSettingsApi();
  const fetchImpl = createFetchStub([]);

  const result = await submitPairingCode(
    { apiBaseUrl: "not a url", pairingCode: "some-code" },
    { settingsApi, gameApi: createFakeGame(), fetchImpl },
  );

  assert.equal(result.ok, false);
  assert.deepEqual(result.problems, ["DNDAI.Errors.InvalidApiBaseUrl"]);
  assert.equal(fetchImpl.calls.length, 0);
});

test("submitPairingCode on success persists connection metadata and device credential and saves the API base URL", async () => {
  const settingsApi = makeSettingsApi();
  const fetchImpl = createFetchStub([
    {
      status: 200,
      body: {
        foundry_connection_id: "conn-1",
        foundry_device_id: "device-1",
        raw_device_secret: "raw-secret",
        raw_access_token: "raw-token",
        expires_at: "2026-01-01T00:05:00.000Z",
        campaign_id: "22222222-2222-2222-2222-222222222222",
        external_system_id: "11111111-1111-1111-1111-111111111111",
        granted_scopes: ["combat.write"],
      },
    },
  ]);
  const gameApi = createFakeGame({ userId: "user-1" });

  const result = await submitPairingCode(
    { apiBaseUrl: "https://dnd-ai.example.com", pairingCode: "  pairing-code-123  " },
    { settingsApi, gameApi, fetchImpl, generateDeviceId: () => "device-1" },
  );

  assert.deepEqual(result, { ok: true });

  const [{ url, init }] = fetchImpl.calls;
  assert.equal(url, "https://dnd-ai.example.com/foundry/pair");
  assert.deepEqual(JSON.parse(init.body).raw_code, "pairing-code-123");

  const metadata = getConnectionMetadata({ settingsApi });
  assert.equal(metadata.foundryConnectionId, "conn-1");
  assert.equal(metadata.campaignId, "22222222-2222-2222-2222-222222222222");
  assert.equal(metadata.externalSystemId, "11111111-1111-1111-1111-111111111111");
  assert.equal(metadata.foundryUserId, "user-1");
  assert.deepEqual(metadata.grantedScopes, ["combat.write"]);
  assert.ok(metadata.pairedAt);

  const credential = getDeviceCredential({ settingsApi });
  assert.deepEqual(credential, { foundryDeviceId: "device-1", rawDeviceSecret: "raw-secret" });
});

test("submitPairingCode surfaces a server rejection without persisting anything", async () => {
  const settingsApi = makeSettingsApi();
  const fetchImpl = createFetchStub([
    { status: 422, body: { error: { code: "validation_failed", message: "Pairing code is invalid or expired." } } },
  ]);
  const gameApi = createFakeGame({ userId: "user-1" });

  const result = await submitPairingCode(
    { apiBaseUrl: "https://dnd-ai.example.com", pairingCode: "bad-code" },
    { settingsApi, gameApi, fetchImpl, generateDeviceId: () => "device-1" },
  );

  assert.equal(result.ok, false);
  assert.deepEqual(result.problems, []);
  assert.equal(result.error.code, "validation_failed");
  assert.deepEqual(getConnectionMetadata({ settingsApi }), {});
  assert.deepEqual(getDeviceCredential({ settingsApi }), {});
});
