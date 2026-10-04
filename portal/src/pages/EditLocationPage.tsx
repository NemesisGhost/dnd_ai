import {
    locationAuthoringPath,
    locationOptionsPath,
    updateLocation,
} from "../api/locationAuthoring"
import { ContentEditPage } from "../components/authoring/ContentEditPage"
import type { ContentEditConfig } from "../components/authoring/ContentEditPage"
import { LocationFields } from "../components/authoring/LocationFields"
import type {
    LocationAuthoringView,
    LocationOptions,
    UpdateLocationBody,
} from "../types/locationAuthoring"
import {
    sameValues,
    toFieldsBody,
    validateLocationForm,
    valuesFromView,
} from "../utils/locationForm"
import type { LocationFormValues } from "../utils/locationForm"

type EditBody = Omit<UpdateLocationBody, "expected_row_version" | "change_note">

const config: ContentEditConfig<
    LocationAuthoringView,
    LocationOptions,
    LocationFormValues,
    EditBody
> = {
    noun: "location",
    heading: "Edit location",
    entityParam: "entityId",
    breadcrumbLabel: "World",
    worldPath: (campaignId) => `/app/${encodeURIComponent(campaignId)}/world`,
    detailPath: (campaignId, id) =>
        `/app/${encodeURIComponent(campaignId)}/world/location/${encodeURIComponent(id)}`,
    viewPath: locationAuthoringPath,
    optionsPath: locationOptionsPath,
    name: (view) => view.name,
    valuesFromView,
    same: sameValues,
    validate: (values, view, options) =>
        validateLocationForm(
            values,
            options.categories.find((c) => c.code === view.category.code),
            { requireCategory: false },
        ),
    toBody: (values, view, options) =>
        toFieldsBody(
            values,
            options.categories.find((c) => c.code === view.category.code),
        ),
    update: updateLocation,
    renderFields: ({ campaignId, entityId, options, values, setValues, errorFor }) => (
        <LocationFields
            campaignId={campaignId}
            locationId={entityId}
            categories={options.categories}
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
            <dt>Contained in</dt>
            <dd>{values.parent?.label ?? "(none)"}</dd>
            {values.population !== "" ? (
                <>
                    <dt>Population</dt>
                    <dd>{values.population}</dd>
                </>
            ) : null}
            {values.buildingUse !== "" ? (
                <>
                    <dt>Use</dt>
                    <dd>{values.buildingUse}</dd>
                </>
            ) : null}
        </dl>
    ),
    canonWarning:
        "This location is published. People with access will see the change. For a change in meaning, create a replacement and supersede this location instead.",
    saved: "Location saved",
}

// Edit a Location definition: /app/:campaignId/world/location/:entityId/edit.
export function EditLocationPage() {
    return <ContentEditPage config={config} />
}
