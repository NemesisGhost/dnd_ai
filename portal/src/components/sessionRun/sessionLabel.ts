import type { CampaignSessionDetail } from "../../types/campaignSession"

// How a session is named wherever it is a heading or a breadcrumb ancestor: its title, else its number.
export function sessionLabel(session: Pick<CampaignSessionDetail, "title" | "session_number">): string {
    return session.title ?? `Session ${session.session_number}`
}
