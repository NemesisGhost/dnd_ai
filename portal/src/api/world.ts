import type {
    EventDetail,
    ItemDetail,
    LocationDetail,
    OrganizationDetail,
    ReligionDetail,
    WorldCategoryCounts,
    WorldEntityPage,
    WorldEntitySearchParameters,
} from "../types/world"

export class WorldRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `World request failed with status ${status}`,
        )
        this.name = "WorldRequestError"
        this.status = status
    }
}

function buildWorldSearchPath(
    campaignId: string,
    parameters: WorldEntitySearchParameters,
): string {
    const encodedCampaignId =
        encodeURIComponent(campaignId)

    const searchParameters = new URLSearchParams()

    if (parameters.category !== null) {
        searchParameters.set(
            "category",
            parameters.category,
        )
    }

    if (parameters.query !== "") {
        searchParameters.set("q", parameters.query)
    }

    if (parameters.cursor) {
        searchParameters.set(
            "cursor",
            parameters.cursor,
        )
    }

    if (parameters.includeHidden === true) {
        searchParameters.set("include_noncanon", "true")
        searchParameters.set("include_archived", "true")
    }

    if (parameters.limit !== undefined) {
        searchParameters.set(
            "limit",
            parameters.limit.toString(),
        )
    }

    const queryString = searchParameters.toString()

    const path =
        `/api/campaigns/${encodedCampaignId}/world/search`

    return queryString === ""
        ? path
        : `${path}?${queryString}`
}

export async function fetchWorldEntities(
    campaignId: string,
    parameters: WorldEntitySearchParameters,
    signal?: AbortSignal,
): Promise<WorldEntityPage> {
    const response = await fetch(
        buildWorldSearchPath(campaignId, parameters),
        {
            method: "GET",
            headers: {
                Accept: "application/json",
            },
            cache: "no-store",
            signal,
        },
    )

    if (!response.ok) {
        throw new WorldRequestError(response.status)
    }

    return (await response.json()) as WorldEntityPage
}

export async function fetchWorldCategoryCounts(
    campaignId: string,
    parameters: { query: string; includeHidden?: boolean },
    signal?: AbortSignal,
): Promise<WorldCategoryCounts> {
    const searchParameters = new URLSearchParams()

    if (parameters.query !== "") {
        searchParameters.set("q", parameters.query)
    }

    if (parameters.includeHidden === true) {
        searchParameters.set("include_noncanon", "true")
        searchParameters.set("include_archived", "true")
    }

    const queryString = searchParameters.toString()
    const path = `/api/campaigns/${encodeURIComponent(campaignId)}/world/search/counts`
    const response = await fetch(
        queryString === "" ? path : `${path}?${queryString}`,
        {
            method: "GET",
            headers: { Accept: "application/json" },
            cache: "no-store",
            signal,
        },
    )

    if (!response.ok) {
        throw new WorldRequestError(response.status)
    }

    return (await response.json()) as WorldCategoryCounts
}

async function fetchWorldDetail<T>(
    path: string,
    signal?: AbortSignal,
): Promise<T> {
    const response = await fetch(path, {
        method: "GET",
        headers: {
            Accept: "application/json",
        },
        cache: "no-store",
        signal,
    })

    if (!response.ok) {
        throw new WorldRequestError(response.status)
    }

    return (await response.json()) as T
}

export async function fetchLocationDetail(
    campaignId: string,
    locationId: string,
    signal?: AbortSignal,
): Promise<LocationDetail> {
    return fetchWorldDetail<LocationDetail>(
        `/api/campaigns/${encodeURIComponent(campaignId)}` +
            `/world/locations/${encodeURIComponent(locationId)}`,
        signal,
    )
}

export async function fetchOrganizationDetail(
    campaignId: string,
    organizationId: string,
    signal?: AbortSignal,
): Promise<OrganizationDetail> {
    return fetchWorldDetail<OrganizationDetail>(
        `/api/campaigns/${encodeURIComponent(campaignId)}` +
            `/world/organizations/${encodeURIComponent(organizationId)}`,
        signal,
    )
}

export async function fetchReligionDetail(
    campaignId: string,
    religionId: string,
    signal?: AbortSignal,
): Promise<ReligionDetail> {
    return fetchWorldDetail<ReligionDetail>(
        `/api/campaigns/${encodeURIComponent(campaignId)}` +
            `/world/religions/${encodeURIComponent(religionId)}`,
        signal,
    )
}

export async function fetchItemDetail(
    campaignId: string,
    itemInstanceId: string,
    signal?: AbortSignal,
): Promise<ItemDetail> {
    return fetchWorldDetail<ItemDetail>(
        `/api/campaigns/${encodeURIComponent(campaignId)}` +
            `/world/items/${encodeURIComponent(itemInstanceId)}`,
        signal,
    )
}

export async function fetchEventDetail(
    campaignId: string,
    eventId: string,
    signal?: AbortSignal,
): Promise<EventDetail> {
    return fetchWorldDetail<EventDetail>(
        `/api/campaigns/${encodeURIComponent(campaignId)}` +
            `/world/events/${encodeURIComponent(eventId)}`,
        signal,
    )
}