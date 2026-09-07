import type { ReactNode } from "react"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import type { CampaignContext } from "../types/bootstrap"
import { CharacterPerspectiveSelector } from "./CharacterPerspectiveSelector"

interface CampaignContextPanelProps {
  campaign: CampaignContext
  // Composition points for dimensions the current frontend/backend
  // contracts do not yet expose. Left undefined until real authorized data
  // is available; see the "not yet supported" note in the component doc.
  worldName?: string | null
  currentWorldTime?: ReactNode
}

// Answers "what campaign context and viewing perspective am I using?" for
// the campaign shell. Distinct from the InfoBox family, which answers
// "what are the facts about the entity on this page?" Reuses the
// established character-perspective context/selector rather than
// introducing a second perspective state.
export function CampaignContextPanel({
  campaign,
  worldName,
  currentWorldTime,
}: CampaignContextPanelProps) {
  const { getSelectedCharacterId, selectCharacter } = usePerspective()

  const selectedCharacterId = getSelectedCharacterId(
    campaign.campaign_id,
  )

  const selectedCharacter = campaign.character_perspectives.find(
    (character) => character.character_id === selectedCharacterId,
  )

  const perspectiveName =
    selectedCharacter?.character_name ?? "No character selected"

  const hasWorld = worldName !== undefined && worldName !== null
  const hasTime =
    currentWorldTime !== undefined && currentWorldTime !== null

  return (
    <details className="campaign-context-panel" open>
      <summary className="campaign-context-panel__summary">
        Campaign context: {campaign.campaign_name} — Viewing as{" "}
        {perspectiveName}
      </summary>

      <dl className="campaign-context-panel__list">
        {hasWorld && (
          <div className="campaign-context-panel__item">
            <dt>World</dt>
            <dd>{worldName}</dd>
          </div>
        )}

        <div className="campaign-context-panel__item">
          <dt>Campaign</dt>
          <dd>{campaign.campaign_name}</dd>
        </div>

        {hasTime && (
          <div className="campaign-context-panel__item">
            <dt>Time</dt>
            <dd>{currentWorldTime}</dd>
          </div>
        )}

        <div className="campaign-context-panel__item">
          <dt>Viewing as</dt>
          <dd>
            <CharacterPerspectiveSelector
              perspectives={campaign.character_perspectives}
              selectedCharacterId={selectedCharacterId}
              onSelectCharacter={(characterId) =>
                selectCharacter(campaign.campaign_id, characterId)
              }
            />
          </dd>
        </div>
      </dl>
    </details>
  )
}
