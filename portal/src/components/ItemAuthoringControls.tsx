import { useState } from "react"
import { itemAuthoringPath } from "../api/items"
import { AuthoringEditLink } from "./AuthoringEditLink"
import { EntityLifecyclePanel } from "./EntityLifecyclePanel"
import { ItemOperationsPanel } from "./ItemOperationsPanel"

interface Props {
    campaignId: string
    itemId: string
}

// Editor-only controls under an item's World detail: an Edit link, the lifecycle panel and the
// operations panel. Each mounts nothing for a caller without `canon.edit`, so a player sends no
// request. A lifecycle change refreshes the edit link (and the panel remounts on the new state).
export function ItemAuthoringControls({ campaignId, itemId }: Props) {
    const [changes, setChanges] = useState(0)
    return (
        <>
            <AuthoringEditLink
                campaignId={campaignId}
                noun="item"
                viewPath={itemAuthoringPath(campaignId, itemId)}
                editPath={`/app/${encodeURIComponent(campaignId)}/items/${encodeURIComponent(itemId)}/edit`}
                detail={changes}
            />
            <ItemOperationsPanel key={changes} campaignId={campaignId} itemId={itemId} />
            <EntityLifecyclePanel
                campaignId={campaignId}
                entityId={itemId}
                category="item"
                onChanged={() => setChanges((n) => n + 1)}
            />
        </>
    )
}
