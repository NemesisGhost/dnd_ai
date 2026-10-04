import type { AuthoringReadModel, ContentLimits, EntityReferenceSummary } from "./contentAuthoring"

// Typed Organization and Religion authoring contracts (Phase 15.1).

export interface OrganizationFieldDescriptor {
    name: string
    kind: "text" | "longtext" | "integer" | "select"
    label: string
    max_length: number | null
    minimum: number | null
    maximum: number | null
    required: boolean
    options: { value: string; label: string }[]
}

export interface OrganizationKindOption {
    code: string
    label: string
    needs_religion: boolean
    fields: OrganizationFieldDescriptor[]
}

export interface OrganizationOptions {
    can_create: boolean
    kinds: OrganizationKindOption[]
    limits: ContentLimits & { description_max_length: number }
    generic_types: { value: string; label: string }[]
}

export interface OrganizationAuthoringView extends AuthoringReadModel {
    organization_id: string
    name: string
    summary: string | null
    kind: { code: string; label: string }
    organization_type: string
    public_description: string | null
    internal_description: string | null
    parent: EntityReferenceSummary | null
    headquarters: EntityReferenceSummary | null
    religion: EntityReferenceSummary | null
    // Kind-specific values keyed by field name.
    typed: Record<string, string | number | null>
}

// Typed fields travel flat in the body, exactly as the server's strict model.
export interface OrganizationFieldsBody {
    name: string
    summary: string | null
    public_description: string | null
    internal_description: string | null
    parent_organization_id: string | null
    headquarters_location_id: string | null
    religion_id: string | null
    organization_type?: string | null
    business_type?: string | null
    operating_status?: string | null
    reputation?: number | null
    government_form?: string | null
    unit_type?: string | null
    ideology?: string | null
}

export interface CreateOrganizationBody extends OrganizationFieldsBody {
    kind: string
}

export interface UpdateOrganizationBody extends OrganizationFieldsBody {
    expected_row_version: number
    change_note?: string | null
}

export interface OrganizationParentOption {
    organization_id: string
    name: string
    kind: string
    canon_status: string
}

export interface OrganizationParentOptionPage {
    items: OrganizationParentOption[]
    next_cursor: string | null
}

export interface ReligionOptions {
    can_create: boolean
    limits: ContentLimits & { pantheon_max_length: number }
}

export interface ReligionAuthoringView extends AuthoringReadModel {
    religion_id: string
    name: string
    summary: string | null
    pantheon_structure: string | null
}

export interface ReligionFieldsBody {
    name: string
    summary: string | null
    pantheon_structure: string | null
}

export type CreateReligionBody = ReligionFieldsBody

export interface UpdateReligionBody extends ReligionFieldsBody {
    expected_row_version: number
    change_note?: string | null
}

export interface ReligionReferenceOptionPage {
    items: { religion_id: string; name: string; canon_status: string }[]
    next_cursor: string | null
}
