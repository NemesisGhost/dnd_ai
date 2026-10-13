import type { MockServer } from "./authoringHarness"

// The reads the editors' World record workspace makes beyond the record itself: its revisions, its
// provenance and the world's sources. Test support for the route tests.

export const SOURCE_LIST = {
    items: [],
    source_types: [{ value: "session", label: "Session" }],
    limits: { title_max_length: 200, reference_max_length: 500 },
}

export interface RevisionFixture {
    row_version: number
    kind: string
    created_at: string
    created_by_name: string | null
    canon_status: string | null
    lifecycle_status: string | null
}

export function installRecordReads(
    server: MockServer,
    options: {
        campaignId: string
        entityId: string
        name?: string
        entityTypeCode?: string
        canon?: string
        revisions?: RevisionFixture[]
    },
): void {
    const { campaignId, entityId } = options
    const name = options.name ?? "Record"
    const canon = options.canon ?? "draft"
    const revisions = options.revisions ?? [
        {
            row_version: 1,
            kind: "created",
            created_at: "2026-01-01T10:00:00Z",
            created_by_name: "Gina",
            canon_status: null,
            lifecycle_status: null,
        },
    ]
    server.on("GET", `/campaigns/${campaignId}/entities/${entityId}/revisions`, {
        body: {
            entity_id: entityId,
            name,
            entity_type_code: options.entityTypeCode ?? "settlement",
            canon_status: canon,
            lifecycle_status: "active",
            row_version: revisions[0]?.row_version ?? 1,
            revisions,
        },
    })
    server.on("GET", `/campaigns/${campaignId}/entities/${entityId}/provenance`, {
        body: {
            entity_id: entityId,
            name,
            entity_type_code: options.entityTypeCode ?? "settlement",
            canon_status: canon,
            lifecycle_status: "active",
            created_at: "2026-01-01T10:00:00Z",
            created_by_name: "Gina",
            origin: null,
            links: [],
            transitions: [],
            superseded_by: null,
            supersedes: [],
        },
    })
    server.on("GET", `/campaigns/${campaignId}/sources`, { body: SOURCE_LIST })
}
