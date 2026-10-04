import { createLocation, locationOptionsPath } from "../api/locationAuthoring"
import { ContentCreatePage } from "../components/authoring/ContentCreatePage"
import type { ContentCreateConfig } from "../components/authoring/ContentCreatePage"
import { LocationFields } from "../components/authoring/LocationFields"
import type {
    CreateLocationBody,
    LocationAuthoringView,
    LocationOptions,
} from "../types/locationAuthoring"
import {
    EMPTY_LOCATION_FORM,
    sameValues,
    toFieldsBody,
    validateLocationForm,
} from "../utils/locationForm"
import type { LocationFormValues } from "../utils/locationForm"

const config: ContentCreateConfig<
    LocationOptions,
    LocationFormValues,
    CreateLocationBody,
    LocationAuthoringView
> = {
    noun: "location",
    heading: "New location",
    lead: "A new location is saved as a draft. Only people who can edit canon see it until it is published.",
    breadcrumbLabel: "World",
    worldPath: (campaignId) => `/app/${encodeURIComponent(campaignId)}/world`,
    optionsPath: locationOptionsPath,
    canCreate: (options) => options.can_create,
    initialValues: () => EMPTY_LOCATION_FORM,
    isDirty: (values, initial) => !sameValues(values, initial),
    validate: (values, options) =>
        validateLocationForm(
            values,
            options.categories.find((c) => c.code === values.category),
            { requireCategory: true },
        ),
    toBody: (values, options) => ({
        category: values.category,
        ...toFieldsBody(
            values,
            options.categories.find((c) => c.code === values.category),
        ),
    }),
    create: createLocation,
    resultPath: (campaignId, created) =>
        `/app/${encodeURIComponent(campaignId)}/world/location/${encodeURIComponent(created.location_id)}`,
    announce: "Location created as a draft",
    saveLabel: "Create location",
    pendingLabel: "Creating…",
    renderFields: ({ campaignId, options, values, setValues, errorFor }) => (
        <LocationFields
            campaignId={campaignId}
            locationId={null}
            categories={options.categories}
            values={values}
            onChange={setValues}
            errorFor={errorFor}
        />
    ),
}

// Create a Location draft: /app/:campaignId/world/location/new. The category
// catalog and the create permission come from the server; this page offers
// nothing the options read did not.
export function CreateLocationPage() {
    return <ContentCreatePage config={config} />
}
