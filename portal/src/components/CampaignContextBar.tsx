import { usePerspective } from "../context/CharacterPerspectiveContext"
import type { CampaignContext } from "../types/bootstrap"
import { CharacterPerspectiveSelector } from "./CharacterPerspectiveSelector"

interface CampaignContextBarProps {
  campaign: CampaignContext
}

export function CampaignContextBar({
  campaign,
}: CampaignContextBarProps) {
  const {
    getSelectedCharacterId,
    selectCharacter,
  } = usePerspective()

  const selectedCharacterId =
    getSelectedCharacterId(campaign.campaign_id)

  const selectedCharacter =
    campaign.character_perspectives.find(
      (character) =>
        character.character_id === selectedCharacterId,
    )

  const perspectiveName =
    selectedCharacter?.character_name ??
    "No character selected"

  const roleNames =
    campaign.roles.length > 0
      ? campaign.roles.join(", ")
      : "No role assigned"

  return (
    <section
      className="campaign-context"
      aria-label="Current campaign context"
    >
      <dl className="campaign-context__list">
        <div className="campaign-context__item">
          <dt>Campaign</dt>
          <dd>{campaign.campaign_name}</dd>
        </div>

        <div className="campaign-context__item">
          <dt>Timeline</dt>
          <dd>
            {campaign.timeline_name ?? "No timeline selected"}
          </dd>
        </div>

        <div className="campaign-context__item">
          <dt>Role</dt>
          <dd>{roleNames}</dd>
        </div>

        <div className="campaign-context__item">
          <dt>Perspective</dt>
          <dd>{perspectiveName}</dd>
        </div>
      </dl>

      <CharacterPerspectiveSelector
        perspectives={campaign.character_perspectives}
        selectedCharacterId={selectedCharacterId}
        onSelectCharacter={(characterId) =>
          selectCharacter(
            campaign.campaign_id,
            characterId,
          )
        }
      />
    </section>
  )
}