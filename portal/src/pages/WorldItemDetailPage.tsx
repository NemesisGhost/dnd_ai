import { useWorldBackPath } from "../hooks/useWorldBackPath"
import { Link } from "react-router"
import { DetailPanel } from "../components/DetailPanel"
import { FactGrid } from "../components/FactGrid"
import type { FactGridItem } from "../components/FactGrid"
import type { ItemDetail } from "../types/world"
import { conditionText } from "../utils/itemState"

interface WorldItemDetailPageProps {
    campaignId: string
    item: ItemDetail
}

// Item detail. item_definition_id is never rendered — the response has no
// authorized display label for it (UI_STYLE_GUIDE.md §10.2).
export function WorldItemDetailPage({
    campaignId,
    item,
}: WorldItemDetailPageProps) {
    const worldBackPath = useWorldBackPath(campaignId)
    const hasCharges =
        item.charges_current !== null || item.charges_maximum !== null
    // An item nothing has happened to has no state row, so every state field is empty. That is
    // said once, rather than as a "Not recorded" beside each field.
    const inPlay = item.quantity !== null
    const state: FactGridItem[] = [
        { key: "quantity", label: "Quantity", value: item.quantity },
        { key: "condition", label: "Condition", value: conditionText(item.condition_percentage) },
        // No command maintains charges yet, so they appear only when something recorded them.
        ...(hasCharges
            ? [
                  {
                      key: "charges",
                      label: "Charges",
                      value: `${item.charges_current ?? "?"} / ${item.charges_maximum ?? "?"}`,
                  },
              ]
            : []),
        ...(item.is_equipped !== null
            ? [{ key: "equipped", label: "Equipped", value: item.is_equipped ? "Yes" : "No" }]
            : []),
        ...(item.is_destroyed === true ? [{ key: "destroyed", label: "Destroyed", value: "Yes" }] : []),
    ]

    return (
        <section aria-labelledby="world-item-heading">
            <p>
                <Link to={worldBackPath}>
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

                <DetailPanel title="In play">
                    {inPlay ? (
                        <FactGrid items={state} />
                    ) : (
                        <p>
                            Not in play yet: this campaign&apos;s timeline records no state for it.
                        </p>
                    )}
                </DetailPanel>
            </div>
        </section>
    )
}
