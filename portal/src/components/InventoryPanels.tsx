import { Link } from "react-router"
import { characterInventoryPath, partyInventoryPath } from "../api/items"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useWorldReturnState } from "../hooks/useWorldBackPath"
import type { CharacterInventoryItem, PartyInventory } from "../types/items"
import "./authoring/authoring.css"
import { ReadClosedNotice, ReadFailedNotice } from "./authoring/ReadState"
import { PanelFrame } from "./DetailPanel"

const itemPath = (campaignId: string, itemId: string): string =>
    `/app/${encodeURIComponent(campaignId)}/world/item/${encodeURIComponent(itemId)}`

interface Row {
    item_instance_id: string
    name: string
    display_name: string
    quantity: number
    // Absent (not null) on the inventory-only read (CP-6), which does not carry condition.
    condition_percentage?: number | null
    is_equipped: boolean
    is_destroyed: boolean
    is_attuned?: boolean
}

function ItemList({ campaignId, items }: { campaignId: string; items: Row[] }) {
    // An item opened from here keeps the World browser state this page was opened with.
    const returnState = useWorldReturnState()
    if (items.length === 0) return <p>Nothing carried.</p>
    return (
        <ul className="record-list">
            {items.map((item) => (
                <li key={item.item_instance_id}>
                    <Link to={itemPath(campaignId, item.item_instance_id)} state={returnState}>
                        {item.name}
                    </Link>
                    {item.name !== item.display_name ? ` (${item.display_name})` : ""}
                    {item.quantity !== 1 ? `, ×${item.quantity}` : ""}
                    {item.condition_percentage !== null && item.condition_percentage !== undefined ? `, ${item.condition_percentage}% condition` : ""}
                    {item.is_equipped ? ", equipped" : ""}
                    {item.is_attuned === true ? ", attuned" : ""}
                    {item.is_destroyed ? ", destroyed" : ""}
                </li>
            ))}
        </ul>
    )
}

// What a character carries, from the inventory read the server allows this caller (the full
// character view). The read can end four ways and each reads differently:
//   loading      embedded: a status line. On a page that is complete without it: nothing yet.
//   empty        "Nothing carried."
//   refused      403/404. Embedded in a staged section: said plainly. Otherwise absent, because the
//                server only gives the inventory to the full view and everyone else is not meant
//                to see a panel for it. Anything loaded earlier is dropped.
//   failed       a network or server failure: said so, with a retry that only reads again.
export function CharacterInventoryPanel({
    campaignId,
    characterId,
    embedded,
}: {
    campaignId: string
    characterId: string
    // A staged section already supplies the surface and the heading: render the content only.
    embedded?: boolean
}) {
    const { state, refetch } = useAuthoringResource<CharacterInventoryItem[]>(
        characterInventoryPath(campaignId, characterId),
    )
    if (state.kind !== "ready") {
        if (state.kind === "loading") {
            return embedded === true ? <p role="status">Loading inventory…</p> : null
        }
        if (state.kind === "denied" || state.kind === "unavailable") {
            return embedded === true ? <ReadClosedNotice what="inventory" denied={state.kind === "denied"} /> : null
        }
        return <ReadFailedNotice what="inventory" onRetry={() => void refetch()} />
    }
    return (
        <PanelFrame embedded={embedded} title="Inventory" headingId={`inventory-${characterId}`}>
            <ItemList campaignId={campaignId} items={state.data} />
        </PanelFrame>
    )
}

// The items each current member of a party carries (editors only; the read is refused to anyone
// else and the panel is then absent). A failed read says so and can be retried.
export function PartyInventoryPanel({
    campaignId,
    partyId,
}: {
    campaignId: string
    partyId: string
}) {
    const { state, refetch } = useAuthoringResource<PartyInventory>(partyInventoryPath(campaignId, partyId))
    if (state.kind !== "ready") {
        return state.kind === "error" ? (
            <ReadFailedNotice what="party inventory" onRetry={() => void refetch()} />
        ) : null
    }
    return (
        <section aria-labelledby="party-inventory-heading">
            <h2 id="party-inventory-heading">Party inventory</h2>
            {state.data.members.length === 0 ? <p>No current members.</p> : null}
            {state.data.members.map((member) => (
                <div key={member.character_id}>
                    <h3>{member.character_name}</h3>
                    <ItemList campaignId={campaignId} items={member.items} />
                </div>
            ))}
        </section>
    )
}
