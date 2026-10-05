import { useState } from "react"
import { npcAuthoringPath } from "../api/npcAuthoring"
import { AuthoringEditLink } from "./AuthoringEditLink"
import { EntityLifecyclePanel } from "./EntityLifecyclePanel"

interface NpcAuthoringControlsProps {
    campaignId: string
    characterId: string
}

// Editor-only controls under a character's World detail: an Edit link and the
// lifecycle panel. Both mount nothing for a caller without `canon.edit` (and the
// panel nothing for a player character, which is not lifecycle-managed; the edit
// read is a 404 for anything that is not an NPC), so this sends no request for a
// player. A lifecycle change refreshes the edit link so it never outlives the
// state that allowed it.
export function NpcAuthoringControls({ campaignId, characterId }: NpcAuthoringControlsProps) {
    const [changes, setChanges] = useState(0)
    return (
        <>
            <AuthoringEditLink
                campaignId={campaignId}
                noun="NPC"
                viewPath={npcAuthoringPath(campaignId, characterId)}
                editPath={`/app/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(characterId)}/edit`}
                detail={changes}
            />
            <EntityLifecyclePanel
                campaignId={campaignId}
                entityId={characterId}
                onChanged={() => setChanges((n) => n + 1)}
            />
        </>
    )
}
