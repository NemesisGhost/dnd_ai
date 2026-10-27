import type { CharacterKind } from "../../types/character"

export const ROLE_LABEL: Readonly<Record<string, string>> = {
    player_character: "Player character",
    npc: "NPC",
    guest: "Guest",
}

// The compatible roles for a character, from the server's catalog (never from this file): the
// matching role first, then Guest. A kind the catalog doesn't list has none.
export function rolesForKind(
    catalog: Readonly<Record<string, readonly string[]>> | null | undefined,
    kind: CharacterKind | null,
): readonly string[] {
    return kind === null ? [] : (catalog?.[kind] ?? [])
}

// The role to submit: Guest only when the user chose it and it is still compatible, otherwise
// the character's matching role. Because it is derived, changing the character can never leave
// an incompatible role selected.
export function effectiveRole(roles: readonly string[], wantsGuest: boolean): string {
    return wantsGuest && roles.includes("guest") ? "guest" : (roles[0] ?? "")
}
