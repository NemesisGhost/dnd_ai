import { Navigate, useLocation, useParams } from "react-router"

// The old "Edit" (/knowledge/:id/edit) and "Who knows this" (/knowledge/:id/audience) addresses
// now open the unified claim page at the matching section. Every query parameter is carried over,
// so the campaign's character and party perspective survive the redirect.
export function KnowledgeSectionRedirect({ section }: { section: "claim" | "who-knows" }) {
    const { campaignId = "", knowledgeItemId = "" } = useParams()
    const { search } = useLocation()
    const params = new URLSearchParams(search)
    params.set("section", section)
    return (
        <Navigate
            replace
            to={{
                pathname: `/app/${encodeURIComponent(campaignId)}/knowledge/${encodeURIComponent(knowledgeItemId)}`,
                search: `?${params.toString()}`,
            }}
        />
    )
}
