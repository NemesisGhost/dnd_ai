// Authoritative response shape for GET /auth/session.
export interface UserSummary {
  user_id: string
  display_name: string
}

export interface AuthorizedParty {
  party_id: string
  party_name: string
}

export interface CharacterPerspective {
  character_id: string
  character_name: string
  authorized_parties: AuthorizedParty[]
}

export interface CampaignContext {
  campaign_id: string
  campaign_name: string
  world_id: string | null
  world_name: string | null
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
  // Phase 13E checkpoint 9: the only server-authoritative signal for
  // whether to render an admin surface at all (CP 10's /admin/accounts
  // page) — campaign-scoped access.manage grants nothing here.
  is_platform_administrator: boolean
  selected_campaign_id: string | null
  campaigns: CampaignContext[]
  features: FeatureManifest
}