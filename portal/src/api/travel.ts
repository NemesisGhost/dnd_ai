import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export interface TravelBody {
    destination_location_id: string
    character_ids: string[]
    party_id: string | null
    route_id: string | null
    world_time_id?: string | null
    note?: string | null
}

export interface TravelReceipt {
    destination_location_id: string
    changed: boolean
    moved: string[]
    already_there: string[]
    event_id?: string
    // Present on a session-scoped receipt.
    session_id?: string
}

export interface RouteItem {
    relationship_id: string
    description: string | null
    origin: { entity_id: string; name: string } | null
    destination: { entity_id: string; name: string } | null
}

export const routesPath = (campaignId: string, locationId: string): string =>
    `/campaigns/${enc(campaignId)}/authoring/routes?location_id=${enc(locationId)}`

export function recordTravel(
    campaignId: string,
    body: TravelBody,
    ctx: MutationContext,
): Promise<TravelReceipt> {
    return apiRequest<TravelReceipt>("POST", `/campaigns/${enc(campaignId)}/travel`, {
        body,
        ...ctx,
    })
}

// Travel recorded in a session in progress: the server links the event to that session
// (the id comes from the path only). The plain route above records standalone travel.
export function recordSessionTravel(
    campaignId: string,
    sessionId: string,
    body: TravelBody,
    ctx: MutationContext,
): Promise<TravelReceipt> {
    return apiRequest<TravelReceipt>(
        "POST",
        `/campaigns/${enc(campaignId)}/sessions/${enc(sessionId)}/travel`,
        { body, ...ctx },
    )
}
