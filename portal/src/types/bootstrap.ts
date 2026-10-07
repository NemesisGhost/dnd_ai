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
  // The caller's capabilities on this campaign's *world* (ADR 0020), independent of
  // `capabilities`. Optional only so older fixtures keep compiling; the server always
  // sends it. Decides what to offer; the server re-checks every request.
  world_capabilities?: readonly string[]
}

export interface FeatureManifest {
  ask: boolean
  ai_summaries: boolean
  gm_briefs: boolean
  cited_rules: boolean
}

export type CampaignStartupMode = "resume_last_visited" | "preferred_campaign"

// Stored startup values, already filtered by the server to campaigns the
// caller can currently access (docs/UI_DESIGN.md §4.7). An ID here never
// grants access.
export interface CampaignPreferences {
  startup_mode: CampaignStartupMode
  preferred_campaign_id: string | null
  last_visited_campaign_id: string | null
}

export interface SessionBootstrap {
  user: UserSummary
  csrf_token: string
  browser_session_id: string | null
  // The caller's unrevoked system roles (admin, gm, player, observer): display
  // only. Optional so older fixtures keep compiling; the server always sends it.
  system_roles?: readonly string[]
  // Server-computed global (non-campaign) capabilities for this user: the union
  // of the system capabilities of their system roles (accounts.manage,
  // system_roles.manage, system_roles.grant_admin while the deployment enables
  // it, world.create, campaign.host, world.administer; ADR 0020). Optional only
  // so older fixtures keep compiling; the server always sends it. Never inferred
  // client-side (see utils/systemAccess.ts and utils/worldAccess.ts).
  global_capabilities?: readonly string[]
  // Server-computed landing campaign (docs/UI_DESIGN.md §4.2): null means
  // "no campaign to resume" and the portal lands on /campaigns. Always null or
  // one of `campaigns`.
  startup_campaign_id: string | null
  campaign_preferences: CampaignPreferences
  campaigns: CampaignContext[]
  features: FeatureManifest
}