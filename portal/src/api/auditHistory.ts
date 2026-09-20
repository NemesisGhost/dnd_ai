import type {
    AuditHistoryFilters,
    AuditHistoryPage,
} from "../types/auditHistory"

export class AuditHistoryRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Audit history request failed with status ${status}`,
        )
        this.name = "AuditHistoryRequestError"
        this.status = status
    }
}

function buildAuditHistoryPath(
    campaignId: string,
    filters: AuditHistoryFilters,
    cursor: string | null,
    limit: number | undefined,
): string {
    const encodedCampaignId =
        encodeURIComponent(campaignId)

    const searchParameters = new URLSearchParams()

    if (filters.category !== null) {
        searchParameters.set(
            "category",
            filters.category,
        )
    }

    if (filters.actorUserId !== null && filters.actorUserId !== "") {
        searchParameters.set(
            "actor_user_id",
            filters.actorUserId,
        )
    }

    if (filters.occurredFrom !== null && filters.occurredFrom !== "") {
        searchParameters.set(
            "occurred_from",
            filters.occurredFrom,
        )
    }

    if (filters.occurredTo !== null && filters.occurredTo !== "") {
        searchParameters.set(
            "occurred_to",
            filters.occurredTo,
        )
    }

    if (cursor !== null) {
        searchParameters.set("cursor", cursor)
    }

    if (limit !== undefined) {
        searchParameters.set(
            "limit",
            limit.toString(),
        )
    }

    const queryString = searchParameters.toString()

    const path =
        `/api/campaigns/${encodedCampaignId}/audit-history`

    return queryString === ""
        ? path
        : `${path}?${queryString}`
}

export async function fetchAuditHistory(
    campaignId: string,
    filters: AuditHistoryFilters,
    cursor: string | null,
    signal?: AbortSignal,
    limit?: number,
): Promise<AuditHistoryPage> {
    const response = await fetch(
        buildAuditHistoryPath(
            campaignId,
            filters,
            cursor,
            limit,
        ),
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
        throw new AuditHistoryRequestError(
            response.status,
        )
    }

    return (await response.json()) as AuditHistoryPage
}
