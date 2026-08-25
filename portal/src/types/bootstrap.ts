// Provisional Phase 13A shape; the Phase 13B API contract remains authoritative.

export interface UserSummary {
  userId: string
  displayName: string
}

export interface CharacterPerspective {
  characterId: string
  characterName: string
}

export interface CampaignContext {
  campaignId: string
  campaignName: string
  timelineId: string
  timelineName: string
  roles: string[]
  characterPerspectives: CharacterPerspective[]
  selectedCharacterId: string | null
}

export interface FeatureManifest {
  ask: boolean
  aiSummaries: boolean
  gmBriefs: boolean
  citedRules: boolean
}

export interface SessionBootstrap {
  user: UserSummary
  selectedCampaignId: string | null
  campaigns: CampaignContext[]
  features: FeatureManifest
}