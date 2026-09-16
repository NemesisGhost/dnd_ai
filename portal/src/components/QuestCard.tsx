import type { CampaignQuestListItem } from "../types/quest"
import { humanizeCode } from "../utils/humanize"
import { EntityCard } from "./EntityCard"

interface QuestCardProps {
    campaignId: string
    quest: CampaignQuestListItem
}

// The list contract supplies only a quest name and status — this card
// never invents a description, objective count, reward, participant, or
// location (UI_STYLE_GUIDE.md §12.1).
export function QuestCard({ campaignId, quest }: QuestCardProps) {
    const status =
        quest.status_code !== null
            ? humanizeCode(quest.status_code)
            : "No status recorded"

    return (
        <EntityCard
            title={quest.name}
            status={status}
            to={`/app/${encodeURIComponent(campaignId)}/quests/${encodeURIComponent(quest.quest_id)}`}
            linkLabel={`${quest.name}, ${status}`}
        />
    )
}
