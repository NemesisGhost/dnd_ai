import { Link } from "react-router"
import { characterInventoryPath, partyInventoryPath } from "../api/items"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { CharacterInventoryItem, PartyInventory } from "../types/items"
import "./authoring/authoring.css"

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
    if (items.length === 0) return <p>Nothing carried.</p>
    return (
        <ul className="authoring-choice-list">
            {items.map((item) => (
                <li key={item.item_instance_id}>
                    <Link to={itemPath(campaignId, item.item_instance_id)}>{item.name}</Link>
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
}: {
    campaignId: string
    characterId: string
}) {
    const { state } = useAuthoringResource<CharacterInventoryItem[]>(
        characterInventoryPath(campaignId, characterId),
    )
    if (state.kind !== "ready") return null
    return (
        <section aria-labelledby={`inventory-${characterId}`}>
            <h2 id={`inventory-${characterId}`}>Inventory</h2>
            <ItemList campaignId={campaignId} items={state.data} />
        </section>
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
