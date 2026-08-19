import assert from "node:assert/strict";
import { test } from "node:test";
import { SyncEngine } from "../scripts/sync-engine.mjs";
import { registerHpSyncHooks } from "../scripts/hooks.mjs";
import { FakeDocument, FakeHooks, createFakeGame, createFakeUi } from "./harness/foundry-globals.mjs";

function wait(ms = 5) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test("applyHitPoints marks the actor self-updating for the duration of its own write", async () => {
  const client = { getCharacter: async () => ({}) };
  const engine = new SyncEngine({ client, getSettings: () => ({ externalSystemId: "sys-1" }) });
  const actor = new FakeDocument({ id: "actor-1", system: { attributes: { hp: { value: 10 } } } });

  assert.equal(engine.isSelfUpdating("actor-1"), false);
  await engine.applyHitPoints(actor, 16);
  // Still true immediately after the write resolves — cleared only on
  // the next macrotask (see SyncEngine.applyHitPoints's own docstring
  // for why this can't be cleared synchronously).
  assert.equal(engine.isSelfUpdating("actor-1"), true);

  await wait();
  assert.equal(engine.isSelfUpdating("actor-1"), false);
});

test("the updateActor hook does not resubmit a change while the engine is self-updating that actor", async () => {
  const actor = new FakeDocument({ id: "actor-1", system: { attributes: { hp: { value: 10 } } } });
  await actor.setFlag("dnd-ai-adapter", "entityId", "char-1");

  const submitCalls = [];
  const engine = {
    isSelfUpdating: () => true, // simulates "this actor's HP write is our own"
    getLinkedEntityId: (document) => document.getFlag("dnd-ai-adapter", "entityId"),
    submitHpChange: async (a, body) => submitCalls.push([a.id, body]),
  };

  const hooksApi = new FakeHooks();
  const gameApi = createFakeGame({ isGM: true });
  registerHpSyncHooks({ hooksApi, gameApi, uiApi: createFakeUi(), engine });

  await hooksApi.call("preUpdateActor", actor, { system: { attributes: { hp: { value: 16 } } } });
  actor.system.attributes.hp.value = 16;
  await hooksApi.call("updateActor", actor, { system: { attributes: { hp: { value: 16 } } } });

  assert.equal(submitCalls.length, 0, "a self-triggered update must never be resubmitted");
});

test("the updateActor hook submits a genuine external HP change as a signed delta", async () => {
  const actor = new FakeDocument({ id: "actor-1", system: { attributes: { hp: { value: 10 } } } });
  await actor.setFlag("dnd-ai-adapter", "entityId", "char-1");

  const submitCalls = [];
  const engine = {
    isSelfUpdating: () => false,
    getLinkedEntityId: (document) => document.getFlag("dnd-ai-adapter", "entityId"),
    submitHpChange: async (a, body) => submitCalls.push([a.id, body]),
  };

  const hooksApi = new FakeHooks();
  const gameApi = createFakeGame({ isGM: true, worldTime: 555 });
  registerHpSyncHooks({ hooksApi, gameApi, uiApi: createFakeUi(), engine });

  await hooksApi.call("preUpdateActor", actor, { system: { attributes: { hp: { value: 4 } } } });
  actor.system.attributes.hp.value = 4; // the GM manually damaged the actor by 6
  await hooksApi.call("updateActor", actor, { system: { attributes: { hp: { value: 4 } } } });

  assert.equal(submitCalls.length, 1);
  assert.equal(submitCalls[0][0], "actor-1");
  assert.equal(submitCalls[0][1].delta, -6);
  assert.equal(submitCalls[0][1].worldTimeId, 555);
});

test("an unlinked actor's HP change is ignored entirely", async () => {
  const actor = new FakeDocument({ id: "actor-1", system: { attributes: { hp: { value: 10 } } } });
  // no setFlag — actor is not linked

  const submitCalls = [];
  const engine = {
    isSelfUpdating: () => false,
    getLinkedEntityId: () => null,
    submitHpChange: async (...args) => submitCalls.push(args),
  };

  const hooksApi = new FakeHooks();
  const gameApi = createFakeGame({ isGM: true });
  registerHpSyncHooks({ hooksApi, gameApi, uiApi: createFakeUi(), engine });

  await hooksApi.call("preUpdateActor", actor, { system: { attributes: { hp: { value: 4 } } } });
  actor.system.attributes.hp.value = 4;
  await hooksApi.call("updateActor", actor, { system: { attributes: { hp: { value: 4 } } } });

  assert.equal(submitCalls.length, 0);
});

test("a non-GM client never submits (avoids every connected player independently syncing)", async () => {
  const actor = new FakeDocument({ id: "actor-1", system: { attributes: { hp: { value: 10 } } } });
  await actor.setFlag("dnd-ai-adapter", "entityId", "char-1");

  const submitCalls = [];
  const engine = {
    isSelfUpdating: () => false,
    getLinkedEntityId: (document) => document.getFlag("dnd-ai-adapter", "entityId"),
    submitHpChange: async (...args) => submitCalls.push(args),
  };

  const hooksApi = new FakeHooks();
  const gameApi = createFakeGame({ isGM: false });
  registerHpSyncHooks({ hooksApi, gameApi, uiApi: createFakeUi(), engine });

  await hooksApi.call("preUpdateActor", actor, { system: { attributes: { hp: { value: 4 } } } });
  actor.system.attributes.hp.value = 4;
  await hooksApi.call("updateActor", actor, { system: { attributes: { hp: { value: 4 } } } });

  assert.equal(submitCalls.length, 0);
});

test("end-to-end: SyncEngine's own write-back does not retrigger a second outbound submit", async () => {
  const actor = new FakeDocument({ id: "actor-1", system: { attributes: { hp: { value: 20 } } } });
  await actor.setFlag("dnd-ai-adapter", "entityId", "char-1");

  const adjustHitPointsCalls = [];
  const client = {
    adjustHitPoints: async (characterId, body, key) => {
      adjustHitPointsCalls.push([characterId, body, key]);
      // Deliberately different from what the client requested (15) —
      // simulates the server's own authoritative clamping/adjustment
      // (e.g. a rule this client never applies locally). This forces
      // applyHitPoints below to perform a *real* second actor.update()
      // call, so this test actually exercises the self-updating guard
      // rather than the unrelated "value already matches, skip the
      // write" short-circuit in applyHitPoints itself.
      return { event_id: "e1", previous_hit_points: 20, new_hit_points: 12, changed: true };
    },
  };
  const engine = new SyncEngine({ client, getSettings: () => ({ externalSystemId: "sys-1" }) });

  const hooksApi = new FakeHooks();
  const gameApi = createFakeGame({ isGM: true, worldTime: 100 });
  registerHpSyncHooks({ hooksApi, gameApi, uiApi: createFakeUi(), engine });

  // A genuine GM-driven HP change: 20 -> 15. registerHpSyncHooks's own
  // updateActor handler awaits engine.submitHpChange, which (via
  // applyHitPoints) already performs the clamped 15 -> 12 write-back
  // before this await resolves.
  await hooksApi.call("preUpdateActor", actor, { system: { attributes: { hp: { value: 15 } } } });
  actor.system.attributes.hp.value = 15;
  await hooksApi.call("updateActor", actor, { system: { attributes: { hp: { value: 15 } } } });

  assert.equal(adjustHitPointsCalls.length, 1);
  assert.equal(adjustHitPointsCalls[0][1].delta, -5);
  assert.equal(actor.system.attributes.hp.value, 12, "applyHitPoints already wrote the clamped value");

  // In real Foundry, that write-back would itself dispatch a second
  // updateActor hook carrying a genuinely nonzero delta (15 -> 12).
  // This harness cannot replay real Foundry's exact "hooks fire before
  // the document mutation" ordering for a write that already happened
  // as a side effect further up this same call stack, so the pre-write
  // value is staged explicitly here (15, distinct from the already-
  // applied 12) — the point is to prove the self-updating *guard*, not
  // an incidental zero-delta short-circuit, is what prevents
  // resubmission: with a real, nonzero delta on the table, only the
  // guard stops it.
  actor.system.attributes.hp.value = 15;
  await hooksApi.call("preUpdateActor", actor, { system: { attributes: { hp: { value: 12 } } } });
  actor.system.attributes.hp.value = 12;
  await hooksApi.call("updateActor", actor, { system: { attributes: { hp: { value: 12 } } } });

  assert.equal(adjustHitPointsCalls.length, 1, "the self-triggered write must not be resubmitted");
});
