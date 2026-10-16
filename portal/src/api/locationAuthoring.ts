import type { LocationReceipt } from "../types/contentAuthoring"
import type { CreateLocationBody, LocationParentOptionPage, UpdateLocationBody } from "../types/locationAuthoring"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

function base(campaignId: string): string {
    return `/campaigns/${encodeURIComponent(campaignId)}/authoring/locations`
}

export function locationOptionsPath(campaignId: string): string {
    return `${base(campaignId)}/options`
}

export function locationAuthoringPath(campaignId: string, locationId: string): string {
    return `${base(campaignId)}/${encodeURIComponent(locationId)}`
}

export function locationParentOptionsPath(
    campaignId: string,
    query: string,
    forLocationId: string | null,
): string {
    const params = new URLSearchParams({ limit: "25" })
    if (query.trim() !== "") {
        params.set("q", query.trim())
    }
    if (forLocationId !== null) {
        params.set("for", forLocationId)
    }
    return `${base(campaignId)}/parent-options?${params.toString()}`
}

export function fetchLocationParentOptions(
    campaignId: string,
    query: string,
    forLocationId: string | null,
    signal?: AbortSignal,
): Promise<LocationParentOptionPage> {
    return apiRequest<LocationParentOptionPage>(
        "GET",
        locationParentOptionsPath(campaignId, query, forLocationId),
        { signal },
    )
}

export function createLocation(
    campaignId: string,
    body: CreateLocationBody,
    ctx: MutationContext,
): Promise<LocationReceipt> {
    return apiRequest<LocationReceipt>("POST", base(campaignId), { body, ...ctx })
}

export function updateLocation(
    campaignId: string,
    locationId: string,
    body: UpdateLocationBody,
    ctx: MutationContext,
): Promise<LocationReceipt> {
    return apiRequest<LocationReceipt>(
        "POST",
        `${locationAuthoringPath(campaignId, locationId)}/update`,
        { body, ...ctx },
    )
}
