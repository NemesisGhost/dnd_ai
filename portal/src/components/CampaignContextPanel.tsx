import { useId } from "react"
import type { CampaignContext } from "../types/bootstrap"
import { CharacterContextDetails } from "./CharacterContextDetails"
import { CharacterPerspectiveSelector } from "./CharacterPerspectiveSelector"

interface CampaignContextPanelProps {
  // The active campaign, plus the full authorized list for the campaign selector.
  campaign: CampaignContext
  campaigns: CampaignContext[]
  selectedCharacterId: string | null
  onSelectCampaign: (campaignId: string) => void
  onSelectCharacter: (characterId: string | null) => void
  // Reserved: read-only until the backend exposes authorized worlds.
  worldName?: string | null
}

// One compact, infobox-styled panel describing the viewer's current vantage
// point as a World -> Campaign -> Timeline -> Character hierarchy. Purely
// presentational: it takes the current selections and reports changes through
// callbacks. CampaignLayout owns the routing and perspective wiring. World and
// Timeline are not yet selectable (no authorized list / selection API), so they
// are shown read-only / disabled. Never renders raw identifiers.
export function CampaignContextPanel({
  campaign,
  campaigns,
  selectedCharacterId,
  onSelectCampaign,
  onSelectCharacter,
  worldName,
}: CampaignContextPanelProps) {
  const worldHeadingId = useId()
  const campaignHeadingId = useId()
  const timelineHeadingId = useId()
  const characterHeadingId = useId()

  const selectedCharacter = campaign.character_perspectives.find(
    (character) => character.character_id === selectedCharacterId,
  )

  const perspectiveName =
    selectedCharacter?.character_name ?? "No character perspective selected"

  const rolesLabel =
    campaign.roles.length > 0
      ? campaign.roles.join(", ")
      : "Not available"

  return (
    <details className="campaign-context-panel" open>
      <summary className="campaign-context-panel__summary">
        Campaign context: {campaign.campaign_name}
        {" — "}Viewing as {perspectiveName}
      </summary>

      <div className="campaign-context-panel__body">
        <section
          className="campaign-context-panel__section"
          aria-labelledby={worldHeadingId}
        >
          <h3
            id={worldHeadingId}
            className="campaign-context-panel__section-heading"
          >
            World
          </h3>
          <p className="campaign-context-panel__value">
            {worldName ?? "Not available"}
          </p>
        </section>

        <section
          className="campaign-context-panel__section"
          aria-labelledby={campaignHeadingId}
        >
          <h3
            id={campaignHeadingId}
            className="campaign-context-panel__section-heading"
          >
            Campaign
          </h3>
          <select
            className="campaign-context-panel__control"
            aria-labelledby={campaignHeadingId}
            value={campaign.campaign_id}
            onChange={(event) => {
              const nextCampaignId = event.currentTarget.value
              if (nextCampaignId !== campaign.campaign_id) {
                onSelectCampaign(nextCampaignId)
              }
            }}
          >
            {campaigns.map((candidate) => (
              <option
                key={candidate.campaign_id}
                value={candidate.campaign_id}
              >
                {candidate.campaign_name}
              </option>
            ))}
          </select>

          <dl className="campaign-context-panel__detail">
            <div className="campaign-context-panel__detail-row">
              <dt>Your roles</dt>
              <dd>{rolesLabel}</dd>
            </div>
          </dl>
        </section>

        <section
          className="campaign-context-panel__section"
          aria-labelledby={timelineHeadingId}
        >
          <h3
            id={timelineHeadingId}
            className="campaign-context-panel__section-heading"
          >
            Timeline
          </h3>
          <select
            className="campaign-context-panel__control"
            aria-labelledby={timelineHeadingId}
            value="current"
            disabled
          >
            <option value="current">
              {campaign.timeline_name ?? "No timeline selected"}
            </option>
          </select>
        </section>

        <section
          className="campaign-context-panel__section"
          aria-labelledby={characterHeadingId}
        >
          <h3
            id={characterHeadingId}
            className="campaign-context-panel__section-heading"
          >
            Character
          </h3>
          <CharacterPerspectiveSelector
            perspectives={campaign.character_perspectives}
            selectedCharacterId={selectedCharacterId}
            onSelectCharacter={onSelectCharacter}
          />

          {selectedCharacterId !== null && (
            <CharacterContextDetails
              campaignId={campaign.campaign_id}
              characterId={selectedCharacterId}
            />
          )}
        </section>
      </div>
    </details>
  )
}
