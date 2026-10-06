import { useState } from "react"
import { Link } from "react-router"
import { characterBuildsPath } from "../api/characterBuilds"
import { npcAuthoringPath } from "../api/npcAuthoring"
import { playerCharacterAuthoringPath } from "../api/playerCharacterAuthoring"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import type { CharacterBuilds } from "../types/characterBuilds"
import type { PlayerCharacterAuthoringView } from "../types/npcAuthoring"
import { AuthoringEditLink } from "./AuthoringEditLink"
import { EntityLifecyclePanel } from "./EntityLifecyclePanel"
import { NpcRuntimePanel } from "./NpcRuntimePanel"

interface NpcAuthoringControlsProps {
    campaignId: string
    characterId: string
}

// Editor-only controls under a character's World detail: an Edit link and the
// lifecycle panel. Both mount nothing for a caller without `canon.edit`, so this
// sends no request for a player. Each kind's authoring read is a 404 for the
// other, so exactly one Edit link (NPC or player character) can appear. A
// lifecycle change refreshes the edit link so it never outlives the state that
// allowed it.
export function NpcAuthoringControls({ campaignId, characterId }: NpcAuthoringControlsProps) {
    const [changes, setChanges] = useState(0)
    const editPath = `/app/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(characterId)}/edit`
    return (
        <>
            <AuthoringEditLink
                campaignId={campaignId}
                noun="NPC"
                viewPath={npcAuthoringPath(campaignId, characterId)}
                editPath={editPath}
                detail={changes}
            />
            <AuthoringEditLink
                campaignId={campaignId}
                noun="player character"
                viewPath={playerCharacterAuthoringPath(campaignId, characterId)}
                editPath={editPath}
                detail={changes}
            />
            <PlayerAccessLink campaignId={campaignId} characterId={characterId} detail={changes} />
            <PortrayalLink campaignId={campaignId} characterId={characterId} detail={changes} />
            <BuildsLink campaignId={campaignId} characterId={characterId} />
            <NpcRuntimePanel campaignId={campaignId} characterId={characterId} />
            <EntityLifecyclePanel
                campaignId={campaignId}
                entityId={characterId}
                onChanged={() => setChanges((n) => n + 1)}
            />
        </>
    )
}

// For a published player character, people who can manage access get a link to
// the Access page with this character already chosen in the relationship control.
// A draft cannot be linked to a player, so it says so instead.
function PlayerAccessLink({
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
function BuildsLink({ campaignId, characterId }: NpcAuthoringControlsProps) {
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

// For an NPC, editors get a link to how it is played (its portrayal profile).
function PortrayalLink({
    campaignId,
    characterId,
    detail,
}: NpcAuthoringControlsProps & { detail: number }) {
    if (!useCampaignCapability(campaignId, "canon.edit")) {
        return null
    }
    return <LoadedPortrayalLink campaignId={campaignId} characterId={characterId} detail={detail} />
}

function LoadedPortrayalLink({
    campaignId,
    characterId,
    detail,
}: NpcAuthoringControlsProps & { detail: number }) {
    const { state } = useAuthoringResource<unknown>(
        `${npcAuthoringPath(campaignId, characterId)}${detail === 0 ? "" : `?v=${detail}`}`,
    )
    if (state.kind !== "ready") {
        return null
    }
    return (
        <p>
            <Link
                to={`/app/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(characterId)}/portrayal`}
            >
                How this NPC is played
            </Link>
        </p>
    )
}
