import { Link } from "react-router"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import type { CharacterKind } from "../types/character"
import { BuildsLink, PortrayalLink } from "./NpcAuthoringControls"

// The editors' "Manage" row on a character's sheet. Every control is a link to a page that keeps
// its own eligibility rules and saves: the sheet shows what a character is, and never embeds the
// controls that change it. Nothing mounts, and no request is sent, for a caller without
// `canon.edit`. Run this NPC and How this NPC is played belong to NPCs only; the builds link
// appears only where the builds read finds a buildable character.
export function CharacterManageLinks({
    campaignId,
    characterId,
    kind,
}: {
    campaignId: string
    characterId: string
    kind: CharacterKind
}) {
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    if (!canEdit) {
        return null
    }
    const root = `/app/${encodeURIComponent(campaignId)}`
    const id = encodeURIComponent(characterId)
    return (
        <nav aria-label="Manage character" className="authoring-page__actions-row character-manage">
            <Link className="authoring-button" to={`${root}/world/character/${id}`}>
                Open in World
            </Link>
            <Link className="authoring-button" to={`${root}/characters/${id}/edit`}>
                Edit
            </Link>
            <BuildsLink campaignId={campaignId} characterId={characterId} />
            {kind === "npc" ? (
                <>
                    <Link className="authoring-button" to={`${root}/world/character/${id}?section=run`}>
                        Run this NPC
                    </Link>
                    <PortrayalLink campaignId={campaignId} characterId={characterId} detail={0} asButton />
                </>
            ) : null}
        </nav>
    )
}
