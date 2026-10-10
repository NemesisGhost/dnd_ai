// The Knowledge "Member preview" contracts (docs/UI_DESIGN.md, Member preview).
// The server projects everything for the selected member (dnd_ai.api.preview); these shapes
// only describe what comes back.

export interface PreviewPartyRef {
    party_id: string
    party_name: string
}

export interface PreviewCharacterPerspective {
    character_id: string
    character_name: string
    authorized_parties: PreviewPartyRef[]
}

// What the previewed member may choose as a Knowledge perspective: exactly the perspectives
// their own session would offer them.
export interface PreviewPerspectives {
    display_name: string
    roles: string[]
    character_perspectives: PreviewCharacterPerspective[]
}
