import assert from "node:assert/strict";
import { test } from "node:test";
import { SyncEngine } from "../scripts/sync-engine.mjs";
import { FakeDocument } from "./harness/foundry-globals.mjs";

test("restoreFromServer issues only read calls, never a write, for every linked actor", async () => {
  const calls = [];
  const client = {
    getCharacter: async (characterId) => {
      calls.push(["getCharacter", characterId]);
      return { character_id: characterId, current_hit_points: 8 };
    },
    // If restoration ever calls one of these, the test must fail loudly
    // rather than silently succeed — reconnect must never resubmit.
    applyCombatSync: async () => {
      throw new Error("restoreFromServer must never call applyCombatSync");
    },
    adjustHitPoints: async () => {
      throw new Error("restoreFromServer must never call adjustHitPoints");
    },
    applyCondition: async () => {
      throw new Error("restoreFromServer must never call applyCondition");
    },
    adjustResource: async () => {
      throw new Error("restoreFromServer must never call adjustResource");
    },
  };
  const engine = new SyncEngine({ client, getSettings: () => ({ externalSystemId: "sys-1" }) });

  const linkedActor = new FakeDocument({ id: "actor-1", system: { attributes: { hp: { value: 3 } } } });
  await linkedActor.setFlag("dnd-ai-adapter", "entityId", "char-1");
  const unlinkedActor = new FakeDocument({ id: "actor-2" });

  const restored = await engine.restoreFromServer([linkedActor, unlinkedActor]);

  assert.equal(calls.length, 1, "only the linked actor should be read");
  assert.deepEqual(calls[0], ["getCharacter", "char-1"]);
  assert.equal(restored.length, 1);
});

test("restoreFromServer applies the server's canonical HP to the local actor", async () => {
  const client = {
    getCharacter: async () => ({ character_id: "char-1", current_hit_points: 11 }),
  };
  const engine = new SyncEngine({ client, getSettings: () => ({ externalSystemId: "sys-1" }) });
  const actor = new FakeDocument({ id: "actor-1", system: { attributes: { hp: { value: 3 } } } });
  await actor.setFlag("dnd-ai-adapter", "entityId", "char-1");

  await engine.restoreFromServer([actor]);

  assert.equal(actor.system.attributes.hp.value, 11);
  assert.equal(actor.updateCalls.length, 1);
});

test("restoreFromServer skips an actor already at the correct HP without writing", async () => {
  const client = {
    getCharacter: async () => ({ character_id: "char-1", current_hit_points: 11 }),
  };
  const engine = new SyncEngine({ client, getSettings: () => ({ externalSystemId: "sys-1" }) });
  const actor = new FakeDocument({ id: "actor-1", system: { attributes: { hp: { value: 11 } } } });
  await actor.setFlag("dnd-ai-adapter", "entityId", "char-1");

  await engine.restoreFromServer([actor]);

  assert.equal(actor.updateCalls.length, 0, "no redundant write when the value already matches");
});
