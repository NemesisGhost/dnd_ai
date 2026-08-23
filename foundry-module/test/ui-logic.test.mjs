import assert from "node:assert/strict";
import { test } from "node:test";
import { dispatchSyncAction, prepareSyncDialogContext, ACTION_ADJUST_RESOURCE, ACTION_APPLY_CONDITION, ACTION_COMBAT_TURN, ACTION_REMOVE_CONDITION } from "../scripts/ui/sync-dialog-logic.mjs";
import { FakeCombat, FakeDocument } from "./harness/foundry-globals.mjs";

// -- sync-dialog-logic.mjs -------------------------------------------------
// Pairing's own form logic (`pairing-logic.mjs`) has its own dedicated
// test file, test/pairing-logic.test.mjs.

function makeEngineStub() {
  const calls = [];
  return {
    calls,
    getLinkedEntityId: (document) => document.getFlag("dnd-ai-adapter", "entityId") ?? null,
    submitCombatTurn: async (args) => calls.push(["submitCombatTurn", args]),
    submitConditionApply: async (actor, body) => calls.push(["submitConditionApply", actor.id, body]),
    submitConditionRemove: async (actor, conditionId, body) =>
      calls.push(["submitConditionRemove", actor.id, conditionId, body]),
    submitResourceChange: async (actor, body) => calls.push(["submitResourceChange", actor.id, body]),
  };
}

test("dispatchSyncAction routes a combat-turn submission with parsed field types", async () => {
  const engine = makeEngineStub();
  const actor = new FakeDocument({ id: "actor-1" });
  const target = new FakeDocument({ id: "actor-2" });
  const combat = new FakeCombat({ id: "combat-1" });

  await dispatchSyncAction(engine, ACTION_COMBAT_TURN, {
    actor,
    target,
    combat,
    worldTimeId: "wt-1",
    formValues: { hit: "true", damageAmount: "7" },
  });

  const [call] = engine.calls;
  assert.equal(call[0], "submitCombatTurn");
  assert.equal(call[1].hit, true);
  assert.equal(call[1].damageAmount, 7);
  assert.equal(call[1].actor, actor);
  assert.equal(call[1].target, target);
});

test("dispatchSyncAction routes apply/remove condition and requires conditionId", async () => {
  const engine = makeEngineStub();
  const actor = new FakeDocument({ id: "actor-1" });

  await dispatchSyncAction(engine, ACTION_APPLY_CONDITION, {
    actor,
    worldTimeId: "wt-1",
    formValues: { conditionId: "cond-1" },
  });
  assert.equal(engine.calls[0][0], "submitConditionApply");

  await assert.rejects(
    () => dispatchSyncAction(engine, ACTION_REMOVE_CONDITION, { actor, worldTimeId: "wt-1", formValues: {} }),
    /Missing required field: conditionId/,
  );
});

test("dispatchSyncAction routes resource adjustment and requires both fields", async () => {
  const engine = makeEngineStub();
  const actor = new FakeDocument({ id: "actor-1" });

  await dispatchSyncAction(engine, ACTION_ADJUST_RESOURCE, {
    actor,
    worldTimeId: "wt-1",
    formValues: { resourceDefinitionId: "res-1", delta: "-1" },
  });
  assert.equal(engine.calls[0][0], "submitResourceChange");
  assert.equal(engine.calls[0][2].delta, -1);

  await assert.rejects(
    () =>
      dispatchSyncAction(engine, ACTION_ADJUST_RESOURCE, {
        actor,
        worldTimeId: "wt-1",
        formValues: { resourceDefinitionId: "res-1" },
      }),
    /Missing required field: delta/,
  );
});

test("dispatchSyncAction throws on an unknown action type", async () => {
  const engine = makeEngineStub();
  const actor = new FakeDocument({ id: "actor-1" });
  await assert.rejects(
    () => dispatchSyncAction(engine, "not-a-real-action", { actor, worldTimeId: "wt-1", formValues: {} }),
    /Unknown D&D AI sync action/,
  );
});

test("prepareSyncDialogContext lists only linked actors", async () => {
  const engine = makeEngineStub();
  const linked = new FakeDocument({ id: "actor-1", name: "Rin" });
  await linked.setFlag("dnd-ai-adapter", "entityId", "char-1");
  const unlinked = new FakeDocument({ id: "actor-2", name: "Ghost" });

  const context = prepareSyncDialogContext(engine, [linked, unlinked]);
  assert.deepEqual(context.linkedActors, [{ id: "actor-1", name: "Rin" }]);
});
