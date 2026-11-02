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
    // The campaign clock the list was evaluated at. With `clock_unset` there is none: current
    // membership is undetermined and `items` is empty, which is not "no memberships". Optional
    // only for an older server.
    as_of?: string | null
    clock_unset?: boolean
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

// The server's classification of a membership against the campaign clock (never recomputed here):
// `in_effect` is current, `not_started` upcoming, `ended` history, `clock_unset` undetermined.
export type MembershipPeriodStatus = "in_effect" | "not_started" | "ended" | "clock_unset"

export interface PartyMember {
    party_membership_id: string
    character_id: string
    character_name: string
    joined_at: string
    left_at: string | null
    joined_reason: string | null
    left_reason: string | null
    // True only when in effect at the campaign clock (false when the clock is unset).
    is_current: boolean
    period_status: MembershipPeriodStatus
}

export interface PartyMembers {
    party: PartyItem
    // The clock the statuses were classified at; null with `clock_unset` when none is set.
    as_of?: string | null
    clock_unset?: boolean
    members: PartyMember[]
}

// GET .../parties/{id}/roster (campaign.view): the read-only roster. Current members only,
// identity and name; `member_count` is the length of what is listed.
export interface PartyRoster {
    party: PartyItem
    as_of?: string | null
    // True when no campaign clock is set: current membership cannot be determined, so an empty
    // `members` list does not mean the party has no members.
    clock_unset?: boolean
    member_count: number
    members: { character_id: string; character_name: string }[]
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
