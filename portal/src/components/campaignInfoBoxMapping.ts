import type { CampaignContext } from "../types/bootstrap"
import type { InfoBoxProps } from "../types/infobox"

const NOT_AVAILABLE = "Not available"

// Translates the authorized CampaignContext already delivered by session
// bootstrap into the generic InfoBox model. Deliberately does not expose
// campaign_id, timeline_id, selected_character_id, or capabilities: those
// are internal identifiers/authorization grants, not user-facing facts.
export function campaignToInfoBoxProps(
  campaign: CampaignContext,
): InfoBoxProps {
  const roleLabels =
    campaign.roles.length > 0
      ? campaign.roles.join(", ")
      : NOT_AVAILABLE

  const characterNames =
    campaign.character_perspectives.length > 0
      ? campaign.character_perspectives
          .map((character) => character.character_name)
          .join(", ")
      : NOT_AVAILABLE

  return {
    title: campaign.campaign_name,
    subtitle: "Campaign",
    sections: [
      {
        heading: "Overview",
        rows: [
          {
            label: "Timeline",
            value: campaign.timeline_name ?? NOT_AVAILABLE,
          },
          {
            label: "Your roles",
            value: roleLabels,
          },
        ],
      },
      {
        heading: "Characters",
        rows: [
          {
            label: "Playable perspectives",
            value: characterNames,
          },
        ],
      },
    ],
    relatedLinks: [
      {
        label: "View characters",
        to: `/app/${campaign.campaign_id}/characters`,
      },
    ],
  }
}
