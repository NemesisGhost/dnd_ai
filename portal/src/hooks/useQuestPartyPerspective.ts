import { useCallback } from "react"
import { useSearchParams } from "react-router"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { useSession } from "../context/SessionContext"
import type { AuthorizedParty } from "../types/bootstrap"
import { resolveAuthorizedParties } from "../utils/authorizedParties"

export interface QuestPartyPerspective {
    characterId: string | null
    /** The party perspective to send alongside `characterId`, or `null`
     * for campaign-wide quests only. Always one of `parties`. */
    partyId: string | null
    parties: AuthorizedParty[]
    selectParty: (partyId: string | null) => void
}

/**
 * The (character, party) perspective the quest list and detail routes send.
 * The server only honors a party perspective when given *both*
 * `character_id` and `party_id` (`resolve_party_perspective`), so the party
 * has to be chosen here:
 *
 * - zero authorized parties: no party — campaign-wide quests only;
 * - exactly one: that party, the unambiguous choice;
 * - several: only the party the user explicitly picked — never guessed.
 *
 * An explicit pick is carried in the URL as a `character_id` + `party_id`
 * pair (so the list's quest links, a refresh, and a bookmark keep it). It is
 * honored only while it still belongs to the *currently selected*
 * character and is still among that character's authorized parties: a
 * character switch, or a party that is no longer offered, falls back to the
 * derivation above rather than sending a party that belongs to another
 * perspective.
 */
export function useQuestPartyPerspective(campaignId: string): QuestPartyPerspective {
    const { getSelectedCharacterId } = usePerspective()
    const characterId = getSelectedCharacterId(campaignId)
    const { state: sessionState } = useSession()
    const parties = resolveAuthorizedParties(sessionState, campaignId, characterId)
    const [searchParams, setSearchParams] = useSearchParams()

    const urlCharacterId = searchParams.get("character_id")
    const urlPartyId = searchParams.get("party_id")
    const urlPartyIsCurrent =
        characterId !== null &&
        urlCharacterId === characterId &&
        parties.some((party) => party.party_id === urlPartyId)

    const partyId = urlPartyIsCurrent
        ? urlPartyId
        : parties.length === 1
          ? parties[0].party_id
          : null

    const selectParty = useCallback(
        (nextPartyId: string | null) => {
            setSearchParams(
                (current) => {
                    const next = new URLSearchParams(current)
                    if (nextPartyId === null || characterId === null) {
                        next.delete("character_id")
                        next.delete("party_id")
                    } else {
                        next.set("character_id", characterId)
                        next.set("party_id", nextPartyId)
                    }
                    return next
                },
                { replace: true },
            )
        },
        [characterId, setSearchParams],
    )

    return { characterId, partyId, parties, selectParty }
}

/** The `?character_id=…&party_id=…` suffix that carries a party perspective
 * from the quest list into a quest detail link (empty without a party). */
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
