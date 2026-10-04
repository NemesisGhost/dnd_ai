import type {
    CreateBranchRequest,
    CreateBranchResponse,
    CreateTimelineRequest,
    CreateTimelineResponse,
    TimelineMutationResponse,
    UpdateTimelineRequest,
} from "../types/timelineAuthoring"
import type { TransitionRequest } from "../types/worldAuthoring"
import { apiRequest } from "./http"
import { worldPath } from "./worlds"
import type { MutationContext } from "./worlds"

export function timelinesPath(worldId: string): string {
    return `${worldPath(worldId)}/timelines`
}

export function timelinePath(worldId: string, timelineId: string): string {
    return `${timelinesPath(worldId)}/${encodeURIComponent(timelineId)}`
}

export function branchPointsPath(worldId: string, timelineId: string): string {
    return `${timelinePath(worldId, timelineId)}/branch-points?limit=100`
}

export function createTimeline(
    worldId: string,
    body: CreateTimelineRequest,
    ctx: MutationContext,
): Promise<CreateTimelineResponse> {
    return apiRequest<CreateTimelineResponse>("POST", timelinesPath(worldId), { body, ...ctx })
}

export function updateTimeline(
    worldId: string,
    timelineId: string,
    body: UpdateTimelineRequest,
    ctx: MutationContext,
): Promise<TimelineMutationResponse> {
    return apiRequest<TimelineMutationResponse>(
        "POST",
        `${timelinePath(worldId, timelineId)}/update`,
        { body, ...ctx },
    )
}

export function createBranch(
    worldId: string,
    parentTimelineId: string,
    body: CreateBranchRequest,
    ctx: MutationContext,
): Promise<CreateBranchResponse> {
    return apiRequest<CreateBranchResponse>(
        "POST",
        `${timelinePath(worldId, parentTimelineId)}/branches`,
        { body, ...ctx },
    )
}

export function archiveTimeline(
    worldId: string,
    timelineId: string,
    body: TransitionRequest,
    ctx: MutationContext,
): Promise<TimelineMutationResponse> {
    return apiRequest<TimelineMutationResponse>(
        "POST",
        `${timelinePath(worldId, timelineId)}/archive`,
        { body, ...ctx },
    )
}

export function restoreTimeline(
    worldId: string,
    timelineId: string,
    body: TransitionRequest,
    ctx: MutationContext,
): Promise<TimelineMutationResponse> {
    return apiRequest<TimelineMutationResponse>(
        "POST",
        `${timelinePath(worldId, timelineId)}/restore`,
        { body, ...ctx },
    )
}
