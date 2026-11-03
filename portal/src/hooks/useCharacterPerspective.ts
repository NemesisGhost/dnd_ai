import { useSyncExternalStore } from "react"
import { resolveSelectedCharacterId } from "../context/characterPerspective"
import {
    selectionOwner,
    useSelectedContextStore,
} from "../navigation/selectedContextStore"
import type { CampaignContext } from "../types/bootstrap"
import type { UseSessionBootstrapResult } from "./useSessionBootstrap"

// The character perspective over the tab's selected-context store (navigation/selectedContextStore.ts).
// The selection belongs to the store, which sits above the campaign-scoped session; this hook is the
// validated view of it for one session: a perspective is read only for the campaign it was chosen
// under, only for the owner (user and browser session) that chose it, and only while the bootstrap
// still authorizes it. It makes no request and never navigates.
export function useCharacterPerspective({ state }: UseSessionBootstrapResult) {
    const store = useSelectedContextStore()
    const selection = useSyncExternalStore(store.subscribe, store.getSnapshot)

    function campaignOf(campaignId: string): CampaignContext | undefined {
        if (state.status !== "authenticated") return undefined
        return state.bootstrap.campaigns.find((candidate) => candidate.campaign_id === campaignId)
    }

    function getSelectedCharacterId(
        campaignId: string,
    ): string | null {
        if (state.status !== "authenticated") {
            return null
        }

        const { bootstrap } = state
        const campaign = campaignOf(campaignId)

        if (campaign === undefined) {
            return null
        }

        const selectionMatchesCurrentSession =
            selection.owner === selectionOwner(bootstrap) &&
            selection.campaignId === campaignId

        const requestedCharacterId = selectionMatchesCurrentSession
            ? selection.characterId
            : undefined

        // A selection the bootstrap no longer authorizes (revoked) is never replaced by the server
        // default: it reads as no perspective until the campaign layout commits that as an explicit
        // choice, so re-authorization alone cannot bring it back (UI_DESIGN §4.5).
        if (
            typeof requestedCharacterId === "string" &&
            !campaign.character_perspectives.some(
                (character) =>
                    character.character_id === requestedCharacterId,
            )
        ) {
            return null
        }

        return resolveSelectedCharacterId(
            campaign,
            requestedCharacterId,
        )
    }

    // Commits `characterId` for the campaign together with the levels the campaign fixes (its world and
    // timeline). The caller is the campaign layout, from an accepted location, or a URL character the
    // route already trusts the server to authorize. Idempotent: committing what is already committed
    // changes nothing and renders nothing.
    function commit(campaignId: string, characterId: string | null): void {
        if (state.status !== "authenticated") {
            return
        }
        const campaign = campaignOf(campaignId)
        if (campaign === undefined) {
            return
        }
        const authorized =
            characterId === null ||
            campaign.character_perspectives.some((character) => character.character_id === characterId)
        if (!authorized) {
            return
        }
        store.commit({
            owner: selectionOwner(state.bootstrap),
            campaignId,
            worldId: campaign.world_id,
            timelineId: campaign.timeline_id,
            characterId,
        })
    }

    // Commits a perspective the user's navigation has already been accepted for (the campaign layout
    // calls this from the accepted location). It starts nothing: no session reload, and no refresh.
    function selectCharacter(
        campaignId: string,
        characterId: string | null,
    ): void {
        commit(campaignId, characterId)
    }

    // Makes the route campaign the selected campaign (the route scope governs, UI_DESIGN §4.8). A
    // retained selection of any other campaign is replaced; the perspective of this same campaign,
    // including an explicit none, is kept as it is, and a campaign with no perspective chosen yet stays
    // uninitialized so the server default can still initialize it.
    function adoptRouteCampaign(campaignId: string): void {
        if (state.status !== "authenticated") {
            return
        }
        const campaign = campaignOf(campaignId)
        if (campaign === undefined) {
            return
        }
        const owner = selectionOwner(state.bootstrap)
        const current = store.getSnapshot()
        const keep = current.owner === owner && current.campaignId === campaignId
        store.commit({
            owner,
            campaignId,
            worldId: campaign.world_id,
            timelineId: campaign.timeline_id,
            characterId: keep ? current.characterId : undefined,
        })
    }

    // Unlike an explicit user selection, this never navigates: it exists
    // to reconcile the visible perspective with a character id a route
    // already trusts the server to authorize (e.g. from a URL), not to
    // perform a new user-driven selection.
    function syncCharacterFromUrl(
        campaignId: string,
        characterId: string,
    ): void {
        commit(campaignId, characterId)
    }

    return {
        getSelectedCharacterId,
        selectCharacter,
        adoptRouteCampaign,
        syncCharacterFromUrl,
    }
}
