import { useParams } from "react-router"
import { ItemWorkspace } from "../components/items/ItemWorkspace"
import { useCampaignCapability } from "../hooks/useCampaignCapability"

// /app/:campaignId/items/:itemId: an item opened from the item inventory. Editors only; anyone
// else gets the permission message and no item request is made (the World page shows them the
// reader).
export function ItemWorkspacePage() {
    const { campaignId = "", itemId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    if (!canEdit) {
        return (
            <section className="authoring-page" aria-labelledby="items-heading">
                <h1 id="items-heading">Item inventory</h1>
                <p role="alert">You do not have permission to manage items.</p>
            </section>
        )
    }
    return <ItemWorkspace key={itemId} campaignId={campaignId} itemId={itemId} origin="items" />
}
