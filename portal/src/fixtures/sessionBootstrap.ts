import type { SessionBootstrap } from "../types/bootstrap"

export const sessionBootstrapFixture = {
  user: {
    userId: "user-fixture-001",
    displayName: "Campaign Administrator",
  },

  selectedCampaignId: "campaign-mundivita",

  campaigns: [
    {
      campaignId: "mundivita",
      campaignName: "Mundivita",
      timelineId: "timeline-primary",
      timelineName: "Primary Timeline",
      roles: ["Game Master"],
      characterPerspectives: [
        {
          characterId: "character-ixamarra",
          characterName: "Ixamarra",
        },
      ],
      selectedCharacterId: "character-ixamarra",
    },
  ],

  features: {
    ask: false,
    aiSummaries: false,
    gmBriefs: false,
    citedRules: false,
  },
} satisfies SessionBootstrap