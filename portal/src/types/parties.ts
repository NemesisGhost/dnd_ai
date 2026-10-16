// Party definition contracts (Phase 15 checkpoint 15.2C-1).

export interface PartyItem {
    party_id: string
    name: string
    description: string | null
    lifecycle_status: "active" | "archived"
    row_version: number
    // Present only for people who can edit canon.
    available_actions?: ("update" | "archive" | "restore")[]
}

// The parties a character currently belongs to (GET .../characters/{id}/parties): an informational
// affiliation list, complete and never paged. `can_open` says whether the caller may open a
// party's own page; the server decides it.
export interface CharacterParties {
    character_id: string
    can_open: boolean
    items: { party_id: string; name: string }[]
}

export interface PartyList {
    can_create: boolean
    items: PartyItem[]
}

export interface PartyReceipt {
    party_id: string
    row_version: number
    created: boolean
    changed: boolean
}

export interface PartyFieldsBody {
    name: string
    description: string | null
}

export interface PartyMember {
    party_membership_id: string
    character_id: string
    character_name: string
    joined_at: string
    left_at: string | null
    joined_reason: string | null
    left_reason: string | null
    is_current: boolean
}

export interface PartyMembers {
    party: PartyItem
    members: PartyMember[]
}

export interface MembershipReceipt {
    party_id: string
    party_membership_id: string
    // The new row version of the party.
    row_version: number
    event_id: string
    created: boolean
    changed: boolean
}
