import { HitPointsMeter } from "./HitPointsMeter"
import { useCharacter } from "../hooks/useCharacter"

interface CharacterContextDetailsProps {
  campaignId: string
  characterId: string
}

// Compact, read-only character facts for the Character section of
// CampaignContextPanel. Self-fetching leaf (same pattern as CharacterBoundary),
// but renders panel-sized states rather than a full-width placeholder page.
// Never emits raw identifiers.
export function CharacterContextDetails({
  campaignId,
  characterId,
}: CharacterContextDetailsProps) {
  const { state } = useCharacter(campaignId, characterId)

  if (state.status === "loading") {
    return (
      <p className="campaign-context-panel__note">
        Loading character…
      </p>
    )
  }

  if (state.status !== "success") {
    return (
      <p className="campaign-context-panel__note">
        Character details unavailable.
      </p>
    )
  }

  const character = state.character

  const hasLiveState =
    character.conditions !== null && character.resources !== null

  return (
    <dl className="campaign-context-panel__detail">
      <div className="campaign-context-panel__detail-row">
        <dt>Species</dt>
        <dd>{character.species_code}</dd>
      </div>

      <div className="campaign-context-panel__detail-row">
        <dt>Size</dt>
        <dd>{character.size_category}</dd>
      </div>

      {hasLiveState && (
        <>
          <div className="campaign-context-panel__detail-row">
            <dt>Hit points</dt>
            <dd>
              {character.current_hit_points !== null &&
              character.maximum_hit_points !== null ? (
                <HitPointsMeter
                  currentHitPoints={character.current_hit_points}
                  maximumHitPoints={character.maximum_hit_points}
                />
              ) : (
                "Not recorded"
              )}
            </dd>
          </div>

          <div className="campaign-context-panel__detail-row">
            <dt>Temporary hit points</dt>
            <dd>
              {character.temporary_hit_points ?? "Not recorded"}
            </dd>
          </div>

          <div className="campaign-context-panel__detail-row">
            <dt>Exhaustion level</dt>
            <dd>{character.exhaustion_level ?? "Not recorded"}</dd>
          </div>

          <div className="campaign-context-panel__detail-row">
            <dt>Death saves</dt>
            <dd>
              {character.death_save_successes ?? 0}
              {" / "}
              {character.death_save_failures ?? 0}
            </dd>
          </div>

          {character.conditions?.map((condition) => (
            <div
              className="campaign-context-panel__detail-row"
              key={condition.condition_code}
            >
              <dt>{condition.condition_code}</dt>
              <dd>{condition.source_description ?? "—"}</dd>
            </div>
          ))}

          {character.resources?.map((resource) => (
            <div
              className="campaign-context-panel__detail-row"
              key={resource.resource_code}
            >
              <dt>{resource.resource_code}</dt>
              <dd>
                {resource.current_amount}
                {" / "}
                {resource.maximum_amount}
              </dd>
            </div>
          ))}
        </>
      )}
    </dl>
  )
}
