import { Link, useParams } from "react-router"
import { createItem, itemAuthoringPath, itemOptionsPath, itemsPath, updateItem } from "../api/items"
import { ContentCreatePage } from "../components/authoring/ContentCreatePage"
import type { ContentCreateConfig } from "../components/authoring/ContentCreatePage"
import { ContentEditPage } from "../components/authoring/ContentEditPage"
import type { ContentEditConfig } from "../components/authoring/ContentEditPage"
import type { FieldError } from "../components/authoring/feedback"
import { SelectField, TextAreaField, TextField } from "../components/authoring/fields"
import { LifecycleBadge } from "../components/authoring/feedback"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import type { CreateItemBody, ItemList, ItemOptions, ItemView, UpdateItemBody } from "../types/items"
import { validateName } from "../utils/authoringValidation"
import "../components/authoring/authoring.css"

const itemsListPath = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}/items`
const worldItemPath = (campaignId: string, itemId: string): string =>
    `/app/${encodeURIComponent(campaignId)}/world/item/${encodeURIComponent(itemId)}`

interface ItemFormValues {
    name: string
    summary: string
    definition: string
    notes: string
}

const EMPTY: ItemFormValues = { name: "", summary: "", definition: "", notes: "" }

const FIELD = {
    name: "item-name",
    summary: "item-summary",
    definition: "item-definition",
    notes: "item-notes",
} as const

const same = (a: ItemFormValues, b: ItemFormValues): boolean =>
    a.name.trim() === b.name.trim() &&
    a.summary.trim() === b.summary.trim() &&
    a.definition === b.definition &&
    a.notes.trim() === b.notes.trim()

function validate(values: ItemFormValues, options: ItemOptions, creating: boolean): FieldError[] {
    const errors: FieldError[] = []
    const nameError = validateName(values.name)
    if (nameError) errors.push({ fieldId: FIELD.name, message: nameError })
    if (values.summary.trim().length > options.limits.summary_max_length) {
        errors.push({
            fieldId: FIELD.summary,
            message: `Summary must be ${options.limits.summary_max_length} characters or fewer.`,
        })
    }
    if (creating && values.definition === "") {
        errors.push({ fieldId: FIELD.definition, message: "Choose the kind of item this is." })
    }
    if (values.notes.trim().length > options.limits.origin_notes_max_length) {
        errors.push({
            fieldId: FIELD.notes,
            message: `Origin notes must be ${options.limits.origin_notes_max_length} characters or fewer.`,
        })
    }
    return errors
}

const nullable = (value: string): string | null => (value.trim() === "" ? null : value.trim())

function Fields({
    values,
    setValues,
    errorFor,
    options,
    definitionName,
}: {
    values: ItemFormValues
    setValues: (values: ItemFormValues) => void
    errorFor: (fieldId: string) => string | null
    options: ItemOptions
    // Set when editing: the definition is fixed, so it is shown rather than chosen.
    definitionName: string | null
}) {
    return (
        <>
            <TextField
                id={FIELD.name}
                label="Name"
                hint="This particular object, such as “Aldric's sword”."
                value={values.name}
                onChange={(name) => setValues({ ...values, name })}
                required
                maxLength={options.limits.name_max_length}
                error={errorFor(FIELD.name)}
            />
            {definitionName === null ? (
                <SelectField
                    id={FIELD.definition}
                    label="Kind of item"
                    hint="Only published definitions can be used. A homebrew definition is made on the Item definitions page."
                    required
                    value={values.definition}
                    placeholder="Choose a kind of item"
                    options={options.definitions}
                    onChange={(definition) => setValues({ ...values, definition })}
                    error={errorFor(FIELD.definition)}
                />
            ) : (
                <p>
                    Kind of item: <strong>{definitionName}</strong> (fixed once created)
                </p>
            )}
            <TextAreaField
                id={FIELD.summary}
                label="Summary"
                value={values.summary}
                onChange={(summary) => setValues({ ...values, summary })}
                maxLength={options.limits.summary_max_length}
                error={errorFor(FIELD.summary)}
            />
            <TextAreaField
                id={FIELD.notes}
                label="Origin notes"
                hint="Where it came from. Visible to people who can see the item."
                value={values.notes}
                onChange={(notes) => setValues({ ...values, notes })}
                maxLength={options.limits.origin_notes_max_length}
                error={errorFor(FIELD.notes)}
            />
        </>
    )
}

const createConfig: ContentCreateConfig<ItemOptions, ItemFormValues, CreateItemBody, ItemView> = {
    noun: "item",
    heading: "New item",
    lead: "A new item is saved as a draft. It cannot be awarded or moved until it is published.",
    breadcrumbLabel: "Items",
    worldPath: itemsListPath,
    optionsPath: itemOptionsPath,
    canCreate: (options) => options.can_create,
    initialValues: () => EMPTY,
    isDirty: (values, initial) => !same(values, initial),
    validate: (values, options) => validate(values, options, true),
    toBody: (values) => ({
        name: values.name.trim(),
        summary: nullable(values.summary),
        item_definition_id: values.definition,
        origin_notes: nullable(values.notes),
    }),
    create: createItem,
    resultPath: (campaignId, created) => worldItemPath(campaignId, created.item_instance_id),
    announce: "Item created as a draft",
    saveLabel: "Create item",
    pendingLabel: "Creating…",
    renderFields: ({ values, setValues, errorFor, options }) => (
        <Fields
            values={values}
            setValues={setValues}
            errorFor={errorFor}
            options={options}
            definitionName={null}
        />
    ),
}

// /app/:campaignId/items/new
export function CreateItemPage() {
    return <ContentCreatePage config={createConfig} />
}

type ItemEditBody = Omit<UpdateItemBody, "expected_row_version" | "change_note">

const editConfig: ContentEditConfig<ItemView, ItemOptions, ItemFormValues, ItemEditBody> = {
    noun: "item",
    heading: "Edit item",
    entityParam: "itemId",
    breadcrumbLabel: "Items",
    worldPath: itemsListPath,
    detailPath: worldItemPath,
    viewPath: itemAuthoringPath,
    optionsPath: itemOptionsPath,
    name: (view) => view.name,
    valuesFromView: (view) => ({
        name: view.name,
        summary: view.summary ?? "",
        definition: view.item_definition_id,
        notes: view.origin_notes ?? "",
    }),
    same,
    validate: (values, _view, options) => validate(values, options, false),
    toBody: (values) => ({
        name: values.name.trim(),
        summary: nullable(values.summary),
        origin_notes: nullable(values.notes),
    }),
    update: (campaignId, itemId, body, ctx) => updateItem(campaignId, itemId, body, ctx),
    renderFields: ({ values, setValues, errorFor, options, view }) => (
        <Fields
            values={values}
            setValues={setValues}
            errorFor={errorFor}
            options={options}
            definitionName={view.definition_name}
        />
    ),
    summarize: (values) => (
        <dl className="authoring-fact-list">
            <dt>Name</dt>
            <dd>{values.name}</dd>
            <dt>Summary</dt>
            <dd>{values.summary || "(empty)"}</dd>
            <dt>Origin notes</dt>
            <dd>{values.notes || "(empty)"}</dd>
        </dl>
    ),
    canonWarning:
        "This item is published. People with access will see the change. Where it is and what condition it is in are changed by running the item, not by editing it.",
    saved: "Item saved",
}

// /app/:campaignId/items/:itemId/edit
export function EditItemPage() {
    return <ContentEditPage config={editConfig} />
}

// /app/:campaignId/items: every item instance of the world, for editors.
export function ItemsPage() {
    const { campaignId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const list = useAuthoringResource<ItemList>(itemsPath(campaignId))
    const headingRef = usePageArrival(list.state.kind === "ready")
    return (
        <section className="authoring-page" aria-labelledby="items-heading">
            <h1 id="items-heading" ref={headingRef} tabIndex={-1}>
                Items
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to manage items.</p>
            ) : list.state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : list.state.kind !== "ready" ? (
                <p role="alert">Items could not be loaded.</p>
            ) : (
                <>
                    <p>
                        <Link className="authoring-button" to={`${itemsListPath(campaignId)}/new`}>
                            New item
                        </Link>{" "}
                        <Link to={`${itemsListPath(campaignId).replace(/items$/, "item-definitions")}`}>
                            Item definitions
                        </Link>
                    </p>
                    {list.state.data.items.length === 0 ? (
                        <p>No items yet.</p>
                    ) : (
                        <ul className="authoring-choice-list">
                            {list.state.data.items.map((item) => (
                                <li key={item.item_instance_id}>
                                    <Link to={worldItemPath(campaignId, item.item_instance_id)}>{item.name}</Link>{" "}
                                    ({item.definition_name})
                                    {item.holder_name !== null ? `, carried by ${item.holder_name}` : ""}
                                    {item.is_destroyed ? ", destroyed" : ""}{" "}
                                    <LifecycleBadge
                                        status={
                                            item.lifecycle_status === "archived"
                                                ? "archived"
                                                : item.canon_status
                                        }
                                    />
                                </li>
                            ))}
                        </ul>
                    )}
                </>
            )}
        </section>
    )
}
