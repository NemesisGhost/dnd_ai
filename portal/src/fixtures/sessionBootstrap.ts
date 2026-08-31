import type { SessionBootstrap } from "../types/bootstrap"

export const sessionBootstrapFixture = {
  user: {
    user_id: "user-fixture-001",
    display_name: "Campaign Administrator",
  },

  selected_campaign_id: "mundivita",
  csrf_token: 'fixture-csrf-token-not-a-secret',
  browser_session_id: "browser-session-fixture-001",
  campaigns: [
    {
      campaign_id: "mundivita",
      campaign_name: "Mundivita",
      timeline_id: "timeline-primary",
      timeline_name: "Primary Timeline",
      roles: ["campaign_owner"],
      character_perspectives: [
        {
          character_id: "character-ixamarra",
          character_name: "Ixamarra",
        },
      ],
      selected_character_id: "character-ixamarra",
      capabilities: ['access.manage']
    },
  ],

  features: {
    ask: false,
    ai_summaries: false,
    gm_briefs: false,
    cited_rules: false,
  },
} satisfies SessionBootstrap