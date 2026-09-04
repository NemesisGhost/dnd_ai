import { createContext, useContext } from "react"

interface CharacterPerspectiveContextValue {
    getSelectedCharacterId: (
        campaignId: string,
    ) => string | null

    selectCharacter: (
        campaignId: string,
        characterId: string,
    ) => void
}

export const CharacterPerspectiveContext =
    createContext<
        CharacterPerspectiveContextValue | undefined
    >(undefined)

export function usePerspective():
    CharacterPerspectiveContextValue {
    const perspective = useContext(
        CharacterPerspectiveContext,
    )

    if (perspective === undefined) {
        throw new Error(
            "usePerspective must be used inside SessionProvider",
        )
    }

    return perspective
}