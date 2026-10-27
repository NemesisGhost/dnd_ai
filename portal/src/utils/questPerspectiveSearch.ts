/** The query suffix that carries a quest's character and party perspective. */
export function questPerspectiveSearch(
    characterId: string | null,
    partyId: string | null,
): string {
    if (characterId === null || partyId === null) {
        return ""
    }
    const parameters = new URLSearchParams({
        character_id: characterId,
        party_id: partyId,
    })
    return `?${parameters.toString()}`
}
