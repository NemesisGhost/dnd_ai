// Authoritative response shape for GET /auth/session.
export interface UserSummary {
  user_id: string
  display_name: string
}

export interface CharacterPerspective {
  character_id: string
  character_name: string
}

export interface CampaignContext {
  campaign_id: string
  campaign_name: string
  timeline_id: string | null
  timeline_name: string | null
  roles: string[]
  character_perspectives: CharacterPerspective[]
  selected_character_id: string | null
  capabilities: string[]
}

export interface FeatureManifest {
  ask: boolean
  ai_summaries: boolean
  gm_briefs: boolean
  cited_rules: boolean
}

export interface SessionBootstrap {
  user: UserSummary
  csrf_token: string
  browser_session_id: string | null
  selected_campaign_id: string | null
  campaigns: CampaignContext[]
  features: FeatureManifest
}