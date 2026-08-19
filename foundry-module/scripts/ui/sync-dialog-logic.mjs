/**
 * The pure dispatch logic behind the "D&D AI Sync" manual action panel —
 * split from `sync-dialog-app.mjs` for the same reason
 * `connection-setup-logic.mjs` is split from `connection-setup-app.mjs`:
 * importable and testable under Node without a real Foundry
 * `Application` runtime.
 *
 * Per this module's documented scope boundary (`foundry-module/
 * README.md`), combat-turn/condition/resource submissions are always
 * explicit GM/player actions through this panel — never inferred by
 * scraping dnd5e's own chat-card/damage-application internals, which
 * aren't stable or portable enough to integrate against without a real
 * running instance to verify against. HP sync is the one exception,
 * wired directly to the `updateActor` hook (`hooks.mjs`) since
 * `system.attributes.hp.value` is a stable, well-known dnd5e path.
 */

export const ACTION_COMBAT_TURN = "combat-turn";
export const ACTION_APPLY_CONDITION = "apply-condition";
export const ACTION_REMOVE_CONDITION = "remove-condition";
export const ACTION_ADJUST_RESOURCE = "adjust-resource";

/** Converts a raw Foundry `FormDataExtended#object` (all string values)
 * plus the resolved actor/target/combat documents into the call
 * `SyncEngine` expects, and invokes it. Returns whatever the engine
 * method resolves to. Throws (never swallows) on an unknown
 * `actionType` or a missing required field — the caller (the real
 * ApplicationV2 form handler, or a test) is responsible for turning that
 * into a user-facing message. */
export async function dispatchSyncAction(engine, actionType, { actor, target = null, combat = null, formValues, worldTimeId }) {
  switch (actionType) {
    case ACTION_COMBAT_TURN:
      return engine.submitCombatTurn({
        combat,
        actor,
        target,
        worldTimeId,
        hit: formValues.hit === "true" ? true : formValues.hit === "false" ? false : null,
        damageAmount: formValues.damageAmount ? Number(formValues.damageAmount) : null,
      });
    case ACTION_APPLY_CONDITION:
      requireField(formValues, "conditionId");
      return engine.submitConditionApply(actor, {
        worldTimeId,
        conditionId: formValues.conditionId,
        sourceDescription: formValues.sourceDescription || null,
      });
    case ACTION_REMOVE_CONDITION:
      requireField(formValues, "conditionId");
      return engine.submitConditionRemove(actor, formValues.conditionId, { worldTimeId });
    case ACTION_ADJUST_RESOURCE:
      requireField(formValues, "resourceDefinitionId");
      requireField(formValues, "delta");
      return engine.submitResourceChange(actor, {
        worldTimeId,
        resourceDefinitionId: formValues.resourceDefinitionId,
        delta: Number(formValues.delta),
      });
    default:
      throw new Error(`Unknown D&D AI sync action: ${actionType}`);
  }
}

function requireField(formValues, key) {
  if (!formValues[key]) {
    throw new Error(`Missing required field: ${key}`);
  }
}

/** Builds the template context: every actor in `actors` that has a
 * linked D&D AI entity id, for the panel's actor picker. Pure —
 * `engine.getLinkedEntityId` is a synchronous flag read. */
export function prepareSyncDialogContext(engine, actors) {
  return {
    linkedActors: actors
      .filter((actor) => engine.getLinkedEntityId(actor))
      .map((actor) => ({ id: actor.id, name: actor.name })),
  };
}
