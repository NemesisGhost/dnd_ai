import { Link } from "react-router"
import { DetailPanel } from "../components/DetailPanel"
import { FactGrid } from "../components/FactGrid"
import type { ItemDetail } from "../types/world"

interface WorldItemDetailPageProps {
    campaignId: string
    item: ItemDetail
}

function describeBoolean(value: boolean | null): string {
    if (value === null) {
        return "Not recorded"
    }
    return value ? "Yes" : "No"
}

// Item detail. item_definition_id is never rendered — the response has no
// authorized display label for it (UI_STYLE_GUIDE.md §10.2).
export function WorldItemDetailPage({
    campaignId,
    item,
}: WorldItemDetailPageProps) {
    const hasCharges =
        item.charges_current !== null || item.charges_maximum !== null

    return (
        <section aria-labelledby="world-item-heading">
            <p>
                <Link to={`/app/${encodeURIComponent(campaignId)}/world`}>
                    Back to World
                </Link>
            </p>

            <p className="world-detail__eyebrow">Item</p>
            <h1 id="world-item-heading">{item.name}</h1>

            {item.summary !== null && (
                <p className="world-detail__summary">{item.summary}</p>
            )}

            <div className="world-detail__panel-grid">
                <DetailPanel title="Overview">
                    <FactGrid
                        items={[
                            {
                                key: "origin",
                                label: "Origin notes",
                                value: item.origin_notes ?? "Not recorded",
                            },
                        ]}
                    />
                </DetailPanel>

                <DetailPanel title="Current State">
                    <FactGrid
                        items={[
                            {
                                key: "quantity",
                                label: "Quantity",
                                value: item.quantity ?? "Not recorded",
                            },
                            {
                                key: "condition",
                                label: "Condition",
                                value:
                                    item.condition_percentage !== null
                                        ? `${item.condition_percentage}%`
                                        : "Not recorded",
                            },
                            {
                                key: "charges",
                                label: "Charges",
                                value: hasCharges
                                    ? `${item.charges_current ?? "?"} / ${item.charges_maximum ?? "?"}`
                                    : "Not recorded",
                            },
                            {
                                key: "equipped",
                                label: "Equipped",
                                value: describeBoolean(item.is_equipped),
                            },
                            {
                                key: "destroyed",
                                label: "Destroyed",
                                value: describeBoolean(item.is_destroyed),
                            },
                        ]}
                    />
                </DetailPanel>
            </div>
        </section>
    )
}
