import type {
    EntityTransitionBody,
    EntityTransitionResponse,
    SupersedeBody,
} from "../types/entityLifecycle"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

// Server action codes (snake_case) mapped to their route segment.
const SEGMENTS: Readonly<Record<string, string>> = {
    submit_for_review: "submit-for-review",
    return_to_draft: "return-to-draft",
    approve: "approve",
    reject: "reject",
    publish: "publish",
    supersede: "supersede",
    archive: "archive",
    restore: "restore",
    delete_draft: "delete-draft",
}

export function entityLifecyclePath(campaignId: string, entityId: string): string {
    return `/campaigns/${encodeURIComponent(campaignId)}/entities/${encodeURIComponent(entityId)}/lifecycle`
}

export function replacementCandidatesPath(
    campaignId: string,
    entityId: string,
    query: string,
): string {
    const base = `${entityLifecyclePath(campaignId, entityId)}/replacement-candidates?limit=25`
    return query.trim() === "" ? base : `${base}&q=${encodeURIComponent(query.trim())}`
}

export function runEntityAction(
    campaignId: string,
    entityId: string,
    action: string,
    body: EntityTransitionBody | SupersedeBody,
    ctx: MutationContext,
): Promise<EntityTransitionResponse> {
    const segment = SEGMENTS[action]
    if (segment === undefined) {
        return Promise.reject(new Error(`Unknown lifecycle action: ${action}`))
    }
    return apiRequest<EntityTransitionResponse>(
        "POST",
        `${entityLifecyclePath(campaignId, entityId)}/${segment}`,
        { body, ...ctx },
    )
}
