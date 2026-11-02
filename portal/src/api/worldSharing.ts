import type {
    AssignWorldRoleRequest,
    TransferOwnershipRequest,
    WorldAccessView,
    WorldCanonResponse,
    WorldSharingChange,
    WorldTransferResult,
} from "../types/worldSharing"
import { apiRequest } from "./http"
import { worldPath } from "./worlds"
import type { MutationContext } from "./worlds"

export function worldAccessPath(worldId: string): string {
    return `${worldPath(worldId)}/access`
}

export function worldCanonPath(worldId: string, query: string, cursor: string | null): string {
    const params = new URLSearchParams()
    if (query.trim() !== "") params.set("q", query.trim())
    if (cursor !== null) params.set("cursor", cursor)
    params.set("limit", "50")
    return `${worldPath(worldId)}/canon?${params.toString()}`
}

export function fetchWorldCanon(
    worldId: string,
    query: string,
    cursor: string | null,
    signal?: AbortSignal,
): Promise<WorldCanonResponse> {
    return apiRequest<WorldCanonResponse>("GET", worldCanonPath(worldId, query, cursor), { signal })
}

export function assignWorldRole(
    worldId: string,
    body: AssignWorldRoleRequest,
    ctx: MutationContext,
): Promise<WorldSharingChange> {
    return apiRequest<WorldSharingChange>("POST", `${worldPath(worldId)}/roles`, { body, ...ctx })
}

export function endWorldRole(
    worldId: string,
    worldMembershipId: string,
    ctx: MutationContext,
): Promise<WorldSharingChange> {
    return apiRequest<WorldSharingChange>(
        "POST",
        `${worldPath(worldId)}/roles/${encodeURIComponent(worldMembershipId)}/end`,
        { body: {}, ...ctx },
    )
}

export function grantWorldUse(
    worldId: string,
    loginName: string,
    ctx: MutationContext,
): Promise<WorldSharingChange> {
    return apiRequest<WorldSharingChange>("POST", `${worldPath(worldId)}/use-grants`, {
        body: { login_name: loginName },
        ...ctx,
    })
}

export function revokeWorldUse(
    worldId: string,
    worldUseGrantId: string,
    ctx: MutationContext,
): Promise<WorldSharingChange> {
    return apiRequest<WorldSharingChange>(
        "POST",
        `${worldPath(worldId)}/use-grants/${encodeURIComponent(worldUseGrantId)}/revoke`,
        { body: {}, ...ctx },
    )
}

export function transferWorldOwnership(
    worldId: string,
    body: TransferOwnershipRequest,
    ctx: MutationContext,
): Promise<WorldTransferResult> {
    return apiRequest<WorldTransferResult>("POST", `${worldPath(worldId)}/ownership-transfer`, {
        body,
        ...ctx,
    })
}

export type { WorldAccessView }
