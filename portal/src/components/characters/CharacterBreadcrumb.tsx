import { TaskBreadcrumb } from "../navigation/TaskBreadcrumb"
import { useBreadcrumbLabelReader } from "../../navigation/BreadcrumbLabelContext"

// The one breadcrumb of a character's pages (docs/UI_DESIGN.md §5.5): the shared task trail with the
// character as the current page, on `/characters/:id` and `/world/character/:id` alike. The name is the
// one a page registered from an authorized character read under the authority still in force; without
// it the noun "Character" stands, so nothing here reads the character.
//
// `recordUnknown` is for the page of a reader who was never told what else of the character they may
// open (inventory only): the ancestor that would link to the record is left out rather than offered as
// if they could open it, and the page names itself.
export function CharacterBreadcrumb({
    campaignId,
    characterId,
    recordUnknown = false,
}: {
    campaignId: string
    characterId: string
    recordUnknown?: boolean
}) {
    const labelFor = useBreadcrumbLabelReader()
    if (recordUnknown) return <TaskBreadcrumb omit={["characters.detail"]} />
    return <TaskBreadcrumb current={labelFor("characters.detail", { campaignId, characterId }) ?? "Character"} />
}
