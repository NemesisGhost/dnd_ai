import type { CharacterKind } from "../types/character"

// The label for a character's kind, in text (never colour alone). A bare character row is
// neither an NPC nor a player character, and is called what it is.
export function characterKindLabel(kind: CharacterKind): string {
    switch (kind) {
        case "npc":
            return "NPC"
        case "player_character":
            return "Player character"
        default:
            return "Character"
    }
}

// The kind from a World search card's entity type code.
export function characterKindOfTypeCode(entityTypeCode: string): CharacterKind {
    return entityTypeCode === "npc" || entityTypeCode === "player_character"
        ? entityTypeCode
        : "character"
}
