import { Link, useLocation } from "react-router"
import { useCampaignCapability } from "../../hooks/useCampaignCapability"
import { continuedListState, continuedState } from "../../navigation/breadcrumbModel"

// The Characters area's one create offer: New PC, opening player-character creation directly (NPCs are
// created from the World's People category; the chooser is decision PD-8, still pending). It uses the same
// rule as the World's creation links: canon.edit from the bootstrap decides what to show, the server
// re-checks every request, and it is independent of any selected or viewed character. The page it is
// shown on rides along as the task (the browser with its filters, or the character's record), which the
// create page validates before Cancel and the breadcrumb use it. It is rendered by the Characters header
// (`/characters/all`) and by the character record, so the entry point that lands on the record keeps it.
export function CharactersCreateAction({ campaignId }: { campaignId: string }) {
    const canCreate = useCampaignCapability(campaignId, "canon.edit")
    const { pathname, search, state } = useLocation()
    // A record is left on the section it shows, so Cancel returns to that section.
    const section = new URLSearchParams(search).get("section") ?? undefined
    const task = continuedListState(pathname, state, search) ?? continuedState(pathname, state, section) ?? undefined
    if (!canCreate) return null
    return (
        <nav aria-label="Create character" className="authoring-page__actions-row">
            <Link
                to={`/app/${encodeURIComponent(campaignId)}/characters/pc/new`}
                state={task}
                className="authoring-button"
            >
                New PC
            </Link>
        </nav>
    )
}
