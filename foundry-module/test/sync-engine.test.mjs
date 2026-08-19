import assert from "node:assert/strict";
import { test } from "node:test";
import { SyncEngine } from "../scripts/sync-engine.mjs";
import { FakeCombat, FakeDocument } from "./harness/foundry-globals.mjs";

const SETTINGS = { externalSystemId: "sys-1" };

function makeEngine(clientOverrides = {}) {
  const calls = [];
  const client = {
    mapExternalIdentifier: async (args) => {
      calls.push(["mapExternalIdentifier", args]);
      return { external_identifier_id: "ident-1" };
    },
    applyCombatSync: async (payload) => {
      calls.push(["applyCombatSync", payload]);
      return (
        clientOverrides.applyCombatSync?.(payload) ?? {
          sync_job_id: "job-1",
          encounter_turn_id: "turn-1",
          combat_action_id: "action-1",
          event_id: "event-1",
          previous_hit_points: 20,
          new_hit_points: 13,
          replayed: false,
        }
      );
    },
    adjustHitPoints: async (characterId, body, idempotencyKey) => {
      calls.push(["adjustHitPoints", characterId, body, idempotencyKey]);
      return { event_id: "e1", previous_hit_points: 10, new_hit_points: 10 + body.delta, changed: true };
    },
    applyCondition: async (characterId, body, idempotencyKey) => {
      calls.push(["applyCondition", characterId, body, idempotencyKey]);
      return { event_id: "e2", changed: true };
    },
    removeCondition: async (characterId, conditionId, body, idempotencyKey) => {
      calls.push(["removeCondition", characterId, conditionId, body, idempotencyKey]);
      return { event_id: "e3", changed: true };
    },
    adjustResource: async (characterId, body, idempotencyKey) => {
      calls.push(["adjustResource", characterId, body, idempotencyKey]);
      return { event_id: "e4", previous_amount: 3, new_amount: 3 + body.delta, changed: true };
    },
    getCharacter: async (characterId) => {
      calls.push(["getCharacter", characterId]);
      return clientOverrides.getCharacter?.(characterId) ?? { character_id: characterId, current_hit_points: 8 };
    },
  };
  const engine = new SyncEngine({ client, getSettings: () => SETTINGS, sleep: async () => {} });
  return { engine, calls };
}

test("linkActor calls map_external_identifier and sets the entity-id flag", async () => {
  const { engine, calls } = makeEngine();
  const actor = new FakeDocument({ id: "actor-1", name: "Rin" });

  await engine.linkActor(actor, "entity-1");

  assert.deepEqual(calls[0], [
    "mapExternalIdentifier",
    { entityId: "entity-1", externalKind: "actor", externalId: "actor-1" },
  ]);
  assert.equal(engine.getLinkedEntityId(actor), "entity-1");
});

test("linkEncounter is local-only: it never calls the API", async () => {
  const { engine, calls } = makeEngine();
  const combat = new FakeCombat({ id: "combat-1" });

  await engine.linkEncounter(combat, "encounter-1");

  assert.equal(calls.length, 0);
  assert.equal(engine.getLinkedEntityId(combat), "encounter-1");
});

test("submitCombatTurn builds the request from the linked actor/target/encounter and applies the returned HP", async () => {
  const { engine, calls } = makeEngine();
  const combat = new FakeCombat({ id: "combat-1", round: 2, turn: 1 });
  const attacker = new FakeDocument({ id: "attacker-1", name: "Rin" });
  const defender = new FakeDocument({ id: "defender-1", name: "Borin", system: { attributes: { hp: { value: 20 } } } });
  await engine.linkEncounter(combat, "encounter-1");
  await engine.linkActor(attacker, "actor-entity-1");
  await engine.linkActor(defender, "actor-entity-2");
  calls.length = 0; // discard the two linking calls above

  const result = await engine.submitCombatTurn({
    combat,
    actor: attacker,
    target: defender,
    worldTimeId: "wt-1",
    hit: true,
    damageAmount: 7,
  });

  assert.equal(result.new_hit_points, 13);
  const [call] = calls;
  assert.equal(call[0], "applyCombatSync");
  const payload = call[1];
  assert.equal(payload.external_system_id, "sys-1");
  assert.equal(payload.encounter_id, "encounter-1");
  assert.equal(payload.round_number, 2);
  assert.equal(payload.turn_order, 1);
  assert.equal(payload.actor_entity_id, "actor-entity-1");
  assert.equal(payload.target_entity_id, "actor-entity-2");
  assert.equal(payload.hit, true);
  assert.equal(payload.damage_amount, 7);
  assert.ok(/^combat-[0-9a-f]{8}$/.test(payload.external_operation_id));

  // the returned canonical HP was written back onto the target actor
  assert.equal(defender.system.attributes.hp.value, 13);
});

test("submitCombatTurn rejects with a clear error when the actor is not linked", async () => {
  const { engine } = makeEngine();
  const combat = new FakeCombat({ id: "combat-1" });
  await engine.linkEncounter(combat, "encounter-1");
  const unlinkedActor = new FakeDocument({ id: "actor-x", name: "Unlinked" });

  await assert.rejects(
    () => engine.submitCombatTurn({ combat, actor: unlinkedActor, worldTimeId: "wt-1" }),
    /not linked/,
  );
});

test("submitCombatTurn rejects with a clear error when the encounter is not linked", async () => {
  const { engine } = makeEngine();
  const combat = new FakeCombat({ id: "combat-1" });
  const actor = new FakeDocument({ id: "actor-1" });
  await engine.linkActor(actor, "entity-1");

  await assert.rejects(
    () => engine.submitCombatTurn({ combat, actor, worldTimeId: "wt-1" }),
    /not linked/,
  );
});

test("submitHpChange computes a stable idempotency key and writes back the confirmed HP", async () => {
  const { engine, calls } = makeEngine();
  const actor = new FakeDocument({ id: "actor-1", system: { attributes: { hp: { value: 10 } } } });
  await engine.linkActor(actor, "char-1");
  calls.length = 0;

  await engine.submitHpChange(actor, { worldTimeId: "wt-1", delta: 6 });

  const [call] = calls;
  assert.equal(call[0], "adjustHitPoints");
  assert.equal(call[1], "char-1");
  assert.equal(call[2].delta, 6);
  assert.ok(call[3], "an Idempotency-Key must be supplied");
  assert.equal(actor.system.attributes.hp.value, 16);
});

test("submitConditionApply and submitConditionRemove bind to the linked character id", async () => {
  const { engine, calls } = makeEngine();
  const actor = new FakeDocument({ id: "actor-1" });
  await engine.linkActor(actor, "char-1");
  calls.length = 0;

  await engine.submitConditionApply(actor, { worldTimeId: "wt-1", conditionId: "cond-1" });
  await engine.submitConditionRemove(actor, "cond-1", { worldTimeId: "wt-1" });

  assert.equal(calls[0][0], "applyCondition");
  assert.equal(calls[0][1], "char-1");
  assert.equal(calls[0][2].condition_id, "cond-1");
  assert.equal(calls[1][0], "removeCondition");
  assert.equal(calls[1][1], "char-1");
  assert.equal(calls[1][2], "cond-1");
});

test("submitResourceChange binds to the linked character id and passes delta through", async () => {
  const { engine, calls } = makeEngine();
  const actor = new FakeDocument({ id: "actor-1" });
  await engine.linkActor(actor, "char-1");
  calls.length = 0;

  await engine.submitResourceChange(actor, { worldTimeId: "wt-1", resourceDefinitionId: "res-1", delta: -1 });

  assert.equal(calls[0][0], "adjustResource");
  assert.equal(calls[0][2].resource_definition_id, "res-1");
  assert.equal(calls[0][2].delta, -1);
});
