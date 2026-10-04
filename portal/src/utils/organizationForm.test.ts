import { describe, expect, it } from "vitest"
import type {
    OrganizationAuthoringView,
    OrganizationKindOption,
} from "../types/organizationAuthoring"
import {
    EMPTY_ORGANIZATION_FORM,
    sameOrganizationValues,
    toOrganizationBody,
    validateOrganizationForm,
    valuesFromOrganizationView,
} from "./organizationForm"

const business: OrganizationKindOption = {
    code: "business",
    label: "Business",
    needs_religion: false,
    fields: [
        { name: "business_type", kind: "text", label: "Kind of business", max_length: 200, minimum: null, maximum: null, required: false, options: [] },
        {
            name: "operating_status",
            kind: "select",
            label: "Operating status",
            max_length: null,
            minimum: null,
            maximum: null,
            required: false,
            options: [
                { value: "operating", label: "Operating" },
                { value: "closed", label: "Closed" },
            ],
        },
        { name: "reputation", kind: "integer", label: "Reputation", max_length: null, minimum: -100, maximum: 100, required: false, options: [] },
    ],
}
const religious: OrganizationKindOption = {
    code: "religious_organization",
    label: "Religious organization",
    needs_religion: true,
    fields: [],
}
const generic: OrganizationKindOption = {
    code: "organization",
    label: "Organization",
    needs_religion: false,
    fields: [
        {
            name: "organization_type",
            kind: "select",
            label: "Kind of organization",
            max_length: null,
            minimum: null,
            maximum: null,
            required: true,
            options: [{ value: "guild", label: "Guild" }],
        },
    ],
}

const filled = { ...EMPTY_ORGANIZATION_FORM, kind: "business", name: "Forge" }

describe("validateOrganizationForm", () => {
    it("requires a kind on create and a name always", () => {
        const ids = validateOrganizationForm(EMPTY_ORGANIZATION_FORM, undefined, { requireKind: true }).map(
            (e) => e.fieldId,
        )
        expect(ids).toEqual(["org-kind", "org-name"])
    })

    it("requires a religion for a religious organization only", () => {
        const values = { ...filled, kind: "religious_organization" }
        expect(validateOrganizationForm(values, religious, { requireKind: true }).map((e) => e.fieldId)).toEqual([
            "org-religion",
        ])
        expect(
            validateOrganizationForm({ ...values, religion: { id: "r1", label: "Faith" } }, religious, {
                requireKind: true,
            }),
        ).toEqual([])
        expect(validateOrganizationForm(filled, business, { requireKind: true })).toEqual([])
    })

    it("checks typed integer, select, and text fields against the catalog", () => {
        const problems = (typed: Record<string, string>) =>
            validateOrganizationForm({ ...filled, typed }, business, { requireKind: true }).map((e) => e.fieldId)
        expect(problems({ reputation: "101" })).toEqual(["org-field-reputation"])
        expect(problems({ reputation: "-101" })).toEqual(["org-field-reputation"])
        expect(problems({ reputation: "1.5" })).toEqual(["org-field-reputation"])
        expect(problems({ reputation: "-100" })).toEqual([])
        expect(problems({ operating_status: "thriving" })).toEqual(["org-field-operating_status"])
        expect(problems({ business_type: "x".repeat(201) })).toEqual(["org-field-business_type"])
    })

    it("requires the generic kind to choose its type", () => {
        const values = { ...filled, kind: "organization" }
        expect(validateOrganizationForm(values, generic, { requireKind: true }).map((e) => e.fieldId)).toEqual([
            "org-field-organization_type",
        ])
    })

    it("bounds both descriptions", () => {
        const ids = validateOrganizationForm(
            { ...filled, publicDescription: "x".repeat(4001), internalDescription: "y".repeat(4001) },
            business,
            { requireKind: true },
        ).map((e) => e.fieldId)
        expect(ids).toEqual(["org-public-description", "org-internal-description"])
    })
})

describe("toOrganizationBody", () => {
    it("flattens typed fields, trims, nulls blanks, and parses integers", () => {
        const body = toOrganizationBody(
            {
                ...filled,
                name: "  Forge ",
                publicDescription: " Known ",
                typed: { business_type: " Smithy ", operating_status: "", reputation: " -20 " },
                parent: { id: "p1", label: "Crown" },
                headquarters: { id: "h1", label: "Keep" },
            },
            business,
        )
        expect(body).toEqual({
            name: "Forge",
            summary: null,
            public_description: "Known",
            internal_description: null,
            parent_organization_id: "p1",
            headquarters_location_id: "h1",
            religion_id: null,
            business_type: "Smithy",
            operating_status: null,
            reputation: -20,
        })
    })

    it("never sends typed values or a religion the kind does not carry", () => {
        const body = toOrganizationBody(
            {
                ...filled,
                kind: "government",
                typed: { reputation: "50", government_form: "Council" },
                religion: { id: "r1", label: "Faith" },
            },
            { code: "government", label: "Government", needs_religion: false, fields: [
                { name: "government_form", kind: "text", label: "Form", max_length: 200, minimum: null, maximum: null, required: false, options: [] },
            ] },
        )
        expect(body).not.toHaveProperty("reputation")
        expect(body.religion_id).toBeNull()
        expect(body.government_form).toBe("Council")
    })

    it("sends the religion id for a religious organization", () => {
        const body = toOrganizationBody(
            { ...filled, kind: "religious_organization", religion: { id: "r1", label: "Faith" } },
            religious,
        )
        expect(body.religion_id).toBe("r1")
    })
})

describe("form state", () => {
    const view: OrganizationAuthoringView = {
        organization_id: "o1",
        name: "Forge",
        summary: null,
        kind: { code: "business", label: "Business" },
        organization_type: "business",
        public_description: "Known",
        internal_description: "Secret",
        parent: { entity_id: "p1", name: "Crown", canon_status: "draft", lifecycle_status: "active" },
        headquarters: null,
        religion: null,
        typed: { business_type: "Smithy", operating_status: "operating", reputation: -20 },
        canon_status: "draft",
        lifecycle_status: "active",
        row_version: 2,
        available_actions: ["update"],
        blocked_actions: [],
        field_locks: [],
    }

    it("maps a view to string-valued form state", () => {
        const values = valuesFromOrganizationView(view)
        expect(values.typed).toEqual({ business_type: "Smithy", operating_status: "operating", reputation: "-20" })
        expect(values.parent).toEqual({ id: "p1", label: "Crown", detail: "Draft" })
        expect(values.internalDescription).toBe("Secret")
    })

    it("compares values structurally, ignoring whitespace", () => {
        const base = valuesFromOrganizationView(view)
        expect(sameOrganizationValues(base, { ...base, name: " Forge " })).toBe(true)
        expect(sameOrganizationValues(base, { ...base, typed: { ...base.typed, reputation: "10" } })).toBe(false)
        expect(sameOrganizationValues(base, { ...base, parent: null })).toBe(false)
    })
})
