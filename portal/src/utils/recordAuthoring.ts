// What the caller may do to one record, as the server resolved it (ADR 0020). The portal reads
// these fields and nothing else to decide which preparation, review and edit controls to offer:
// it never infers authority from a role name, a category or the shape of a record. They are
// presentation previews; the command or endpoint still re-checks, and a flag never authorizes
// anything.
//
//   can_read_private     the private side of the definition (lifecycle, drafts, GM-only
//                        preparation) may be read; a read of it is never sent without it
//   can_edit             the definition may be edited, including preparing and withdrawing a draft
//   can_review           the definition may be approved, published, superseded, archived or restored
//   campaign_originated  the record is one of the campaign-owned exceptions (player-character
//                        identity, item instances): the campaign alone authorizes it
export interface RecordAuthoring {
    campaign_originated: boolean
    can_read_private: boolean
    can_edit: boolean
    can_review: boolean
}

// What a record that carries no `authoring` field grants: nothing. A response without it is an
// older or malformed one, and holding back a control is the safe failure.
export const NO_RECORD_AUTHORING: RecordAuthoring = {
    campaign_originated: false,
    can_read_private: false,
    can_edit: false,
    can_review: false,
}

export function authoringOf(detail: { authoring?: RecordAuthoring } | null | undefined): RecordAuthoring {
    return detail?.authoring ?? NO_RECORD_AUTHORING
}
