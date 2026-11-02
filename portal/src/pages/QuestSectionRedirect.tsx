import { Navigate, useLocation, useParams } from "react-router"

// The old "Edit quest" (/quests/:id/edit) and "Run quest" (/quests/:id/progress) addresses now open
// the quest workspace at the matching section. History is replaced, and the whole query string and
// the router state (where the quest was opened from) are carried over, so the campaign's character
// and party perspective and the way back to the Review queue survive the redirect.
export function QuestSectionRedirect({ section }: { section: "details" | "progress" }) {
    const { campaignId = "", questId = "" } = useParams()
    const { search, state } = useLocation()
    const params = new URLSearchParams(search)
    params.set("section", section)
    return (
        <Navigate
            replace
            state={state}
            to={{
                pathname: `/app/${encodeURIComponent(campaignId)}/quests/${encodeURIComponent(questId)}`,
                search: `?${params.toString()}`,
            }}
        />
    )
}
