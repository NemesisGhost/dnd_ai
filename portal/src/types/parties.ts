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
