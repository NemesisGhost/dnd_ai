import assert from "node:assert/strict";
import { test } from "node:test";
import {
  getConnectionSettings,
  isLoopbackHost,
  isSecureApiBaseUrl,
  isValidHttpUrl,
  isValidUuid,
  registerSettings,
  setConnectionSettings,
  validateConnectionSettings,
} from "../scripts/settings.mjs";
import { FakeSettings } from "./harness/foundry-globals.mjs";

test("isValidUuid accepts a well-formed UUID and rejects everything else", () => {
  assert.equal(isValidUuid("11111111-1111-1111-1111-111111111111"), true);
  assert.equal(isValidUuid("not-a-uuid"), false);
  assert.equal(isValidUuid(""), false);
  assert.equal(isValidUuid(undefined), false);
});

test("isValidHttpUrl accepts http(s) and rejects other schemes/malformed input", () => {
  assert.equal(isValidHttpUrl("https://dnd-ai.example.com"), true);
  assert.equal(isValidHttpUrl("http://localhost:8000"), true);
  assert.equal(isValidHttpUrl("ftp://example.com"), false);
  assert.equal(isValidHttpUrl("not a url"), false);
  assert.equal(isValidHttpUrl(""), false);
});

test("isLoopbackHost recognizes only the closed set of loopback hosts", () => {
  assert.equal(isLoopbackHost("localhost"), true);
  assert.equal(isLoopbackHost("LOCALHOST"), true);
  assert.equal(isLoopbackHost("127.0.0.1"), true);
  // "[::1]" (bracketed) is what URL.hostname actually returns for an IPv6
  // literal host — see settings.mjs's own comment on LOOPBACK_HOSTS.
  assert.equal(isLoopbackHost("[::1]"), true);
  assert.equal(isLoopbackHost("::1"), false);
  // Private/LAN addresses are never automatically safe, even though a
  // network observer on the same LAN could still read plaintext traffic.
  assert.equal(isLoopbackHost("192.168.1.50"), false);
  assert.equal(isLoopbackHost("10.0.0.5"), false);
  assert.equal(isLoopbackHost("172.16.0.1"), false);
  // Not the entire 127.0.0.0/8 range — only the exact literal listed.
  assert.equal(isLoopbackHost("127.0.0.2"), false);
  assert.equal(isLoopbackHost("dnd-ai.example.com"), false);
});

test("isSecureApiBaseUrl requires https except for a recognized loopback host", () => {
  assert.equal(isSecureApiBaseUrl("https://dnd-ai.example.com"), true);
  assert.equal(isSecureApiBaseUrl("http://localhost:8000"), true);
  assert.equal(isSecureApiBaseUrl("http://127.0.0.1:8000"), true);
  assert.equal(isSecureApiBaseUrl("http://[::1]:8000"), true);
  // Remote or LAN http:// is rejected — this is the Issue 2 fix: a
  // long-lived FoundrySystem credential must never travel over plaintext
  // to a host other than the developer's own machine.
  assert.equal(isSecureApiBaseUrl("http://dnd-ai.example.com"), false);
  assert.equal(isSecureApiBaseUrl("http://192.168.1.50:8000"), false);
  assert.equal(isSecureApiBaseUrl("not a url"), false);
});

test("registerSettings registers all four settings with the correct config visibility", () => {
  const settingsApi = new FakeSettings();
  registerSettings({ settingsApi });

  assert.deepEqual(getConnectionSettings({ settingsApi }), {
    apiBaseUrl: "",
    externalSystemId: "",
    campaignId: "",
    systemCredential: "",
  });
  assert.equal(settingsApi._definitions.get("dnd-ai-adapter.systemCredential").config, false);
  assert.equal(settingsApi._definitions.get("dnd-ai-adapter.apiBaseUrl").config, true);
});

test("systemCredential is registered client-scoped — never distributed to other connected clients", () => {
  // Regression for the Critical defect this correction closes (see
  // scripts/settings.mjs's own docstring): a world-scoped credential is
  // delivered by Foundry to every connected client regardless of
  // config: false, which only hides a setting from the UI, never narrows
  // its distribution. scope: "client" is what actually keeps this value
  // confined to the one browser profile that set it.
  const settingsApi = new FakeSettings();
  registerSettings({ settingsApi });

  assert.equal(settingsApi._definitions.get("dnd-ai-adapter.systemCredential").scope, "client");
  for (const key of ["apiBaseUrl", "externalSystemId", "campaignId"]) {
    assert.equal(settingsApi._definitions.get(`dnd-ai-adapter.${key}`).scope, "world");
  }
});

test("setConnectionSettings/getConnectionSettings round-trip", async () => {
  const settingsApi = new FakeSettings();
  registerSettings({ settingsApi });

  await setConnectionSettings(
    {
      apiBaseUrl: "https://dnd-ai.example.com",
      externalSystemId: "11111111-1111-1111-1111-111111111111",
      campaignId: "22222222-2222-2222-2222-222222222222",
      systemCredential: "secret-key",
    },
    { settingsApi },
  );

  assert.deepEqual(getConnectionSettings({ settingsApi }), {
    apiBaseUrl: "https://dnd-ai.example.com",
    externalSystemId: "11111111-1111-1111-1111-111111111111",
    campaignId: "22222222-2222-2222-2222-222222222222",
    systemCredential: "secret-key",
  });
});

test("validateConnectionSettings reports a specific problem per invalid field", () => {
  const problems = validateConnectionSettings({
    apiBaseUrl: "not a url",
    externalSystemId: "not-a-uuid",
    campaignId: "22222222-2222-2222-2222-222222222222",
    systemCredential: "",
  });
  assert.deepEqual(problems, [
    "DNDAI.Errors.InvalidApiBaseUrl",
    "DNDAI.Errors.InvalidExternalSystemId",
    "DNDAI.Errors.MissingCredential",
  ]);
});

test("validateConnectionSettings flags a well-formed but insecure (non-loopback http) API base URL", () => {
  const problems = validateConnectionSettings({
    apiBaseUrl: "http://dnd-ai.example.com",
    externalSystemId: "11111111-1111-1111-1111-111111111111",
    campaignId: "22222222-2222-2222-2222-222222222222",
    systemCredential: "secret-key",
  });
  assert.deepEqual(problems, ["DNDAI.Errors.InsecureApiBaseUrl"]);
});

test("validateConnectionSettings accepts http for a loopback API base URL", () => {
  const problems = validateConnectionSettings({
    apiBaseUrl: "http://localhost:8000",
    externalSystemId: "11111111-1111-1111-1111-111111111111",
    campaignId: "22222222-2222-2222-2222-222222222222",
    systemCredential: "secret-key",
  });
  assert.deepEqual(problems, []);
});

test("validateConnectionSettings reports nothing for fully valid settings", () => {
  const problems = validateConnectionSettings({
    apiBaseUrl: "https://dnd-ai.example.com",
    externalSystemId: "11111111-1111-1111-1111-111111111111",
    campaignId: "22222222-2222-2222-2222-222222222222",
    systemCredential: "secret-key",
  });
  assert.deepEqual(problems, []);
});
