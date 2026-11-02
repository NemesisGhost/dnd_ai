import type { CharacterDetail } from "../../types/character"
import type { LocationDetail, OrganizationDetail, ReligionDetail } from "../../types/world"
import type { WorkspaceCategory } from "./worldStages"

const enc = encodeURIComponent

// The audience-safe detail the workspace's Details section reads, by category. The same responses
// the World readers use, read through the authoring resource so a refresh keeps the page mounted.
export type WorkspaceDetail = LocationDetail | OrganizationDetail | ReligionDetail | CharacterDetail

export function worldDetailPath(campaignId: string, category: WorkspaceCategory, entityId: string): string {
    switch (category) {
        case "location":
            return `/campaigns/${enc(campaignId)}/world/locations/${enc(entityId)}`
        case "organization":
            return `/campaigns/${enc(campaignId)}/world/organizations/${enc(entityId)}`
        case "religion":
            return `/campaigns/${enc(campaignId)}/world/religions/${enc(entityId)}`
        case "character":
            return `/campaigns/${enc(campaignId)}/characters/${enc(entityId)}`
    }
}

export const worldRecordPath = (campaignId: string, category: string, entityId: string): string =>
    `/app/${enc(campaignId)}/world/${enc(category)}/${enc(entityId)}`

export const worldHistoryPath = (campaignId: string, category: string, entityId: string): string =>
    `${worldRecordPath(campaignId, category, entityId)}/history`
