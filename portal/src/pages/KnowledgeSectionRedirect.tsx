import { Navigate, useLocation, useParams } from "react-router"

// The old "Edit" (/knowledge/:id/edit) and "Who knows this" (/knowledge/:id/audience) addresses
// now open the unified claim page at the matching section. The query string is carried over
// unchanged, so the campaign's character and party perspective survive the redirect.
export function KnowledgeSectionRedirect({ fragment }: { fragment: "claim" | "who-knows" }) {
    const { campaignId = "", knowledgeItemId = "" } = useParams()
    const { search } = useLocation()
    return (
        <Navigate
            replace
            to={{
                pathname: `/app/${encodeURIComponent(campaignId)}/knowledge/${encodeURIComponent(knowledgeItemId)}`,
                search,
                hash: `#${fragment}`,
            }}
        />
    )
}
