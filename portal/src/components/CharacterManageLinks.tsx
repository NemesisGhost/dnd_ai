import { Link } from "react-router"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { useHeldWorldCapability, WORLD_CANON_READ_PRIVATE } from "../hooks/useWorldCapability"
import type { CharacterKind } from "../types/character"
import { NO_RECORD_AUTHORING } from "../utils/recordAuthoring"
import type { RecordAuthoring } from "../utils/recordAuthoring"
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
    authoring = NO_RECORD_AUTHORING,
}: {
    campaignId: string
    characterId: string
    kind: CharacterKind
    // The server's eligibility for this character (the character read's `authoring`): which of the
    // links below are the caller's to use. Absent means none that edit shared canon.
    authoring?: RecordAuthoring
}) {
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    // A relationship is shared world canon whatever it relates (even a player character), so its
    // section is the world's private side, not the record's own eligibility.
    const canPrepareWorld = useHeldWorldCapability(campaignId, WORLD_CANON_READ_PRIVATE)
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
            {authoring.can_edit ? (
                <Link className="authoring-button" to={`${root}/characters/${id}/edit`}>
                    Edit
                </Link>
            ) : null}
            {canPrepareWorld ? (
                <Link className="authoring-button" to={`${root}/world/character/${id}?section=relationships`}>
                    Relationships
                </Link>
            ) : null}
            <BuildsLink campaignId={campaignId} characterId={characterId} />
            {kind === "npc" ? (
                <>
                    <Link className="authoring-button" to={`${root}/world/character/${id}?section=run`}>
                        Run this NPC
                    </Link>
                    <PortrayalLink
                        campaignId={campaignId}
                        characterId={characterId}
                        detail={0}
                        asButton
                        authoring={authoring}
                    />
                </>
            ) : null}
        </nav>
    )
}
