import { useParams } from "react-router"
import { CharacterBreadcrumb } from "../components/characters/CharacterBreadcrumb"
import { CharacterInventoryPanel } from "../components/InventoryPanels"
import { ArrivalHeadingFocus } from "../navigation/ArrivalHeadingFocus"
import PlaceholderPage from "./PlaceholderPage"

// One character's inventory by address: /app/:campaignId/characters/:characterId/inventory. It is
// the entry for a reader whose only access to the character is `character.view_inventory` (for
// example a direct grant to a player): the character read itself is refused to them, so this page
// never makes it and has no name, sections or sheet to show. The inventory endpoint authorizes
// every request on its own and decides everything here: rows when it answers, the plain
// "not available" notice (denied or revoked) when it does not, a retry when it fails. It sends no
// other request, selects no perspective and offers no control. Its breadcrumb is the task's trail
// without the record: it is not told what else of the character the reader may open, so it offers
// no link to it (and no section row), and the page names itself "Inventory".
export function CharacterInventoryRoutePage() {
    const { campaignId, characterId } = useParams<{ campaignId: string; characterId: string }>()
    if (campaignId === undefined || characterId === undefined) {
        return (
            <PlaceholderPage
                title="Inventory unavailable"
                description="The requested inventory is not available."
            />
        )
    }
    return (
        <div className="character-sheet-route">
            <CharacterBreadcrumb campaignId={campaignId} characterId={characterId} recordUnknown />
            <h1>Inventory</h1>
            <ArrivalHeadingFocus />
            <CharacterInventoryPanel key={`${campaignId}:${characterId}`} embedded campaignId={campaignId} characterId={characterId} />
        </div>
    )
}
