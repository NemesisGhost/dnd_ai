import {
    createOrganization,
    organizationAuthoringPath,
    organizationOptionsPath,
    updateOrganization,
} from "../api/organizationAuthoring"
import { ContentCreatePage } from "../components/authoring/ContentCreatePage"
import type { ContentCreateConfig } from "../components/authoring/ContentCreatePage"
import { ContentEditPage } from "../components/authoring/ContentEditPage"
import type { ContentEditConfig } from "../components/authoring/ContentEditPage"
import { OrganizationFields } from "../components/authoring/OrganizationFields"
import type {
    CreateOrganizationBody,
    OrganizationAuthoringView,
    OrganizationFieldsBody,
    OrganizationKindOption,
    OrganizationOptions,
} from "../types/organizationAuthoring"
import {
    EMPTY_ORGANIZATION_FORM,
    sameOrganizationValues,
    toOrganizationBody,
    validateOrganizationForm,
    valuesFromOrganizationView,
} from "../utils/organizationForm"
import type { OrganizationFormValues } from "../utils/organizationForm"

const worldPath = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}/world`

const kindOf = (
    options: OrganizationOptions,
    code: string,
): OrganizationKindOption | undefined => options.kinds.find((k) => k.code === code)

const createConfig: ContentCreateConfig<
    OrganizationOptions,
    OrganizationFormValues,
    CreateOrganizationBody,
    OrganizationAuthoringView
> = {
    noun: "organization",
    heading: "New organization",
    lead: "A new organization is saved as a draft. Only people who can edit canon see it until it is published.",
    breadcrumbLabel: "World",
    worldPath,
    optionsPath: organizationOptionsPath,
    canCreate: (options) => options.can_create,
    initialValues: () => EMPTY_ORGANIZATION_FORM,
    isDirty: (values, initial) => !sameOrganizationValues(values, initial),
    validate: (values, options) =>
        validateOrganizationForm(values, kindOf(options, values.kind), { requireKind: true }),
    toBody: (values, options) => ({
        kind: values.kind,
        ...toOrganizationBody(values, kindOf(options, values.kind)),
    }),
    create: createOrganization,
    resultPath: (campaignId, created) =>
        `${worldPath(campaignId)}/organization/${encodeURIComponent(created.organization_id)}`,
    announce: "Organization created as a draft",
    saveLabel: "Create organization",
    pendingLabel: "Creating…",
    renderFields: ({ campaignId, options, values, setValues, errorFor }) => (
        <OrganizationFields
            campaignId={campaignId}
            organizationId={null}
            kinds={options.kinds}
            values={values}
            onChange={setValues}
            errorFor={errorFor}
        />
    ),
}

// Create an Organization draft: /app/:campaignId/world/organization/new.
export function CreateOrganizationPage() {
    return <ContentCreatePage config={createConfig} />
}

const editConfig: ContentEditConfig<
    OrganizationAuthoringView,
    OrganizationOptions,
    OrganizationFormValues,
    OrganizationFieldsBody
> = {
    noun: "organization",
    heading: "Edit organization",
    entityParam: "entityId",
    breadcrumbLabel: "World",
    worldPath,
    detailPath: (campaignId, id) => `${worldPath(campaignId)}/organization/${encodeURIComponent(id)}`,
    viewPath: organizationAuthoringPath,
    optionsPath: organizationOptionsPath,
    name: (view) => view.name,
    valuesFromView: valuesFromOrganizationView,
    same: sameOrganizationValues,
    validate: (values, view, options) =>
        validateOrganizationForm(values, kindOf(options, view.kind.code), { requireKind: false }),
    toBody: (values, view, options) => toOrganizationBody(values, kindOf(options, view.kind.code)),
    update: updateOrganization,
    renderFields: ({ campaignId, entityId, options, values, setValues, errorFor }) => (
        <OrganizationFields
            campaignId={campaignId}
            organizationId={entityId}
            kinds={options.kinds}
            values={values}
            onChange={setValues}
            errorFor={errorFor}
        />
    ),
    summarize: (values) => (
        <dl className="authoring-fact-list">
            <dt>Name</dt>
            <dd>{values.name}</dd>
            <dt>Summary</dt>
            <dd>{values.summary || "(empty)"}</dd>
            <dt>Public description</dt>
            <dd>{values.publicDescription || "(empty)"}</dd>
            <dt>GM notes</dt>
            <dd>{values.internalDescription || "(empty)"}</dd>
            <dt>Part of</dt>
            <dd>{values.parent?.label ?? "(none)"}</dd>
            <dt>Headquarters</dt>
            <dd>{values.headquarters?.label ?? "(none)"}</dd>
            {values.religion !== null ? (
                <>
                    <dt>Religion</dt>
                    <dd>{values.religion.label}</dd>
                </>
            ) : null}
            {Object.entries(values.typed)
                .filter(([, value]) => value !== "")
                .map(([key, value]) => (
                    <div key={key} style={{ display: "contents" }}>
                        <dt>{key.replace(/_/g, " ")}</dt>
                        <dd>{value}</dd>
                    </div>
                ))}
        </dl>
    ),
    canonWarning:
        "This organization is published. People with access will see the change. For a change in meaning, create a replacement and supersede this organization instead.",
    saved: "Organization saved",
}

// Edit an Organization definition: /app/:campaignId/world/organization/:entityId/edit.
export function EditOrganizationPage() {
    return <ContentEditPage config={editConfig} />
}
