// The GM's list of who a character's released public profile has been revealed to
// (GET /campaigns/{id}/characters/{id}/revelations). Exactly the keys the API returns: the reason a
// revelation was made under is stored by the server and never returned, so it has no field here.

export type RevelationAudienceKind = "member" | "access_group" | "campaign_current" | "campaign_current_and_future"

export type RevelationEndReason = "revoked" | "target_membership_ended" | "access_group_deactivated"

export interface RevelationSnapshotMember {
    campaign_membership_id: string
    display_name: string
    added_at: string
    removed_at: string | null
    // "membership_ended" when removed_at is set.
    removal_reason: string | null
}

export interface CharacterRevelation {
    character_revelation_id: string
    audience_kind: RevelationAudienceKind
    target_campaign_membership_id: string | null
    target_member_name: string | null
    target_access_group_id: string | null
    target_access_group_name: string | null
    created_by_membership_id: string
    created_by_name: string
    authority_source: "owner" | "delegation"
    created_at: string
    live: boolean
    ended_at: string | null
    end_reason: RevelationEndReason | null
    // Only for `campaign_current`.
    audience_size?: number
    snapshot_members?: RevelationSnapshotMember[]
}

export interface CharacterRevelationsRead {
    character_id: string
    revelations: CharacterRevelation[]
}
