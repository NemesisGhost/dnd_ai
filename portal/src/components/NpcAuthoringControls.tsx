import { Link } from "react-router"
import { characterBuildsPath } from "../api/characterBuilds"
import { npcAuthoringPath } from "../api/npcAuthoring"
import { playerCharacterAuthoringPath } from "../api/playerCharacterAuthoring"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import type { CharacterBuilds } from "../types/characterBuilds"
import type { PlayerCharacterAuthoringView } from "../types/npcAuthoring"
import type { RecordAuthoring } from "../utils/recordAuthoring"

interface NpcAuthoringControlsProps {
    campaignId: string
    characterId: string
}

// The editor-only links of a character's workspace (components/world/WorldRecordWorkspace): the Access
// link for a player character, the builds link and the portrayal link of an NPC. Each mounts nothing,
// and sends no request, for a caller without `canon.edit`, and each kind's authoring read is a 404 for
// the other, so only the links that apply to the character appear. They take a change counter so a
// link never outlives the state that allowed it.

// For a published player character, people who can manage access get a link to
// the Access page with this character already chosen in the relationship control.
// A draft cannot be linked to a player, so it says so instead.
export function PlayerAccessLink({
    campaignId,
    characterId,
    detail,
}: NpcAuthoringControlsProps & { detail: number }) {
    if (!useCampaignCapability(campaignId, "canon.edit")) {
        return null
    }
    return <LoadedPlayerAccessLink campaignId={campaignId} characterId={characterId} detail={detail} />
}

function LoadedPlayerAccessLink({
    campaignId,
    characterId,
    detail,
}: NpcAuthoringControlsProps & { detail: number }) {
    const canManage = useCampaignCapability(campaignId, "access.manage")
    const { state } = useAuthoringResource<PlayerCharacterAuthoringView>(
        `${playerCharacterAuthoringPath(campaignId, characterId)}${detail === 0 ? "" : `?v=${detail}`}`,
    )
    if (state.kind !== "ready") {
        return null
    }
    if (state.data.canon_status !== "canon") {
        return (
            <p className="authoring-note">
                Publish this character before linking a player to it.
            </p>
        )
    }
    if (!canManage) {
        return null
    }
    return (
        <p className="authoring-page__actions-row">
            <Link
                className="authoring-button"
                to={`/app/${encodeURIComponent(campaignId)}/access?character=${encodeURIComponent(characterId)}`}
            >
                Link a player
            </Link>
        </p>
    )
}

// Editors get a link to a character's builds and starting state. The builds read
// is a 404 for anything that is not an NPC or player character, so a bare
// character shows no link, and a player sends no request at all.
export function BuildsLink({ campaignId, characterId }: NpcAuthoringControlsProps) {
    if (!useCampaignCapability(campaignId, "canon.edit")) {
        return null
    }
    return <LoadedBuildsLink campaignId={campaignId} characterId={characterId} />
}

function LoadedBuildsLink({ campaignId, characterId }: NpcAuthoringControlsProps) {
    const { state } = useAuthoringResource<CharacterBuilds>(
        characterBuildsPath(campaignId, characterId),
    )
    if (state.kind !== "ready") {
        return null
    }
    return (
        <p className="authoring-page__actions-row">
            <Link
                className="authoring-button"
                to={`/app/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(characterId)}/builds`}
            >
                Builds and starting state
            </Link>
        </p>
    )
}

// For an NPC, editors get a link to how it is played (its portrayal profile). The profile is the
// private side of shared world canon, so the link is mounted, and its read sent, only when the
// record's `authoring` says that side is the caller's to read.
export function PortrayalLink({
    campaignId,
    characterId,
    detail,
    asButton,
    authoring,
}: NpcAuthoringControlsProps & { detail: number; asButton?: boolean; authoring: RecordAuthoring }) {
    if (!useCampaignCapability(campaignId, "canon.edit") || !authoring.can_read_private) {
        return null
    }
    return (
        <LoadedPortrayalLink
            campaignId={campaignId}
            characterId={characterId}
            detail={detail}
            asButton={asButton}
        />
    )
}

function LoadedPortrayalLink({
    campaignId,
    characterId,
    detail,
    asButton,
}: NpcAuthoringControlsProps & { detail: number; asButton?: boolean }) {
    const { state } = useAuthoringResource<unknown>(
        `${npcAuthoringPath(campaignId, characterId)}${detail === 0 ? "" : `?v=${detail}`}`,
    )
    if (state.kind !== "ready") {
        return null
    }
    return (
        <p>
            <Link
                className={asButton === true ? "authoring-button" : undefined}
                to={`/app/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(characterId)}/portrayal`}
            >
                How this NPC is played
            </Link>
        </p>
    )
}
