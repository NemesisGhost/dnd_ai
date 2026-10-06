import { useParams } from "react-router"
import { fetchLocationParentOptions } from "../api/locationAuthoring"
import {
    areaAuthoringPath,
    createDungeon,
    dungeonAuthoringPath,
    dungeonOptionsPath,
    updateArea,
    updateDungeon,
} from "../api/dungeonAuthoring"
import { EntityLifecyclePanel } from "../components/EntityLifecyclePanel"
import { AreaContent } from "../components/authoring/AreaContent"
import { ContentCreatePage } from "../components/authoring/ContentCreatePage"
import type { ContentCreateConfig } from "../components/authoring/ContentCreatePage"
import { ContentEditPage } from "../components/authoring/ContentEditPage"
import type { ContentEditConfig } from "../components/authoring/ContentEditPage"
import { DungeonStructure } from "../components/authoring/DungeonStructure"
import type { FieldError } from "../components/authoring/feedback"
import { SelectField, TextAreaField, TextField } from "../components/authoring/fields"
import { ReferenceCombobox } from "../components/authoring/ReferenceCombobox"
import type { ReferenceOption } from "../components/authoring/ReferenceCombobox"
import type {
    AreaAuthoringView,
    AreaFieldsBody,
    DungeonAuthoringView,
    DungeonFieldsBody,
    DungeonOptions,
} from "../types/dungeonAuthoring"
import { statusDetail } from "../utils/locationForm"

const root = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`
const worldPath = (campaignId: string): string => `${root(campaignId)}/world`
const locationDetail = (campaignId: string, id: string): string =>
    `${root(campaignId)}/world/location/${encodeURIComponent(id)}`

// --- the dungeon ---------------------------------------------------------------------------------

interface DungeonValues {
    name: string
    summary: string
    danger: string
    parent: ReferenceOption | null
}

const EMPTY_DUNGEON: DungeonValues = { name: "", summary: "", danger: "", parent: null }

const DUNGEON_FIELD = {
    name: "dungeon-name",
    summary: "dungeon-summary",
    danger: "dungeon-danger",
    parent: "dungeon-parent",
} as const

function sameDungeon(a: DungeonValues, b: DungeonValues): boolean {
    return (
        a.name.trim() === b.name.trim() &&
        a.summary.trim() === b.summary.trim() &&
        a.danger === b.danger &&
        (a.parent?.id ?? null) === (b.parent?.id ?? null)
    )
}

function validateDungeon(values: DungeonValues, options: DungeonOptions): FieldError[] {
    const errors: FieldError[] = []
    const name = values.name.trim()
    if (name === "") errors.push({ fieldId: DUNGEON_FIELD.name, message: "Name is required." })
    else if (name.length > options.limits.name_max_length) {
        errors.push({
            fieldId: DUNGEON_FIELD.name,
            message: `Name must be ${options.limits.name_max_length} characters or fewer.`,
        })
    }
    if (values.summary.trim().length > options.limits.summary_max_length) {
        errors.push({
            fieldId: DUNGEON_FIELD.summary,
            message: `Summary must be ${options.limits.summary_max_length} characters or fewer.`,
        })
    }
    return errors
}

function dungeonBody(values: DungeonValues): DungeonFieldsBody {
    return {
        name: values.name.trim(),
        summary: values.summary.trim() === "" ? null : values.summary.trim(),
        danger_level: values.danger === "" ? null : Number(values.danger),
        parent_location_id: values.parent?.id ?? null,
    }
}

function dungeonValues(view: DungeonAuthoringView): DungeonValues {
    return {
        name: view.name,
        summary: view.summary ?? "",
        danger: view.danger_level === null ? "" : String(view.danger_level),
        parent:
            view.parent === null
                ? null
                : {
                      id: view.parent.entity_id,
                      label: view.parent.name,
                      detail: statusDetail(view.parent.canon_status, view.parent.lifecycle_status),
                  },
    }
}

function DungeonFields({
    campaignId,
    options,
    values,
    setValues,
    errorFor,
}: {
    campaignId: string
    options: DungeonOptions
    values: DungeonValues
    setValues: (values: DungeonValues) => void
    errorFor: (fieldId: string) => string | null
}) {
    async function searchParents(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchLocationParentOptions(campaignId, query, null, signal)
        return page.items.map((item) => ({
            id: item.location_id,
            label: item.name,
            detail: `${item.category.label}, ${statusDetail(item.canon_status, "active")}`,
        }))
    }
    const ratings = Array.from(
        { length: options.limits.rating_max - options.limits.rating_min + 1 },
        (_, i) => String(options.limits.rating_min + i),
    ).map((value) => ({ value, label: value }))
    return (
        <>
            <TextField
                id={DUNGEON_FIELD.name}
                label="Name"
                value={values.name}
                onChange={(name) => setValues({ ...values, name })}
                required
                maxLength={options.limits.name_max_length}
                error={errorFor(DUNGEON_FIELD.name)}
            />
            <TextAreaField
                id={DUNGEON_FIELD.summary}
                label="Summary"
                value={values.summary}
                onChange={(summary) => setValues({ ...values, summary })}
                maxLength={options.limits.summary_max_length}
                error={errorFor(DUNGEON_FIELD.summary)}
            />
            <SelectField
                id={DUNGEON_FIELD.danger}
                label="Danger level"
                hint="Optional, from 1 (safe) to 10 (deadly). Only editors see it."
                value={values.danger}
                placeholder="Not rated"
                options={ratings}
                onChange={(danger) => setValues({ ...values, danger })}
            />
            <ReferenceCombobox
                id={DUNGEON_FIELD.parent}
                label="Located in"
                hint="The place this dungeon lies within. Optional."
                value={values.parent}
                onChange={(parent) => setValues({ ...values, parent })}
                search={searchParents}
                error={errorFor(DUNGEON_FIELD.parent)}
                placeholder="Search locations"
            />
        </>
    )
}

const createDungeonConfig: ContentCreateConfig<
    DungeonOptions,
    DungeonValues,
    DungeonFieldsBody,
    DungeonAuthoringView
> = {
    noun: "dungeon",
    heading: "New dungeon",
    lead: "A new dungeon is saved as a draft. Add its areas, connections and contents on the next page; only people who can edit canon see it until it is published.",
    breadcrumbLabel: "World",
    worldPath,
    optionsPath: dungeonOptionsPath,
    canCreate: (options) => options.can_create,
    initialValues: () => EMPTY_DUNGEON,
    isDirty: (values, initial) => !sameDungeon(values, initial),
    validate: validateDungeon,
    toBody: (values) => dungeonBody(values),
    create: createDungeon,
    resultPath: (campaignId, created) =>
        `${root(campaignId)}/world/dungeon/${encodeURIComponent(created.dungeon_id)}/edit`,
    announce: "Dungeon created as a draft",
    saveLabel: "Create dungeon",
    pendingLabel: "Creating…",
    renderFields: ({ campaignId, options, values, setValues, errorFor }) => (
        <DungeonFields
            campaignId={campaignId}
            options={options}
            values={values}
            setValues={setValues}
            errorFor={errorFor}
        />
    ),
}

// Create a dungeon draft: /app/:campaignId/world/dungeon/new.
export function CreateDungeonPage() {
    return <ContentCreatePage config={createDungeonConfig} />
}

const editDungeonConfig: ContentEditConfig<
    DungeonAuthoringView,
    DungeonOptions,
    DungeonValues,
    DungeonFieldsBody
> = {
    noun: "dungeon",
    heading: "Edit dungeon",
    entityParam: "dungeonId",
    breadcrumbLabel: "World",
    worldPath,
    detailPath: locationDetail,
    viewPath: dungeonAuthoringPath,
    optionsPath: dungeonOptionsPath,
    name: (view) => view.name,
    valuesFromView: dungeonValues,
    same: sameDungeon,
    validate: (values, _view, options) => validateDungeon(values, options),
    toBody: (values) => dungeonBody(values),
    update: updateDungeon,
    renderFields: ({ campaignId, options, values, setValues, errorFor }) => (
        <DungeonFields
            campaignId={campaignId}
            options={options}
            values={values}
            setValues={setValues}
            errorFor={errorFor}
        />
    ),
    summarize: (values) => (
        <dl className="authoring-fact-list">
            <dt>Name</dt>
            <dd>{values.name || "(empty)"}</dd>
            <dt>Summary</dt>
            <dd>{values.summary || "(empty)"}</dd>
            <dt>Danger level</dt>
            <dd>{values.danger || "(not rated)"}</dd>
            <dt>Located in</dt>
            <dd>{values.parent?.label ?? "(none)"}</dd>
        </dl>
    ),
    canonWarning:
        "This dungeon is published. People with access will see the change. For a change in meaning, create a replacement instead.",
    saved: "Dungeon saved",
    renderExtra: ({ campaignId, entityId, view, options, refetch }) => (
        <>
            <DungeonStructure campaignId={campaignId} view={view} options={options} refetch={refetch} />
            <EntityLifecyclePanel
                campaignId={campaignId}
                entityId={entityId}
                onChanged={() => void refetch()}
            />
        </>
    ),
}

// Edit a dungeon with its areas and connections: /app/:campaignId/world/dungeon/:dungeonId/edit.
export function EditDungeonPage() {
    return <ContentEditPage config={editDungeonConfig} />
}

// --- an area -------------------------------------------------------------------------------------

interface AreaValues {
    name: string
    summary: string
    areaType: string
    dimensions: string
    environment: string
}

const AREA_FIELD = {
    name: "area-name",
    summary: "area-summary",
    type: "area-type",
    dimensions: "area-dimensions",
    environment: "area-environment",
} as const

function sameArea(a: AreaValues, b: AreaValues): boolean {
    return (
        a.name.trim() === b.name.trim() &&
        a.summary.trim() === b.summary.trim() &&
        a.areaType.trim() === b.areaType.trim() &&
        a.dimensions.trim() === b.dimensions.trim() &&
        a.environment.trim() === b.environment.trim()
    )
}

function validateArea(values: AreaValues, _view: AreaAuthoringView, options: DungeonOptions): FieldError[] {
    const errors: FieldError[] = []
    const name = values.name.trim()
    if (name === "") errors.push({ fieldId: AREA_FIELD.name, message: "Name is required." })
    else if (name.length > options.limits.name_max_length) {
        errors.push({
            fieldId: AREA_FIELD.name,
            message: `Name must be ${options.limits.name_max_length} characters or fewer.`,
        })
    }
    return errors
}

const nullable = (value: string): string | null => (value.trim() === "" ? null : value.trim())

function areaBody(values: AreaValues): AreaFieldsBody {
    return {
        name: values.name.trim(),
        summary: nullable(values.summary),
        area_type: nullable(values.areaType),
        dimensions: nullable(values.dimensions),
        environmental_properties: nullable(values.environment),
    }
}

function areaValues(view: AreaAuthoringView): AreaValues {
    return {
        name: view.name,
        summary: view.summary ?? "",
        areaType: view.area_type ?? "",
        dimensions: view.dimensions ?? "",
        environment: view.environmental_properties ?? "",
    }
}

const editAreaConfig: ContentEditConfig<AreaAuthoringView, DungeonOptions, AreaValues, AreaFieldsBody> = {
    noun: "area",
    heading: "Edit area",
    entityParam: "areaId",
    breadcrumbLabel: "World",
    worldPath,
    detailPath: locationDetail,
    viewPath: areaAuthoringPath,
    optionsPath: dungeonOptionsPath,
    name: (view) => view.name,
    valuesFromView: areaValues,
    same: sameArea,
    validate: validateArea,
    toBody: (values) => areaBody(values),
    update: updateArea,
    renderFields: ({ options, values, setValues, errorFor }) => (
        <>
            <TextField
                id={AREA_FIELD.name}
                label="Name"
                value={values.name}
                onChange={(name) => setValues({ ...values, name })}
                required
                maxLength={options.limits.name_max_length}
                error={errorFor(AREA_FIELD.name)}
            />
            <TextAreaField
                id={AREA_FIELD.summary}
                label="Summary"
                value={values.summary}
                onChange={(summary) => setValues({ ...values, summary })}
                maxLength={options.limits.summary_max_length}
            />
            <TextField
                id={AREA_FIELD.type}
                label="Kind of area"
                value={values.areaType}
                onChange={(areaType) => setValues({ ...values, areaType })}
                maxLength={options.limits.short_text_max_length}
            />
            <TextField
                id={AREA_FIELD.dimensions}
                label="Size"
                hint="For example 30 ft by 40 ft."
                value={values.dimensions}
                onChange={(dimensions) => setValues({ ...values, dimensions })}
                maxLength={options.limits.short_text_max_length}
            />
            <TextAreaField
                id={AREA_FIELD.environment}
                label="Environment"
                value={values.environment}
                onChange={(environment) => setValues({ ...values, environment })}
                maxLength={options.limits.notes_max_length}
            />
        </>
    ),
    summarize: (values) => (
        <dl className="authoring-fact-list">
            <dt>Name</dt>
            <dd>{values.name || "(empty)"}</dd>
            <dt>Summary</dt>
            <dd>{values.summary || "(empty)"}</dd>
            <dt>Kind</dt>
            <dd>{values.areaType || "(none)"}</dd>
            <dt>Size</dt>
            <dd>{values.dimensions || "(none)"}</dd>
            <dt>Environment</dt>
            <dd>{values.environment || "(none)"}</dd>
        </dl>
    ),
    canonWarning:
        "This area is published. People with access will see the change. For a change in meaning, create a replacement instead.",
    saved: "Area saved",
    renderExtra: ({ campaignId, entityId, view, options, refetch }) => (
        <>
            <p>
                <a href={`${root(campaignId)}/world/dungeon/${encodeURIComponent(view.dungeon.entity_id)}/edit`}>
                    Back to {view.dungeon.name}
                </a>
            </p>
            <AreaContent campaignId={campaignId} view={view} options={options} refetch={refetch} />
            <EntityLifecyclePanel
                campaignId={campaignId}
                entityId={entityId}
                onChanged={() => void refetch()}
            />
        </>
    ),
}

// Edit an area, its contents and its current state:
// /app/:campaignId/world/dungeon/:dungeonId/areas/:areaId/edit.
export function EditDungeonAreaPage() {
    const { areaId = "" } = useParams()
    return <ContentEditPage key={areaId} config={editAreaConfig} />
}
