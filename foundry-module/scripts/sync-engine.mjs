import { stableOperationId } from "./ids.mjs";
import { withRetry } from "./retry.mjs";

export const FLAG_ENTITY_ID = "entityId";

/**
 * Everything this module actually synchronizes, independent of Foundry's
 * hook plumbing (hooks.mjs) — kept separate so the sync/request-shaping
 * logic is directly unit-testable against a fake `DndAiApiClient`
 * without needing a real Foundry environment at all.
 *
 * Identifier binding: `core.entities` UUIDs are stored as a document
 * flag (`flags["dnd-ai-adapter"].entityId`) on the linked Foundry
 * actor/scene/item/combat — Foundry's own idiomatic per-document
 * metadata mechanism, not a separate module-side mapping table that
 * could drift from the documents it describes. Actor/scene/item linking
 * additionally calls the real `map_external_identifier` endpoint so the
 * *server* also knows the association (`integration.
 * external_identifiers`) — an encounter has no such endpoint (`narrative.
 * encounters` rows are not `core.entities` rows, so `map_external_
 * identifier` does not apply to them at all); `linkEncounter` is
 * therefore local-only, pointing this Combat document at an
 * `encounter_id` the GM already obtained by starting the encounter
 * through the platform directly (see README).
 */
export class SyncEngine {
  /**
   * @param {object} deps
   * @param {import("./api-client.mjs").DndAiApiClient} deps.client
   * @param {() => {externalSystemId: string}} deps.getSettings
   * @param {(ms: number) => Promise<void>} [deps.sleep] - forwarded to
   *   `withRetry`; injectable for deterministic tests.
   */
  constructor({ client, getSettings, sleep } = {}) {
    this._client = client;
    this._getSettings = getSettings;
    this._sleep = sleep;
    this._selfUpdating = new Set();
  }

  // -- linking -----------------------------------------------------------

  getLinkedEntityId(document) {
    return document.getFlag("dnd-ai-adapter", FLAG_ENTITY_ID) ?? null;
  }

  async linkActor(actor, entityId) {
    await this._client.mapExternalIdentifier({
      entityId,
      externalKind: "actor",
      externalId: actor.id,
    });
    await actor.setFlag("dnd-ai-adapter", FLAG_ENTITY_ID, entityId);
  }

  async linkScene(scene, entityId) {
    await this._client.mapExternalIdentifier({
      entityId,
      externalKind: "scene",
      externalId: scene.id,
    });
    await scene.setFlag("dnd-ai-adapter", FLAG_ENTITY_ID, entityId);
  }

  async linkItem(item, entityId) {
    await this._client.mapExternalIdentifier({ entityId, externalKind: "item", externalId: item.id });
    await item.setFlag("dnd-ai-adapter", FLAG_ENTITY_ID, entityId);
  }

  /** Local-only — see this module's own docstring for why an encounter
   * has no server-side mapping call to make. */
  async linkEncounter(combat, encounterId) {
    await combat.setFlag("dnd-ai-adapter", FLAG_ENTITY_ID, encounterId);
  }

  // -- combat --------------------------------------------------------------

  _requireLinked(document, label) {
    const entityId = this.getLinkedEntityId(document);
    if (!entityId) {
      throw new Error(`${label} is not linked to a D&D AI canonical identifier yet.`);
    }
    return entityId;
  }

  async submitCombatTurn({
    combat,
    actor,
    target = null,
    worldTimeId,
    actionKind = "attack",
    hit = null,
    damageAmount = null,
    damageTypeId = null,
    resultingConditionId = null,
    itemInstanceId = null,
    spellId = null,
    interactionTypeCode = "attack",
    sessionId = null,
    eventDetails = null,
  }) {
    const encounterId = this._requireLinked(combat, "This combat encounter");
    const actorEntityId = this._requireLinked(actor, `Actor "${actor.name}"`);
    const targetEntityId = target ? this._requireLinked(target, `Actor "${target.name}"`) : null;

    const roundNumber = combat.round;
    const turnOrder = combat.turn ?? 0;

    const operationId = stableOperationId("combat", {
      encounterId,
      roundNumber,
      turnOrder,
      actorEntityId,
      targetEntityId,
      actionKind,
      hit,
      damageAmount,
    });

    const payload = {
      external_system_id: this._getSettings().externalSystemId,
      external_operation_id: operationId,
      encounter_id: encounterId,
      round_number: roundNumber,
      turn_order: turnOrder,
      actor_entity_id: actorEntityId,
      world_time_id: worldTimeId,
      action_kind: actionKind,
      target_entity_id: targetEntityId,
      item_instance_id: itemInstanceId,
      spell_id: spellId,
      hit,
      damage_amount: damageAmount,
      damage_type_id: damageTypeId,
      resulting_condition_id: resultingConditionId,
      interaction_type_code: interactionTypeCode,
      session_id: sessionId,
      event_details: eventDetails,
      raw_payload: null,
    };

    const result = await withRetry(() => this._client.applyCombatSync(payload), {
      sleep: this._sleep,
    });
    if (target && result.new_hit_points !== null && result.new_hit_points !== undefined) {
      await this.applyHitPoints(target, result.new_hit_points);
    }
    return result;
  }

  // -- non-combat character state -------------------------------------------

  async submitHpChange(actor, { worldTimeId, delta, sessionId = null, details = null }) {
    const characterId = this._requireLinked(actor, `Actor "${actor.name}"`);
    const idempotencyKey = stableOperationId("hp", { characterId, worldTimeId, delta });
    const result = await withRetry(
      () =>
        this._client.adjustHitPoints(
          characterId,
          { world_time_id: worldTimeId, delta, session_id: sessionId, details },
          idempotencyKey,
        ),
      { sleep: this._sleep },
    );
    await this.applyHitPoints(actor, result.new_hit_points);
    return result;
  }

  async submitConditionApply(
    actor,
    { worldTimeId, conditionId, sourceDescription = null, sessionId = null, details = null },
  ) {
    const characterId = this._requireLinked(actor, `Actor "${actor.name}"`);
    const idempotencyKey = stableOperationId("condition-apply", { characterId, worldTimeId, conditionId });
    return withRetry(
      () =>
        this._client.applyCondition(
          characterId,
          {
            world_time_id: worldTimeId,
            condition_id: conditionId,
            source_description: sourceDescription,
            session_id: sessionId,
            details,
          },
          idempotencyKey,
        ),
      { sleep: this._sleep },
    );
  }

  async submitConditionRemove(actor, conditionId, { worldTimeId, sessionId = null, details = null }) {
    const characterId = this._requireLinked(actor, `Actor "${actor.name}"`);
    const idempotencyKey = stableOperationId("condition-remove", {
      characterId,
      worldTimeId,
      conditionId,
    });
    return withRetry(
      () =>
        this._client.removeCondition(
          characterId,
          conditionId,
          { world_time_id: worldTimeId, session_id: sessionId, details },
          idempotencyKey,
        ),
      { sleep: this._sleep },
    );
  }

  async submitResourceChange(
    actor,
    { worldTimeId, resourceDefinitionId, delta, sessionId = null, details = null },
  ) {
    const characterId = this._requireLinked(actor, `Actor "${actor.name}"`);
    const idempotencyKey = stableOperationId("resource", {
      characterId,
      worldTimeId,
      resourceDefinitionId,
      delta,
    });
    return withRetry(
      () =>
        this._client.adjustResource(
          characterId,
          {
            world_time_id: worldTimeId,
            resource_definition_id: resourceDefinitionId,
            delta,
            session_id: sessionId,
            details,
          },
          idempotencyKey,
        ),
      { sleep: this._sleep },
    );
  }

  // -- write-back / loop suppression ----------------------------------------

  /** True while this engine's own `applyHitPoints()` write is in flight
   * for `actorId` — `hooks.mjs`'s `updateActor` handler checks this
   * before treating a change as GM/player-originated and re-submitting
   * it, which is what prevents "server confirms HP -> client writes HP
   * -> client's own write re-triggers a sync -> ..." from ever
   * happening. */
  isSelfUpdating(actorId) {
    return this._selfUpdating.has(actorId);
  }

  async applyHitPoints(actor, newHitPoints) {
    if (newHitPoints === null || newHitPoints === undefined) {
      return;
    }
    if (actor.system?.attributes?.hp?.value === newHitPoints) {
      return;
    }
    this._selfUpdating.add(actor.id);
    try {
      await actor.update({ "system.attributes.hp.value": newHitPoints });
    } finally {
      // Cleared on the next macrotask, not synchronously: Foundry
      // dispatches the resulting `updateActor` hook asynchronously
      // relative to this update() call's own resolution, so clearing
      // the guard immediately here could race ahead of the very hook
      // firing this guard exists to suppress.
      setTimeout(() => this._selfUpdating.delete(actor.id), 0);
    }
  }

  // -- reconnect / restoration ----------------------------------------------

  /** Called from `Hooks.once("ready", ...)` — a fresh page load or
   * reconnect. Issues only GET requests (`getCharacter`) and local
   * writes; never resubmits any combat/HP/condition/resource change.
   * There is no client-side queue of unconfirmed operations to replay
   * on reconnect — anything not already confirmed by the server before
   * the reload is simply gone, which is the safe default (replaying a
   * local queue is exactly the "duplicate event" risk the exit
   * criterion warns about); the GM re-does the action from Foundry's
   * own UI, and that resubmission is itself idempotent server-side
   * because it hashes to the same stable operation id as before
   * (`ids.mjs`). */
  async restoreFromServer(actors) {
    const restored = [];
    for (const actor of actors) {
      const characterId = this.getLinkedEntityId(actor);
      if (!characterId) {
        continue;
      }
      const character = await this._client.getCharacter(characterId);
      await this.applyHitPoints(actor, character.current_hit_points);
      restored.push({ actor, character });
    }
    return restored;
  }
}
