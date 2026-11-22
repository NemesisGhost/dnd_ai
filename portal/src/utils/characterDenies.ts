import type {
    AccessResourceGrantSummary,
    AssignableCharacter,
    DeniableCharacterCapability,
} from "../types/accessOverview"

// The Access page's "Character (deny only)" resource kind (P15-C02-S04). Every fact about WHICH permissions a
// character may be denied comes from the server (`deniable_character_capabilities`); this file holds only the
// words for the two permissions the product has approved copy for, and the pure helpers both grant forms share.

// The select value of the pseudo-kind. It is never sent to the server: the request writes `entity_id` with
// `effect: "deny"` (the server's rule for a character deny).
export const CHARACTER_DENY_KIND = "character_deny"
export const CHARACTER_DENY_KIND_LABEL = "Character (deny only)"

interface DenyCopy {
    label: string
    // What the deny does now, stated from the code and its tests (plan §10.2). DEF-016 is open: the
    // `canon.edit` deny is not widened and its limits are said, not hidden.
    hint: string
    // Said when the denial is removed.
    returns: (name: string) => string
}

const KNOWN: Record<string, DenyCopy> = {
    "campaign.view": {
        label: "Everything about this character",
        hint: "Hides this character from them wherever access to a character is checked, including from owners and anyone with reveal authority. It does not remove access they hold to anything else.",
        returns: (name) => `They may regain access to ${name} from another source, such as a role or relationship.`,
    },
    "canon.edit": {
        label: "Editing this character's profiles",
        hint: "Stops them saving this character's public profile or copying text into it, and hides the player's own profile of this character from them. Revealing and releasing stay available, except that someone who can no longer read text copied from the player's profile can't release a draft that contains it. It does not change what they see of the character or other character editing.",
        returns: (name) => `They may be able to edit ${name}'s profiles again.`,
    },
}

// The server's display name stands in for a code this client has no approved copy for, with no hint.
export function denyLabel(capability: DeniableCharacterCapability): string {
    return KNOWN[capability.code]?.label ?? capability.display_name
}

export function denyHint(code: string): string | null {
    return KNOWN[code]?.hint ?? null
}

export function denyReturns(code: string, characterName: string): string | null {
    return KNOWN[code]?.returns(characterName) ?? null
}

// Whether the form may offer the kind at all: the server lists at least one deniable permission and there is a
// character to choose. Absent or empty means no offer.
export function canOfferCharacterDeny(
    deniable: DeniableCharacterCapability[] | undefined,
    characters: AssignableCharacter[],
): boolean {
    return (deniable?.length ?? 0) > 0 && characters.length > 0
}

// The permissions still offered for one character and one grantee: the server's list, in its order, minus any
// already actively denied (an existing grant of this grantee with an entity target, this character, deny and the
// same code). The server still refuses a duplicate with a 409.
export function availableDenyCapabilities(
    deniable: DeniableCharacterCapability[],
    existingGrants: AccessResourceGrantSummary[],
    characterId: string,
): DeniableCharacterCapability[] {
    if (characterId === "") return deniable
    const taken = new Set(
        existingGrants
            .filter(
                (grant) =>
                    grant.target_type === "entity" &&
                    grant.target_id === characterId &&
                    grant.effect === "deny",
            )
            .map((grant) => grant.capability_code),
    )
    return deniable.filter((capability) => !taken.has(capability.code))
}

// A grant is a character deny only when it is a `deny`, its target is an `entity`, its code is in the server's
// deniable list AND its target is one of the overview's own characters: all three come from one server read
// (D-6). A non-null `target_display_name` alone proves nothing, so it is never the test.
export interface CharacterDenyInfo {
    code: string
    characterName: string
}

export function characterDenyOf(
    grant: AccessResourceGrantSummary,
    deniable: DeniableCharacterCapability[] | undefined,
    characters: AssignableCharacter[],
): CharacterDenyInfo | null {
    if (grant.effect !== "deny" || grant.target_type !== "entity") return null
    if (!(deniable ?? []).some((capability) => capability.code === grant.capability_code)) return null
    const character = characters.find((candidate) => candidate.character_id === grant.target_id)
    if (character === undefined) return null
    return { code: grant.capability_code, characterName: character.display_name }
}

// What the denial is, in the words the card, the removal confirmation and the control's name share.
export function denyDescription(info: CharacterDenyInfo, capabilityDisplayName: string): string {
    if (info.code === "campaign.view") return `everything about ${info.characterName}`
    if (info.code === "canon.edit") return `editing ${info.characterName}'s profiles`
    return `${capabilityDisplayName} on ${info.characterName}`
}
