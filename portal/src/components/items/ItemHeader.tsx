import { Link } from "react-router"
import type { RefObject } from "react"
import type { ItemView } from "../../types/items"
import { rarityText } from "../../utils/itemState"
import { TaskBreadcrumb } from "../navigation/TaskBreadcrumb"
import { RecordHeader, RecordStatus } from "../records/RecordHeader"
import type { ItemGuidance } from "./itemStages"

export type ItemOrigin = "items" | "world"

interface Props {
    view: ItemView
    origin: ItemOrigin
    // Where the person came from: the item inventory (the shared task breadcrumb, which carries the query
    // it was left on) or the World browser (with its category, search and page): `backHref` is the World
    // browser's, and is unused for the inventory.
    backHref: string
    headingRef: RefObject<HTMLHeadingElement | null>
    guidance: ItemGuidance | null
    // Where the guidance leads; null when it has no destination.
    guidanceHref: string | null
    linkState?: object
}

// The always-visible top of the item page, in the frame the World record shares (`RecordHeader`).
// What is the item's own: the task breadcrumb when it was opened from the inventory, its kind, and
// Destroyed beside the record's status.
export function ItemHeader({ view, origin, backHref, headingRef, guidance, guidanceHref, linkState }: Props) {
    return (
        <RecordHeader
            back={
                origin === "items" ? (
                    <TaskBreadcrumb current={view.name} />
                ) : (
                    <p>
                        <Link to={backHref}>Back to World</Link>
                    </p>
                )
            }
            eyebrow="Item"
            name={view.name}
            headingId="item-workspace-heading"
            headingRef={headingRef}
            status={
                <RecordStatus
                    status={view}
                    extra={view.is_destroyed ? <span className="item-header__destroyed">Destroyed</span> : null}
                />
            }
            summary={view.summary}
            meta={
                <span>
                    Kind: {view.definition_name} ({view.category_label}, {rarityText(view.rarity)})
                </span>
            }
            next={guidance === null ? null : { text: guidance.text, href: guidanceHref, state: linkState }}
        />
    )
}
