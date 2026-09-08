import type { CampaignContext } from "../types/bootstrap"

interface CampaignSelectionPathOptions {
  pathname: string
  targetCampaign: CampaignContext
  askEnabled: boolean
}

const ordinaryCampaignSections: ReadonlySet<string> =
  new Set([
    "home",
    "world",
    "characters",
    "quests",
    "sessions",
    "knowledge",
  ])

export function buildCampaignSelectionPath({
  pathname,
  targetCampaign,
  askEnabled,
}: CampaignSelectionPathOptions): string {
  const pathSegments = pathname
    .split("/")
    .filter((segment) => segment.length > 0)

  const requestedSection = pathSegments[2]

  const canPreserveOrdinarySection =
    requestedSection !== undefined &&
    ordinaryCampaignSections.has(requestedSection)

  const canPreserveAsk =
    requestedSection === "ask" &&
    askEnabled

  const canPreserveAccess =
    requestedSection === "access" &&
    targetCampaign.capabilities.includes(
      "access.manage",
        )

  const selectedSection =
    canPreserveOrdinarySection ||
    canPreserveAsk ||
    canPreserveAccess
      ? requestedSection
      : "home"

  return `/app/${targetCampaign.campaign_id}/${selectedSection}`
}