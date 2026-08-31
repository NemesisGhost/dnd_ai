import type { CampaignContext } from "../types/bootstrap"

interface CampaignContextBarProps {
  campaign: CampaignContext
}

export function CampaignContextBar({
  campaign,
}: CampaignContextBarProps) {
  const selectedCharacter = campaign.character_perspectives.find(
    (character) =>
      character.character_id === campaign.selected_character_id,
  )

  const perspectiveName =
    selectedCharacter?.character_name ?? "No character selected"

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
          <dd>{campaign.timeline_name ?? "No timeline selected"}</dd>
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
    </section>
  )
}