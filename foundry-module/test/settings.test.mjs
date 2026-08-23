import assert from "node:assert/strict";
import { test } from "node:test";
import {
  getApiBaseUrl,
  isLoopbackHost,
  isSecureApiBaseUrl,
  isValidHttpUrl,
  isValidUuid,
  registerSettings,
  setApiBaseUrl,
  validateApiBaseUrl,
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
  // Remote or LAN http:// is rejected — a paired device secret and the
  // access token it is exchanged for must never travel in plaintext to a
  // host other than the developer's own machine.
  assert.equal(isSecureApiBaseUrl("http://dnd-ai.example.com"), false);
  assert.equal(isSecureApiBaseUrl("http://192.168.1.50:8000"), false);
  assert.equal(isSecureApiBaseUrl("not a url"), false);
});

test("registerSettings registers only apiBaseUrl, world-scoped and visible in config", () => {
  const settingsApi = new FakeSettings();
  registerSettings({ settingsApi });

  assert.equal(getApiBaseUrl({ settingsApi }), "");
  const definition = settingsApi._definitions.get("dnd-ai-adapter.apiBaseUrl");
  assert.equal(definition.scope, "world");
  assert.equal(definition.config, true);
});

test("setApiBaseUrl/getApiBaseUrl round-trip", async () => {
  const settingsApi = new FakeSettings();
  registerSettings({ settingsApi });

  await setApiBaseUrl("https://dnd-ai.example.com", { settingsApi });

  assert.equal(getApiBaseUrl({ settingsApi }), "https://dnd-ai.example.com");
});

test("validateApiBaseUrl reports the malformed-URL problem", () => {
  assert.deepEqual(validateApiBaseUrl("not a url"), ["DNDAI.Errors.InvalidApiBaseUrl"]);
  assert.deepEqual(validateApiBaseUrl(""), ["DNDAI.Errors.InvalidApiBaseUrl"]);
});

test("validateApiBaseUrl flags a well-formed but insecure (non-loopback http) URL", () => {
  assert.deepEqual(validateApiBaseUrl("http://dnd-ai.example.com"), ["DNDAI.Errors.InsecureApiBaseUrl"]);
});

test("validateApiBaseUrl accepts http for a loopback host", () => {
  assert.deepEqual(validateApiBaseUrl("http://localhost:8000"), []);
});

test("validateApiBaseUrl reports nothing for a fully valid https URL", () => {
  assert.deepEqual(validateApiBaseUrl("https://dnd-ai.example.com"), []);
});
