import type { OrganizationReceipt, ReligionReceipt } from "../types/contentAuthoring"
import type {
    CreateOrganizationBody,
    CreateReligionBody,
    OrganizationParentOptionPage,
    ReligionReferenceOptionPage,
    UpdateOrganizationBody,
    UpdateReligionBody,
} from "../types/organizationAuthoring"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

function organizations(campaignId: string): string {
    return `/campaigns/${encodeURIComponent(campaignId)}/authoring/organizations`
}

function religions(campaignId: string): string {
    return `/campaigns/${encodeURIComponent(campaignId)}/authoring/religions`
}

function searchParams(query: string, forId: string | null): string {
    const params = new URLSearchParams({ limit: "25" })
    if (query.trim() !== "") params.set("q", query.trim())
    if (forId !== null) params.set("for", forId)
    return params.toString()
}

// --- organizations -----------------------------------------------------------------------------

export const organizationOptionsPath = (campaignId: string): string =>
    `${organizations(campaignId)}/options`

export const organizationAuthoringPath = (campaignId: string, organizationId: string): string =>
    `${organizations(campaignId)}/${encodeURIComponent(organizationId)}`

export const organizationParentOptionsPath = (
    campaignId: string,
    query: string,
    forOrganizationId: string | null,
): string => `${organizations(campaignId)}/parent-options?${searchParams(query, forOrganizationId)}`

export function fetchOrganizationParentOptions(
    campaignId: string,
    query: string,
    forOrganizationId: string | null,
    signal?: AbortSignal,
): Promise<OrganizationParentOptionPage> {
    return apiRequest<OrganizationParentOptionPage>(
        "GET",
        organizationParentOptionsPath(campaignId, query, forOrganizationId),
        { signal },
    )
}

export function createOrganization(
    campaignId: string,
    body: CreateOrganizationBody,
    ctx: MutationContext,
): Promise<OrganizationReceipt> {
    return apiRequest<OrganizationReceipt>("POST", organizations(campaignId), {
        body,
        ...ctx,
    })
}

export function updateOrganization(
    campaignId: string,
    organizationId: string,
    body: UpdateOrganizationBody,
    ctx: MutationContext,
): Promise<OrganizationReceipt> {
    return apiRequest<OrganizationReceipt>(
        "POST",
        `${organizationAuthoringPath(campaignId, organizationId)}/update`,
        { body, ...ctx },
    )
}

// --- religions ------------------------------------------------------------------------------------

export const religionOptionsPath = (campaignId: string): string =>
    `${religions(campaignId)}/options`

export const religionAuthoringPath = (campaignId: string, religionId: string): string =>
    `${religions(campaignId)}/${encodeURIComponent(religionId)}`

export function fetchReligionReferenceOptions(
    campaignId: string,
    query: string,
    signal?: AbortSignal,
): Promise<ReligionReferenceOptionPage> {
    return apiRequest<ReligionReferenceOptionPage>(
        "GET",
        `${religions(campaignId)}/reference-options?${searchParams(query, null)}`,
        { signal },
    )
}

export function createReligion(
    campaignId: string,
    body: CreateReligionBody,
    ctx: MutationContext,
): Promise<ReligionReceipt> {
    return apiRequest<ReligionReceipt>("POST", religions(campaignId), { body, ...ctx })
}

export function updateReligion(
    campaignId: string,
    religionId: string,
    body: UpdateReligionBody,
    ctx: MutationContext,
): Promise<ReligionReceipt> {
    return apiRequest<ReligionReceipt>(
        "POST",
        `${religionAuthoringPath(campaignId, religionId)}/update`,
        { body, ...ctx },
    )
}
