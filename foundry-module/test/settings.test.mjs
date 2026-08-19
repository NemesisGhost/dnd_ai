import assert from "node:assert/strict";
import { test } from "node:test";
import {
  getConnectionSettings,
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

test("validateConnectionSettings reports nothing for fully valid settings", () => {
  const problems = validateConnectionSettings({
    apiBaseUrl: "https://dnd-ai.example.com",
    externalSystemId: "11111111-1111-1111-1111-111111111111",
    campaignId: "22222222-2222-2222-2222-222222222222",
    systemCredential: "secret-key",
  });
  assert.deepEqual(problems, []);
});
