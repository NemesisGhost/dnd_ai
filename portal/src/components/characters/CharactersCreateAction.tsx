import { Link, useLocation } from "react-router"
import { useCampaignCapability } from "../../hooks/useCampaignCapability"

// The Characters area's one create offer: New PC, opening player-character creation directly (NPCs are
// created from the World's People category; the chooser is decision PD-8, still pending). It uses the same
// rule as the World's creation links: canon.edit from the bootstrap decides what to show, the server
// re-checks every request, and it is independent of any selected or viewed character. The page it is
// shown on rides along as `charactersReturn`, which the create pages validate (a Characters address of
// this campaign) before Cancel and the breadcrumb use it. It is rendered by the Characters header
// (`/characters/all`) and by the character record, so the entry point that lands on the record keeps it.
export function CharactersCreateAction({ campaignId }: { campaignId: string }) {
    const canCreate = useCampaignCapability(campaignId, "canon.edit")
    const { pathname, search } = useLocation()
    if (!canCreate) return null
    return (
        <nav aria-label="Create character" className="authoring-page__actions-row">
            <Link
                to={`/app/${encodeURIComponent(campaignId)}/characters/pc/new`}
                state={{ charactersReturn: `${pathname}${search}` }}
                className="authoring-button"
            >
                New PC
            </Link>
        </nav>
    )
}
