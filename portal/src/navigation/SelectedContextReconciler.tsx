import { useLayoutEffect } from "react"
import { useMatch } from "react-router"
import { useSession } from "../context/SessionContext"
import { useWorkspaceHierarchy } from "../context/WorkspaceHierarchyContext"
import { selectionOwner, useSelectedContextStore } from "./selectedContextStore"

// Keeps the retained selection honest outside the campaign layout (which owns it on a campaign route):
//
//   - Sign-out, or a different user or browser session, drops the selection.
//   - A selected campaign the authenticated session no longer lists is cleared with everything that
//     depends on it. A loading, refreshing or failed session never clears anything: only an answer
//     that omits the campaign does.
//   - A perspective that is no longer authorized is cleared to an explicit "none", so neither the
//     server default nor a later re-authorization brings it back. On the route campaign's own pages the
//     campaign layout does this (with its notice), so it is left alone there.
//   - A world route the server confirmed commits its world (and timeline) and keeps a retained campaign
//     only when that campaign belongs to it; anything else is cleared (UI_DESIGN §4.8). An unconfirmed
//     world route commits nothing.
//
// It reads the store fresh in each effect, so it never acts on a snapshot an earlier effect replaced.
export function SelectedContextReconciler() {
    const { state } = useSession()
    const store = useSelectedContextStore()
    const campaignMatch = useMatch("/app/:campaignId/*")
    const { routeNamesWorld, routeNamesTimeline, activeWorldId, activeTimelineId } = useWorkspaceHierarchy()
    const routeCampaignId = campaignMatch?.params.campaignId ?? null
    const bootstrap = state.status === "authenticated" ? state.bootstrap : null
    const unauthenticated = state.status === "unauthenticated"

    useLayoutEffect(() => {
        if (unauthenticated) {
            store.reset()
            return
        }
        if (bootstrap === null) return
        const owner = selectionOwner(bootstrap)
        let current = store.getSnapshot()
        if (current.owner !== null && current.owner !== owner) {
            store.reset()
            current = store.getSnapshot()
        }
        if (current.owner !== owner) return

        const campaign =
            current.campaignId === null
                ? null
                : (bootstrap.campaigns.find((candidate) => candidate.campaign_id === current.campaignId) ?? null)
        if (current.campaignId !== null && campaign === null) {
            store.commit({ owner, campaignId: null, worldId: null, timelineId: null, characterId: undefined })
            return
        }
        if (
            campaign !== null &&
            typeof current.characterId === "string" &&
            current.campaignId !== routeCampaignId &&
            !campaign.character_perspectives.some((character) => character.character_id === current.characterId)
        ) {
            store.commit({ ...current, characterId: null })
            return
        }

        if (!routeNamesWorld || activeWorldId === null || (routeNamesTimeline && activeTimelineId === null)) return
        const keeps =
            campaign !== null &&
            campaign.world_id === activeWorldId &&
            (activeTimelineId === null || campaign.timeline_id === activeTimelineId)
        store.commit({
            owner,
            campaignId: keeps ? current.campaignId : null,
            worldId: activeWorldId,
            timelineId: activeTimelineId,
            characterId: keeps ? current.characterId : undefined,
        })
    }, [
        activeTimelineId,
        activeWorldId,
        bootstrap,
        routeCampaignId,
        routeNamesTimeline,
        routeNamesWorld,
        store,
        unauthenticated,
    ])

    return null
}
