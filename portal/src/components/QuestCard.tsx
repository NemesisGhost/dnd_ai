import type { CampaignQuestListItem } from "../types/quest"
import { humanizeCode } from "../utils/humanize"
import { statusDetail } from "../utils/locationForm"
import { EntityCard } from "./EntityCard"

interface QuestCardProps {
    campaignId: string
    quest: CampaignQuestListItem
}

// The list contract supplies only a quest name and status — this card
// never invents a description, objective count, reward, participant, or
// location (UI_STYLE_GUIDE.md §12.1).
export function QuestCard({ campaignId, quest }: QuestCardProps) {
    const untracked = quest.tracked === false
    const progress =
        quest.status_code !== null
            ? humanizeCode(quest.status_code)
            : untracked
              ? "Not started"
              : "No status recorded"
    // An editor sees a definition's own lifecycle when it is not simply
    // published, so a draft or archived quest is never mistaken for a live one.
    const lifecycle =
        quest.canon_status && quest.lifecycle_status
            ? statusDetail(quest.canon_status, quest.lifecycle_status)
            : null
    const status =
        lifecycle !== null && lifecycle !== "Canon" ? `${lifecycle} · ${progress}` : progress
    const base = `/app/${encodeURIComponent(campaignId)}/quests/${encodeURIComponent(quest.quest_id)}`

    return (
        <EntityCard
            title={quest.name}
            status={status}
            // A definition no party has started has no player-facing detail, so
            // its card opens the editor (the list only includes it for editors).
            to={untracked ? `${base}/edit` : base}
            linkLabel={`${quest.name}, ${status}`}
        />
    )
}
