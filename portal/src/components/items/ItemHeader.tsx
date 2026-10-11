import { Link } from "react-router"
import type { RefObject } from "react"
import type { ItemView } from "../../types/items"
import { rarityText } from "../../utils/itemState"
import { LifecycleBadge } from "../authoring/feedback"
import type { ItemGuidance } from "./itemStages"

export type ItemOrigin = "items" | "world"

interface Props {
    view: ItemView
    origin: ItemOrigin
    // Where the person came from: the item inventory (with the query it was left on) or the World
    // browser (with its category, search and page).
    backHref: string
    headingRef: RefObject<HTMLHeadingElement | null>
    guidance: ItemGuidance | null
    // Where the guidance leads; null when it has no destination.
    guidanceHref: string | null
    linkState?: object
}

// The always-visible top of the item page: where it is, what the item is, and the record's real
// status. Everything here is information or navigation; no lifecycle or operation lives in it.
export function ItemHeader({ view, origin, backHref, headingRef, guidance, guidanceHref, linkState }: Props) {
    return (
        <header className="item-header">
            {origin === "items" ? (
                <nav aria-label="Breadcrumb" className="authoring-page__breadcrumb">
                    <ol className="session-run__breadcrumb">
                        <li>
                            <Link to={backHref}>Item inventory</Link>
                        </li>
                        <li aria-current="page">{view.name}</li>
                    </ol>
                </nav>
            ) : (
                <p>
                    <Link to={backHref}>Back to World</Link>
                </p>
            )}
            <p className="world-detail__eyebrow">Item</p>
            <div className="item-header__headline">
                <h1 id="item-workspace-heading" ref={headingRef} tabIndex={-1} className="item-header__title">
                    {view.name}
                </h1>
                <span className="item-header__status" role="group" aria-label="Record status">
                    <LifecycleBadge status={view.canon_status} />
                    {view.lifecycle_status === "archived" ? <LifecycleBadge status="archived" /> : null}
                    {view.is_destroyed ? <span className="item-header__destroyed">Destroyed</span> : null}
                </span>
            </div>
            {view.summary !== null ? <p className="world-detail__summary">{view.summary}</p> : null}
            <div className="item-header__meta">
                <span>
                    Kind: {view.definition_name} ({view.category_label}, {rarityText(view.rarity)})
                </span>
                {guidance !== null ? (
                    <span className="item-header__next">
                        Next:{" "}
                        {guidanceHref !== null ? (
                            <Link to={guidanceHref} state={linkState}>
                                {guidance.text} ›
                            </Link>
                        ) : (
                            guidance.text
                        )}
                    </span>
                ) : null}
            </div>
        </header>
    )
}
