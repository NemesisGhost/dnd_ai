import { useCallback } from "react"
import { usePerspective } from "../context/CharacterPerspectiveContext"

// Campaign selection side effects shared by the sidebar's campaign list.
// Switching to a different campaign clears that target campaign's selected
// character perspective (UI_DESIGN §4.5: character perspective never
// carries across campaigns); re-selecting the active campaign changes
// nothing. The caller's Link performs the navigation to the target's
// Campaign Home.
export function useSelectCampaign(
    activeCampaignId: string | undefined,
): (campaignId: string) => void {
    const { selectCharacter } = usePerspective()

    return useCallback(
        (campaignId: string) => {
            if (campaignId === activeCampaignId) {
                return
            }
            selectCharacter(campaignId, null)
        },
        [activeCampaignId, selectCharacter],
    )
}
