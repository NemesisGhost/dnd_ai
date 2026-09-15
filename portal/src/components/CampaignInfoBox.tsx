import { campaignToInfoBoxProps } from "./campaignInfoBoxMapping"
import { InfoBox } from "./InfoBox"
import type { CampaignContext } from "../types/bootstrap"

interface CampaignInfoBoxProps {
  campaign: CampaignContext
}

export function CampaignInfoBox({ campaign }: CampaignInfoBoxProps) {
  return <InfoBox {...campaignToInfoBoxProps(campaign)} />
}
