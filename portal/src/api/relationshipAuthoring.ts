import type {
    CreateRelationshipBody,
    RelationshipCommand,
    RelationshipView,
} from "../types/relationshipAuthoring"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

function base(campaignId: string): string {
    return `/campaigns/${enc(campaignId)}/authoring/relationships`
}

export const relationshipOptionsPath = (campaignId: string): string =>
    `${base(campaignId)}/options`

export const entityRelationshipsPath = (
    campaignId: string,
    entityId: string,
    includeArchived: boolean,
): string =>
    `${base(campaignId)}?entity_id=${enc(entityId)}${includeArchived ? "&include_archived=true" : ""}`

export const relationshipAuthoringPath = (campaignId: string, relationshipId: string): string =>
    `${base(campaignId)}/${enc(relationshipId)}`

export function createRelationship(
    campaignId: string,
    body: CreateRelationshipBody,
    ctx: MutationContext,
): Promise<RelationshipView> {
    return apiRequest<RelationshipView>("POST", base(campaignId), { body, ...ctx })
}

const PATH = {
    update: "update",
    end: "end",
    archive: "archive",
    restore: "restore",
    perspective: "perspectives",
} as const

export function runRelationshipCommand(
    campaignId: string,
    relationshipId: string,
    command: RelationshipCommand,
    ctx: MutationContext,
): Promise<RelationshipView> {
    return apiRequest<RelationshipView>(
        "POST",
        `${relationshipAuthoringPath(campaignId, relationshipId)}/${PATH[command.op]}`,
        { body: command.body, ...ctx },
    )
}
