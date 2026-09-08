import { useState } from "react"
import { resolveSelectedCharacterId } from "../context/characterPerspective"
import type { UseSessionBootstrapResult } from "./useSessionBootstrap"

interface CharacterSelection {
    userId: string
    browserSessionId: string | null
    campaignId: string
    characterId: string | null
}

export function useCharacterPerspective({
    state,
    reload,
}: UseSessionBootstrapResult) {
    const [selection, setSelection] =
        useState<CharacterSelection | null>(null)

    function getSelectedCharacterId(
        campaignId: string,
    ): string | null {
        if (state.status !== "authenticated") {
            return null
        }

        const { bootstrap } = state

        const campaign = bootstrap.campaigns.find(
            (candidate) =>
                candidate.campaign_id === campaignId,
        )

        if (campaign === undefined) {
            return null
        }

        const selectionMatchesCurrentSession =
            selection !== null &&
            selection.userId === bootstrap.user.user_id &&
            selection.browserSessionId ===
            bootstrap.browser_session_id &&
            selection.campaignId === campaignId

        const requestedCharacterId =
            selectionMatchesCurrentSession
                ? selection.characterId
                : undefined

        return resolveSelectedCharacterId(
            campaign,
            requestedCharacterId,
        )
    }

    function selectCharacter(
        campaignId: string,
        characterId: string | null,
    ): void {
        if (state.status !== "authenticated") {
            return
        }

        const { bootstrap } = state

        const campaign = bootstrap.campaigns.find(
            (candidate) =>
                candidate.campaign_id === campaignId,
        )

        if (campaign === undefined) {
            return
        }

        const requestedCharacterIsAuthorized =
            characterId === null ||
            campaign.character_perspectives.some(
                (character) =>
                    character.character_id === characterId,
            )

        if (!requestedCharacterIsAuthorized) {
            return
        }

        setSelection({
            userId: bootstrap.user.user_id,
            browserSessionId: bootstrap.browser_session_id,
            campaignId,
            characterId,
        })

        reload()
    }

    return {
        getSelectedCharacterId,
        selectCharacter,
    }
}