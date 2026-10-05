import { fetchLocationParentOptions } from "../../api/locationAuthoring"
import {
    fetchOrganizationParentOptions,
    fetchReligionReferenceOptions,
} from "../../api/organizationAuthoring"
import type { OrganizationKindOption } from "../../types/organizationAuthoring"
import { DESCRIPTION_MAX, NAME_MAX } from "../../utils/authoringValidation"
import { statusDetail } from "../../utils/locationForm"
import { ORG_FIELD_IDS, typedFieldId } from "../../utils/organizationForm"
import type { OrganizationFormValues } from "../../utils/organizationForm"
import { SelectField, TextAreaField, TextField } from "./fields"
import { ReferenceCombobox } from "./ReferenceCombobox"
import type { ReferenceOption } from "./ReferenceCombobox"

interface OrganizationFieldsProps {
    campaignId: string
    // Present when editing: the organization is excluded from its own parent
    // options (with its descendants) and its kind is fixed.
    organizationId: string | null
    kinds: readonly OrganizationKindOption[]
    values: OrganizationFormValues
    onChange: (values: OrganizationFormValues) => void
    errorFor: (fieldId: string) => string | null
}

// The typed Organization fields. The kind-specific section is rendered from the
// server's catalog descriptors, never hard-coded per kind.
export function OrganizationFields({
    campaignId,
    organizationId,
    kinds,
    values,
    onChange,
    errorFor,
}: OrganizationFieldsProps) {
    const kind = kinds.find((k) => k.code === values.kind)
    const editing = organizationId !== null

    async function searchParents(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchOrganizationParentOptions(campaignId, query, organizationId, signal)
        return page.items.map((item) => ({
            id: item.organization_id,
            label: item.name,
            detail: statusDetail(item.canon_status, "active"),
        }))
    }

    async function searchHeadquarters(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchLocationParentOptions(campaignId, query, null, signal)
        return page.items.map((item) => ({
            id: item.location_id,
            label: item.name,
            detail: `${item.category.label}, ${statusDetail(item.canon_status, "active")}`,
        }))
    }

    async function searchReligions(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchReligionReferenceOptions(campaignId, query, signal)
        return page.items.map((item) => ({
            id: item.religion_id,
            label: item.name,
            detail: statusDetail(item.canon_status, "active"),
        }))
    }

    function setTyped(name: string, value: string) {
        onChange({ ...values, typed: { ...values.typed, [name]: value } })
    }

    return (
        <>
            {editing ? (
                <div className="authoring-field">
                    <span className="authoring-field__label">Kind</span>
                    <p id={ORG_FIELD_IDS.kind}>{kind?.label ?? values.kind}</p>
                    <p className="authoring-field__hint">
                        An organization&apos;s kind cannot change. To change it, create a replacement
                        and supersede this one.
                    </p>
                </div>
            ) : (
                <SelectField
                    id={ORG_FIELD_IDS.kind}
                    label="Kind"
                    value={values.kind}
                    placeholder="Choose a kind"
                    required
                    options={kinds.map((k) => ({ value: k.code, label: k.label }))}
                    error={errorFor(ORG_FIELD_IDS.kind)}
                    onChange={(next) => onChange({ ...values, kind: next, typed: {}, religion: null })}
                />
            )}
            <TextField
                id={ORG_FIELD_IDS.name}
                label="Name"
                value={values.name}
                onChange={(name) => onChange({ ...values, name })}
                required
                maxLength={NAME_MAX}
                error={errorFor(ORG_FIELD_IDS.name)}
            />
            <TextAreaField
                id={ORG_FIELD_IDS.summary}
                label="Summary"
                value={values.summary}
                onChange={(summary) => onChange({ ...values, summary })}
                maxLength={DESCRIPTION_MAX}
                error={errorFor(ORG_FIELD_IDS.summary)}
            />
            <TextAreaField
                id={ORG_FIELD_IDS.publicDescription}
                label="Public description"
                hint="What anyone who can see this organization may read."
                value={values.publicDescription}
                onChange={(publicDescription) => onChange({ ...values, publicDescription })}
                maxLength={DESCRIPTION_MAX}
                error={errorFor(ORG_FIELD_IDS.publicDescription)}
            />
            <TextAreaField
                id={ORG_FIELD_IDS.internalDescription}
                label="GM notes"
                hint="Visible only to people who can edit canon. Never shown to players."
                value={values.internalDescription}
                onChange={(internalDescription) => onChange({ ...values, internalDescription })}
                maxLength={DESCRIPTION_MAX}
                error={errorFor(ORG_FIELD_IDS.internalDescription)}
            />
            {(kind?.fields ?? []).map((descriptor) => {
                const id = typedFieldId(descriptor.name)
                const value = values.typed[descriptor.name] ?? ""
                if (descriptor.kind === "select") {
                    return (
                        <SelectField
                            key={descriptor.name}
                            id={id}
                            label={descriptor.label}
                            value={value}
                            required={descriptor.required}
                            placeholder={descriptor.required ? "Choose one" : "Not set"}
                            options={descriptor.options}
                            error={errorFor(id)}
                            onChange={(next) => setTyped(descriptor.name, next)}
                        />
                    )
                }
                if (descriptor.kind === "longtext") {
                    return (
                        <TextAreaField
                            key={descriptor.name}
                            id={id}
                            label={descriptor.label}
                            value={value}
                            maxLength={descriptor.max_length ?? undefined}
                            error={errorFor(id)}
                            onChange={(next) => setTyped(descriptor.name, next)}
                        />
                    )
                }
                return (
                    <TextField
                        key={descriptor.name}
                        id={id}
                        label={descriptor.label}
                        value={value}
                        hint={
                            descriptor.kind === "integer"
                                ? `A whole number from ${descriptor.minimum} to ${descriptor.maximum}. Leave empty if unknown.`
                                : undefined
                        }
                        maxLength={descriptor.kind === "text" ? (descriptor.max_length ?? undefined) : undefined}
                        error={errorFor(id)}
                        onChange={(next) => setTyped(descriptor.name, next)}
                    />
                )
            })}
            {kind?.needs_religion ? (
                <ReferenceCombobox
                    id={ORG_FIELD_IDS.religion}
                    label="Religion"
                    hint="The belief system this organization serves."
                    value={values.religion}
                    onChange={(religion) => onChange({ ...values, religion })}
                    search={searchReligions}
                    error={errorFor(ORG_FIELD_IDS.religion)}
                    placeholder="Search religions"
                />
            ) : null}
            <ReferenceCombobox
                id={ORG_FIELD_IDS.parent}
                label="Part of"
                hint="The larger organization this one belongs to. Leave empty for a top-level organization."
                value={values.parent}
                onChange={(parent) => onChange({ ...values, parent })}
                search={searchParents}
                error={errorFor(ORG_FIELD_IDS.parent)}
                placeholder="Search organizations"
            />
            <ReferenceCombobox
                id={ORG_FIELD_IDS.headquarters}
                label="Headquarters"
                hint="Where this organization is based."
                value={values.headquarters}
                onChange={(headquarters) => onChange({ ...values, headquarters })}
                search={searchHeadquarters}
                error={errorFor(ORG_FIELD_IDS.headquarters)}
                placeholder="Search locations"
            />
        </>
    )
}
