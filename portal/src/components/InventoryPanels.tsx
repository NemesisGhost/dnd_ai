import { Link } from "react-router"
import { characterInventoryPath, partyInventoryPath } from "../api/items"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useWorldReturnState } from "../hooks/useWorldBackPath"
import type { CharacterInventoryItem, PartyInventory } from "../types/items"
import "./authoring/authoring.css"
import { PanelFrame } from "./DetailPanel"

const itemPath = (campaignId: string, itemId: string): string =>
    `/app/${encodeURIComponent(campaignId)}/world/item/${encodeURIComponent(itemId)}`

interface Row {
    item_instance_id: string
    name: string
    display_name: string
    quantity: number
    condition_percentage: number | null
    is_equipped: boolean
    is_destroyed: boolean
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
                    {item.condition_percentage !== null ? `, ${item.condition_percentage}% condition` : ""}
                    {item.is_equipped ? ", equipped" : ""}
                    {item.is_destroyed ? ", destroyed" : ""}
                </li>
            ))}
        </ul>
    )
}

// What a character carries, from the inventory read the server allows this caller (the full
// character view). Shows nothing when that read is refused, so no player sees a broken panel.
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
    const { state } = useAuthoringResource<CharacterInventoryItem[]>(
        characterInventoryPath(campaignId, characterId),
    )
    if (state.kind !== "ready") {
        // Inside a staged section a missing body would read as "nothing carried", so say why.
        if (embedded !== true) return null
        return state.kind === "loading" ? (
            <p role="status">Loading inventory…</p>
        ) : (
            <p role="alert">The inventory could not be loaded.</p>
        )
    }
    return (
        <PanelFrame embedded={embedded} title="Inventory" headingId={`inventory-${characterId}`}>
            <ItemList campaignId={campaignId} items={state.data} />
        </PanelFrame>
    )
}

// The items each current member of a party carries (editors only; the read is refused to anyone
// else and the panel then shows nothing).
export function PartyInventoryPanel({
    campaignId,
    partyId,
}: {
    campaignId: string
    partyId: string
}) {
    const { state } = useAuthoringResource<PartyInventory>(partyInventoryPath(campaignId, partyId))
    if (state.kind !== "ready") return null
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
