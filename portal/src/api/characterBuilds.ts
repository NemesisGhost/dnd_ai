import type { BuildReceipt, CreateBuildBody } from "../types/characterBuilds"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export const buildOptionsPath = (campaignId: string): string =>
    `/campaigns/${enc(campaignId)}/authoring/character-build-options`

export const characterBuildsPath = (campaignId: string, characterId: string): string =>
    `/campaigns/${enc(campaignId)}/authoring/characters/${enc(characterId)}/builds`

export function createBuild(
    campaignId: string,
    characterId: string,
    body: CreateBuildBody,
    ctx: MutationContext,
): Promise<BuildReceipt> {
    return apiRequest<BuildReceipt>("POST", characterBuildsPath(campaignId, characterId), {
        body,
        ...ctx,
    })
}

export function activateBuild(
    campaignId: string,
    characterId: string,
    buildId: string,
    expectedActiveBuildId: string | null,
    ctx: MutationContext,
): Promise<BuildReceipt> {
    return apiRequest<BuildReceipt>(
        "POST",
        `${characterBuildsPath(campaignId, characterId)}/${enc(buildId)}/activate`,
        { body: { expected_active_build_id: expectedActiveBuildId }, ...ctx },
    )
}

export function initializeCharacterState(
    campaignId: string,
    characterId: string,
    body: { maximum_hit_points: number; current_hit_points: number | null },
    ctx: MutationContext,
): Promise<BuildReceipt> {
    return apiRequest<BuildReceipt>(
        "POST",
        `/campaigns/${enc(campaignId)}/authoring/characters/${enc(characterId)}/state/initialize`,
        { body, ...ctx },
    )
}
