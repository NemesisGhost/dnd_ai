import assert from "node:assert/strict";
import { test } from "node:test";
import {
  FoundryAccessTokenCache,
  clearPairing,
  consumeFoundryPairingCode,
  exchangeFoundryDeviceCredential,
  getConnectionMetadata,
  getDeviceCredential,
  isPaired,
  registerPairingSettings,
  setConnectionMetadata,
  setDeviceCredential,
} from "../scripts/pairing.mjs";
import { DndAiApiError } from "../scripts/errors.mjs";
import { FakeSettings } from "./harness/foundry-globals.mjs";
import { createFetchStub } from "./harness/fetch-stub.mjs";

const CONNECTION_METADATA = {
  foundryConnectionId: "conn-1",
  campaignId: "22222222-2222-2222-2222-222222222222",
  externalSystemId: "11111111-1111-1111-1111-111111111111",
  foundryUserId: "user-1",
  grantedScopes: ["combat.write"],
  pairedAt: "2026-01-01T00:00:00.000Z",
};

const DEVICE_CREDENTIAL = { foundryDeviceId: "device-1", rawDeviceSecret: "raw-secret" };

test("registerPairingSettings registers connectionMetadata (user-scoped) and deviceCredential (client-scoped)", () => {
  const settingsApi = new FakeSettings();
  registerPairingSettings({ settingsApi });

  assert.equal(settingsApi._definitions.get("dnd-ai-adapter.connectionMetadata").scope, "user");
  assert.equal(settingsApi._definitions.get("dnd-ai-adapter.connectionMetadata").config, false);
  assert.equal(settingsApi._definitions.get("dnd-ai-adapter.deviceCredential").scope, "client");
  assert.equal(settingsApi._definitions.get("dnd-ai-adapter.deviceCredential").config, false);
});

test("registerPairingSettings registers a settings menu only when a pairingAppClass is supplied", () => {
  const settingsApi = new FakeSettings();
  registerPairingSettings({ settingsApi });
  assert.equal(settingsApi._menus.size, 0);

  const settingsApiWithMenu = new FakeSettings();
  class FakePairingApp {}
  registerPairingSettings({ settingsApi: settingsApiWithMenu, pairingAppClass: FakePairingApp });
  assert.equal(settingsApiWithMenu._menus.get("dnd-ai-adapter.pairing").type, FakePairingApp);
});

test("connection metadata and device credential round-trip independently", async () => {
  const settingsApi = new FakeSettings();
  registerPairingSettings({ settingsApi });

  await setConnectionMetadata(CONNECTION_METADATA, { settingsApi });
  await setDeviceCredential(DEVICE_CREDENTIAL, { settingsApi });

  assert.deepEqual(getConnectionMetadata({ settingsApi }), CONNECTION_METADATA);
  assert.deepEqual(getDeviceCredential({ settingsApi }), DEVICE_CREDENTIAL);
});

test("isPaired is false until both connection metadata and device credential are complete", async () => {
  const settingsApi = new FakeSettings();
  registerPairingSettings({ settingsApi });

  assert.equal(isPaired({ settingsApi }), false);

  await setConnectionMetadata(CONNECTION_METADATA, { settingsApi });
  assert.equal(isPaired({ settingsApi }), false);

  await setDeviceCredential(DEVICE_CREDENTIAL, { settingsApi });
  assert.equal(isPaired({ settingsApi }), true);
});

test("clearPairing removes both connection metadata and device credential", async () => {
  const settingsApi = new FakeSettings();
  registerPairingSettings({ settingsApi });
  await setConnectionMetadata(CONNECTION_METADATA, { settingsApi });
  await setDeviceCredential(DEVICE_CREDENTIAL, { settingsApi });

  await clearPairing({ settingsApi });

  assert.equal(isPaired({ settingsApi }), false);
  assert.deepEqual(getConnectionMetadata({ settingsApi }), {});
  assert.deepEqual(getDeviceCredential({ settingsApi }), {});
});

test("consumeFoundryPairingCode POSTs to /foundry/pair with no Authorization header", async () => {
  const fetchImpl = createFetchStub([
    {
      status: 200,
      body: {
        foundry_connection_id: "conn-1",
        foundry_device_id: "device-1",
        raw_device_secret: "raw-secret",
        raw_access_token: "raw-token",
        expires_at: "2026-01-01T00:05:00.000Z",
        campaign_id: CONNECTION_METADATA.campaignId,
        external_system_id: CONNECTION_METADATA.externalSystemId,
        granted_scopes: ["combat.write"],
      },
    },
  ]);

  const result = await consumeFoundryPairingCode({
    apiBaseUrl: "https://dnd-ai.example.com",
    rawCode: "pairing-code-123",
    foundryUserId: "user-1",
    foundryOrigin: "https://foundry.example.com",
    deviceLabel: "Foundry 13 device-1",
    fetchImpl,
  });

  assert.equal(result.foundry_device_id, "device-1");
  const [{ url, init }] = fetchImpl.calls;
  assert.equal(url, "https://dnd-ai.example.com/foundry/pair");
  assert.equal(init.method, "POST");
  assert.equal(init.headers.Authorization, undefined);
  assert.deepEqual(JSON.parse(init.body), {
    raw_code: "pairing-code-123",
    foundry_user_id: "user-1",
    foundry_origin: "https://foundry.example.com",
    device_label: "Foundry 13 device-1",
    module_version: null,
    foundry_version: null,
  });
});

test("consumeFoundryPairingCode surfaces a rejected code as a DndAiApiError", async () => {
  const fetchImpl = createFetchStub([
    { status: 422, body: { error: { code: "validation_failed", message: "Pairing code is invalid or expired." } } },
  ]);

  await assert.rejects(
    () =>
      consumeFoundryPairingCode({
        apiBaseUrl: "https://dnd-ai.example.com",
        rawCode: "bad-code",
        foundryUserId: "user-1",
        foundryOrigin: "https://foundry.example.com",
        deviceLabel: "device",
        fetchImpl,
      }),
    (error) => {
      assert.ok(error instanceof DndAiApiError);
      assert.equal(error.code, "validation_failed");
      return true;
    },
  );
});

test("exchangeFoundryDeviceCredential sends the FoundryDevice bearer scheme", async () => {
  const fetchImpl = createFetchStub([
    { status: 200, body: { raw_access_token: "raw-token", expires_at: "2026-01-01T00:05:00.000Z" } },
  ]);

  await exchangeFoundryDeviceCredential({
    apiBaseUrl: "https://dnd-ai.example.com",
    foundryDeviceId: "device-1",
    rawDeviceSecret: "raw-secret",
    fetchImpl,
  });

  const [{ url, init }] = fetchImpl.calls;
  assert.equal(url, "https://dnd-ai.example.com/foundry/token");
  assert.equal(init.method, "POST");
  assert.equal(init.headers.Authorization, "FoundryDevice device-1.raw-secret");
});

test("FoundryAccessTokenCache exchanges the device credential once and reuses the cached token", async () => {
  const settingsApi = new FakeSettings();
  registerPairingSettings({ settingsApi });
  await setDeviceCredential(DEVICE_CREDENTIAL, { settingsApi });

  const fetchImpl = createFetchStub([
    { status: 200, body: { raw_access_token: "token-1", expires_at: "2026-01-01T00:10:00.000Z" } },
  ]);
  const cache = new FoundryAccessTokenCache();
  let nowMs = Date.parse("2026-01-01T00:00:00.000Z");

  const first = await cache.getAccessToken({
    apiBaseUrl: "https://dnd-ai.example.com",
    settingsApi,
    fetchImpl,
    now: () => nowMs,
  });
  const second = await cache.getAccessToken({
    apiBaseUrl: "https://dnd-ai.example.com",
    settingsApi,
    fetchImpl,
    now: () => nowMs,
  });

  assert.equal(first, "token-1");
  assert.equal(second, "token-1");
  assert.equal(fetchImpl.calls.length, 1);
});

test("FoundryAccessTokenCache refreshes once the cached token is within its refresh margin", async () => {
  const settingsApi = new FakeSettings();
  registerPairingSettings({ settingsApi });
  await setDeviceCredential(DEVICE_CREDENTIAL, { settingsApi });

  const fetchImpl = createFetchStub([
    { status: 200, body: { raw_access_token: "token-1", expires_at: "2026-01-01T00:10:00.000Z" } },
    { status: 200, body: { raw_access_token: "token-2", expires_at: "2026-01-01T00:20:00.000Z" } },
  ]);
  const cache = new FoundryAccessTokenCache();

  const first = await cache.getAccessToken({
    apiBaseUrl: "https://dnd-ai.example.com",
    settingsApi,
    fetchImpl,
    now: () => Date.parse("2026-01-01T00:00:00.000Z"),
  });
  // Within 60s of the token's expiry — must refresh, not reuse.
  const second = await cache.getAccessToken({
    apiBaseUrl: "https://dnd-ai.example.com",
    settingsApi,
    fetchImpl,
    now: () => Date.parse("2026-01-01T00:09:30.000Z"),
  });

  assert.equal(first, "token-1");
  assert.equal(second, "token-2");
  assert.equal(fetchImpl.calls.length, 2);
});

test("FoundryAccessTokenCache throws a plain Error when no device credential is stored", async () => {
  const settingsApi = new FakeSettings();
  registerPairingSettings({ settingsApi });
  const cache = new FoundryAccessTokenCache();

  await assert.rejects(
    () => cache.getAccessToken({ apiBaseUrl: "https://dnd-ai.example.com", settingsApi, fetchImpl: createFetchStub([]) }),
    (error) => {
      assert.ok(!(error instanceof DndAiApiError));
      return true;
    },
  );
});

test("FoundryAccessTokenCache.clear forces the next call to re-exchange", async () => {
  const settingsApi = new FakeSettings();
  registerPairingSettings({ settingsApi });
  await setDeviceCredential(DEVICE_CREDENTIAL, { settingsApi });

  const fetchImpl = createFetchStub([
    { status: 200, body: { raw_access_token: "token-1", expires_at: "2026-01-01T00:10:00.000Z" } },
    { status: 200, body: { raw_access_token: "token-2", expires_at: "2026-01-01T00:20:00.000Z" } },
  ]);
  const cache = new FoundryAccessTokenCache();
  const now = () => Date.parse("2026-01-01T00:00:00.000Z");

  await cache.getAccessToken({ apiBaseUrl: "https://dnd-ai.example.com", settingsApi, fetchImpl, now });
  cache.clear();
  const second = await cache.getAccessToken({ apiBaseUrl: "https://dnd-ai.example.com", settingsApi, fetchImpl, now });

  assert.equal(second, "token-2");
  assert.equal(fetchImpl.calls.length, 2);
});
