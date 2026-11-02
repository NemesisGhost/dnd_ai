import type { ItemView } from "../../types/items"
import { conditionText, hasRecordedState, ownerName, placementOf } from "../../utils/itemState"
import { DetailPanel } from "../DetailPanel"
import { FactGrid } from "../FactGrid"
import type { FactGridItem } from "../FactGrid"

// The item's in-play state, once, outside any command form: where it is, who owns it, what shape
// it is in. It reads the authoring view the page refetches after every command, so it is what the
// server holds now. The state is the campaign timeline's, after the item's latest recorded change
// (whatever world time that change was recorded at), so the panel never claims "now".
export function ItemStateSummary({ view }: { view: ItemView }) {
    if (!hasRecordedState(view)) {
        return (
            <DetailPanel title="In play" headingId="item-in-play-heading">
                <p>
                    Not in play yet: this campaign&apos;s timeline records no place, owner or condition for it.
                </p>
            </DetailPanel>
        )
    }
    const place = placementOf(view)
    const facts: FactGridItem[] = [
        { key: "where", label: "Where", value: place.text },
        { key: "owner", label: "Owner", value: ownerName(view.owner) },
        { key: "quantity", label: "Quantity", value: view.quantity },
        { key: "condition", label: "Condition", value: conditionText(view.condition_percentage) },
    ]
    if (place.kind === "carried") {
        facts.push({ key: "equipped", label: "Equipped", value: view.is_equipped ? "Yes" : "No" })
    }
    if (view.requires_attunement) {
        facts.push({
            key: "attuned",
            label: "Attuned to",
            value: view.attuned_to?.name ?? "Nobody",
        })
    }
    if (view.is_destroyed) {
        facts.push({ key: "destroyed", label: "Destroyed", value: "Yes" })
    }
    return (
        <DetailPanel title="In play" headingId="item-in-play-heading">
            <FactGrid items={facts} />
            <p className="authoring-field__hint">
                This campaign&apos;s timeline, after the item&apos;s latest recorded change.
            </p>
        </DetailPanel>
    )
}
