import type {
    CreateWorldRequest,
    CreateWorldResponse,
    TransitionRequest,
    UpdateWorldRequest,
    WorldDetail,
    WorldListResponse,
    WorldMutationResponse,
} from "../types/worldAuthoring"
import { apiRequest } from "./http"

export interface MutationContext {
    csrfToken: string
    idempotencyKey: string
    signal?: AbortSignal
}

export function worldsListPath(status: "active" | "archived" | "all"): string {
    return `/worlds?status=${status}`
}

export function worldPath(worldId: string): string {
    return `/worlds/${encodeURIComponent(worldId)}`
}

export function fetchWorlds(
    status: "active" | "archived" | "all",
    signal?: AbortSignal,
): Promise<WorldListResponse> {
    return apiRequest<WorldListResponse>("GET", worldsListPath(status), { signal })
}

export function fetchWorld(worldId: string, signal?: AbortSignal): Promise<WorldDetail> {
    return apiRequest<WorldDetail>("GET", worldPath(worldId), { signal })
}

export function createWorld(
    body: CreateWorldRequest,
    ctx: MutationContext,
): Promise<CreateWorldResponse> {
    return apiRequest<CreateWorldResponse>("POST", "/worlds", { body, ...ctx })
}

export function updateWorld(
    worldId: string,
    body: UpdateWorldRequest,
    ctx: MutationContext,
): Promise<WorldMutationResponse> {
    return apiRequest<WorldMutationResponse>("POST", `${worldPath(worldId)}/update`, {
        body,
        ...ctx,
    })
}

export function archiveWorld(
    worldId: string,
    body: TransitionRequest,
    ctx: MutationContext,
): Promise<WorldMutationResponse> {
    return apiRequest<WorldMutationResponse>("POST", `${worldPath(worldId)}/archive`, {
        body,
        ...ctx,
    })
}

export function restoreWorld(
    worldId: string,
    body: TransitionRequest,
    ctx: MutationContext,
): Promise<WorldMutationResponse> {
    return apiRequest<WorldMutationResponse>("POST", `${worldPath(worldId)}/restore`, {
        body,
        ...ctx,
    })
}
