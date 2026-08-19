import assert from "node:assert/strict";
import { test } from "node:test";
import { stableOperationId } from "../scripts/ids.mjs";

test("the same logical operation produces the same id across repeated calls", () => {
  const parts = { encounterId: "enc-1", roundNumber: 1, turnOrder: 0, actorEntityId: "actor-1" };
  const first = stableOperationId("combat", parts);
  const second = stableOperationId("combat", { ...parts });
  assert.equal(first, second);
});

test("a different operation produces a different id", () => {
  const base = { encounterId: "enc-1", roundNumber: 1, turnOrder: 0, actorEntityId: "actor-1" };
  const a = stableOperationId("combat", base);
  const b = stableOperationId("combat", { ...base, turnOrder: 1 });
  assert.notEqual(a, b);
});

test("key order does not affect the id", () => {
  const a = stableOperationId("hp", { characterId: "c1", worldTimeId: "wt1", delta: 5 });
  const b = stableOperationId("hp", { delta: 5, worldTimeId: "wt1", characterId: "c1" });
  assert.equal(a, b);
});

test("null and undefined for the same field hash identically", () => {
  const a = stableOperationId("hp", { characterId: "c1", sessionId: null });
  const b = stableOperationId("hp", { characterId: "c1", sessionId: undefined });
  assert.equal(a, b);
});

test("the id is a safe Idempotency-Key / external_operation_id value", () => {
  const id = stableOperationId("condition-apply", { characterId: "c1", worldTimeId: "wt1", conditionId: "cond-1" });
  assert.ok(id.length >= 1 && id.length <= 255);
  assert.match(id, /^[A-Za-z0-9._~-]+$/);
});

test("a different tag alone changes the id even with identical parts", () => {
  const parts = { characterId: "c1", worldTimeId: "wt1" };
  const a = stableOperationId("hp", parts);
  const b = stableOperationId("condition-apply", parts);
  assert.notEqual(a, b);
});
