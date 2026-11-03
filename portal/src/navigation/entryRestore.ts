import { resolveSelectedCharacterId } from "../context/characterPerspective"
import type { SessionBootstrap } from "../types/bootstrap"
import { readEntryContext } from "./contexts"
import type { EntryContextV1, SelectedContext } from "./contexts"
import { EMPTY_SELECTION, selectionFor, selectionOwner } from "./selectedContextStore"
import type { SelectedContextSnapshot, SelectedContextState } from "./selectedContextStore"

// History retention for routes outside a campaign (a World page, /campaigns, Settings…): the mirror of
// the selected context that an entry records (state.ctx) and the validated restoration from it. The
// campaign layout owns both on a campaign route. Nothing here is authority: an entry only ever asks, and
// what it names is accepted only if the current bootstrap still says so.

/**
 * The selection an entry's stamp may restore, or null when the entry carries no usable stamp.
 *
 *   - Only the versioned stamp counts. The older perspective-only stamp names no campaign, so it
 *     cannot say what its perspective belonged to and restores nothing.
 *   - A stamp of no campaign restores an empty selection (it recorded "nothing selected").
 *   - A campaign must be in the bootstrap, and the stamp's world and timeline must be that campaign's
 *     own; otherwise the stamp is foreign or tampered and is ignored whole.
 *   - A perspective is an id the campaign authorizes, or `null`, an explicit none, which is kept apart
 *     from an unrecorded one. Anything else ignores the stamp whole.
 */
export function restorableSelection(state: unknown, bootstrap: SessionBootstrap): SelectedContextState | null {
    const read = readEntryContext(state)
    if (read.kind !== "v1") return null
    const { context } = read
    const owner = selectionOwner(bootstrap)
    if (context.campaignId === null) return { ...EMPTY_SELECTION, owner }
    const campaign = bootstrap.campaigns.find((candidate) => candidate.campaign_id === context.campaignId)
    if (campaign === undefined) return null
    if (context.worldId !== campaign.world_id || context.timelineId !== campaign.timeline_id) return null
    if (
        context.characterId !== null &&
        !campaign.character_perspectives.some((character) => character.character_id === context.characterId)
    ) {
        return null
    }
    return {
        owner,
        campaignId: campaign.campaign_id,
        worldId: campaign.world_id,
        timelineId: campaign.timeline_id,
        characterId: context.characterId,
    }
}

/**
 * The context an entry should record for the selection as it stands: ids only, validated against the
 * bootstrap. An uninitialized perspective is recorded as what it resolves to (the campaign's default, or
 * none), so a restored entry never has to guess.
 */
export function selectionToRecord(snapshot: SelectedContextSnapshot, bootstrap: SessionBootstrap): SelectedContext {
    const selection = selectionFor(snapshot, bootstrap)
    const campaign =
        selection.campaignId === null
            ? undefined
            : bootstrap.campaigns.find((candidate) => candidate.campaign_id === selection.campaignId)
    if (campaign === undefined) {
        return { campaignId: null, worldId: selection.worldId, timelineId: selection.timelineId, characterId: null }
    }
    const chosen = selection.characterId
    const authorized = (id: string): boolean =>
        campaign.character_perspectives.some((character) => character.character_id === id)
    return {
        campaignId: campaign.campaign_id,
        worldId: campaign.world_id,
        timelineId: campaign.timeline_id,
        characterId:
            typeof chosen === "string" ? (authorized(chosen) ? chosen : null) : resolveSelectedCharacterId(campaign, chosen),
    }
}

export type { EntryContextV1 }
