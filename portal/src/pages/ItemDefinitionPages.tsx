import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import {
    createItemDefinition,
    itemDefinitionOptionsPath,
    itemDefinitionPath,
    itemDefinitionsPath,
    updateItemDefinition,
} from "../api/itemDefinitions"
import { useAnnounce } from "../components/authoring/announcer"
import { MutationStatusMessage, StaleWriteNotice } from "../components/authoring/feedback"
import { SelectField, TextAreaField, TextField } from "../components/authoring/fields"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import type {
    ItemDefinition,
    ItemDefinitionBody,
    ItemDefinitionList,
    ItemDefinitionOptions,
} from "../types/itemDefinitions"
import "../components/authoring/authoring.css"

const AMOUNT = /^\d+(\.\d{1,2})?$/

// An empty box is "not set"; anything else must be a non-negative amount with at most two decimals.
function parseAmount(value: string): number | null | undefined {
    const trimmed = value.trim()
    if (trimmed === "") return null
    return AMOUNT.test(trimmed) ? Number(trimmed) : undefined
}

const campaignBase = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}/item-definitions`

// /app/:campaignId/item-definitions — the generic definitions of the ruleset and this world's
// homebrew. Only homebrew can be edited.
export function ItemDefinitionsPage() {
    const { campaignId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const [category, setCategory] = useState("")
    const [homebrewOnly, setHomebrewOnly] = useState(false)
    const options = useAuthoringResource<ItemDefinitionOptions>(itemDefinitionOptionsPath(campaignId))
    const list = useAuthoringResource<ItemDefinitionList>(itemDefinitionsPath(campaignId))
    const headingRef = usePageArrival(list.state.kind === "ready")
    const items =
        list.state.kind === "ready"
            ? list.state.data.items.filter(
                  (item) => (category === "" || item.category === category) && (!homebrewOnly || item.is_homebrew),
              )
            : []
    return (
        <section className="authoring-page" aria-labelledby="item-definitions-heading">
            <h1 id="item-definitions-heading" ref={headingRef} tabIndex={-1}>
                Item definitions
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to edit item definitions.</p>
            ) : list.state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : list.state.kind !== "ready" ? (
                <p role="alert">Item definitions could not be loaded.</p>
            ) : (
                <>
                    <p className="authoring-note">
                        Generic definitions come with the ruleset and cannot be changed. Definitions you create
                        belong to this world only.
                    </p>
                    <p>
                        <Link className="authoring-button" to={`${campaignBase(campaignId)}/new`}>
                            New item definition
                        </Link>
                    </p>
                    <form noValidate aria-label="Filter item definitions" className="authoring-form">
                        <SelectField
                            id="item-filter-category"
                            label="Category"
                            value={category}
                            placeholder="All categories"
                            options={options.state.kind === "ready" ? options.state.data.categories : []}
                            onChange={setCategory}
                        />
                        <label>
                            <input
                                type="checkbox"
                                checked={homebrewOnly}
                                onChange={(event) => setHomebrewOnly(event.target.checked)}
                            />{" "}
                            Show only this world&apos;s definitions
                        </label>
                    </form>
                    {items.length === 0 ? (
                        <p>No item definitions match.</p>
                    ) : (
                        <ul className="authoring-choice-list">
                            {items.map((item) => (
                                <li key={item.item_definition_id}>
                                    {item.name} ({item.category_label}, {item.rarity.replace(/_/g, " ")})
                                    {item.canon_status !== "canon" ? " (draft)" : ""}
                                    {item.is_homebrew ? (
                                        <>
                                            {" "}
                                            <Link
                                                to={`${campaignBase(campaignId)}/${encodeURIComponent(item.item_definition_id)}`}
                                            >
                                                Edit {item.name}
                                            </Link>
                                        </>
                                    ) : (
                                        " (generic)"
                                    )}
                                </li>
                            ))}
                        </ul>
                    )}
                </>
            )}
        </section>
    )
}

// /app/:campaignId/item-definitions/new and /item-definitions/:definitionId
export function ItemDefinitionFormPage() {
    const { campaignId = "", definitionId } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const options = useAuthoringResource<ItemDefinitionOptions>(itemDefinitionOptionsPath(campaignId))
    const existing = useAuthoringResource<ItemDefinition>(
        definitionId === undefined ? null : itemDefinitionPath(campaignId, definitionId),
    )
    const ready =
        options.state.kind === "ready" && (definitionId === undefined || existing.state.kind === "ready")
    const headingRef = usePageArrival(ready)
    return (
        <section className="authoring-page" aria-labelledby="item-definition-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={campaignBase(campaignId)}>Item definitions</Link>
            </p>
            <h1 id="item-definition-heading" ref={headingRef} tabIndex={-1}>
                {definitionId === undefined ? "New item definition" : "Edit item definition"}
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to edit item definitions.</p>
            ) : options.state.kind === "loading" || (definitionId !== undefined && existing.state.kind === "loading") ? (
                <p role="status">Loading…</p>
            ) : options.state.kind !== "ready" ||
              (definitionId !== undefined && existing.state.kind !== "ready") ? (
                <p role="alert">This item definition does not exist, or you do not have access to it.</p>
            ) : definitionId !== undefined && existing.state.kind === "ready" && !existing.state.data.can_edit ? (
                <p>This is a generic definition from the ruleset and cannot be changed.</p>
            ) : (
                <DefinitionForm
                    key={existing.state.kind === "ready" ? existing.state.data.row_version : "new"}
                    campaignId={campaignId}
                    options={options.state.data}
                    existing={existing.state.kind === "ready" ? existing.state.data : null}
                    refetch={existing.refetch}
                />
            )}
        </section>
    )
}

function DefinitionForm({
    campaignId,
    options,
    existing,
    refetch,
}: {
    campaignId: string
    options: ItemDefinitionOptions
    existing: ItemDefinition | null
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const navigate = useNavigate()
    const [name, setName] = useState(existing?.name ?? "")
    const [category, setCategory] = useState(existing?.category ?? "")
    const [rarity, setRarity] = useState(existing?.rarity ?? "common")
    const [attunement, setAttunement] = useState(existing?.requires_attunement ?? false)
    const [weight, setWeight] = useState(existing?.weight === null || existing === null ? "" : String(existing.weight))
    const [cost, setCost] = useState(
        existing?.base_cost_gp === null || existing === null ? "" : String(existing.base_cost_gp),
    )
    const [description, setDescription] = useState(existing?.description ?? "")
    const [status, setStatus] = useState(existing?.canon_status ?? "draft")
    const [problems, setProblems] = useState<Record<string, string>>({})

    const mutation = useAuthoringMutation<ItemDefinitionBody, ItemDefinition>({
        scopeKey: `item-definition:${existing?.item_definition_id ?? "new"}`,
        request: (body, ctx) =>
            existing === null
                ? createItemDefinition(campaignId, body, ctx)
                : updateItemDefinition(
                      campaignId,
                      existing.item_definition_id,
                      { ...body, expected_row_version: existing.row_version },
                      ctx,
                  ),
        onSuccess: async () => {
            if (existing === null) {
                announce("Item definition created")
                void navigate(campaignBase(campaignId))
                return
            }
            await refetch()
            announce("Item definition saved")
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const busy = mutation.status.kind === "pending"

    return (
        <>
            {error?.kind === "stale" ? (
                <StaleWriteNotice
                    onLoadLatest={() => {
                        mutation.reset()
                        void refetch()
                    }}
                />
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            <form
                noValidate
                aria-label="Item definition"
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    const found: Record<string, string> = {}
                    if (name.trim() === "") found.name = "Enter a name."
                    if (category === "") found.category = "Choose a category."
                    const parsedWeight = parseAmount(weight)
                    const parsedCost = parseAmount(cost)
                    if (parsedWeight === undefined) found.weight = "Enter a number such as 3 or 2.5."
                    if (parsedCost === undefined) found.cost = "Enter an amount in gold such as 50 or 0.5."
                    setProblems(found)
                    if (Object.keys(found).length > 0) return
                    mutation.submit({
                        name: name.trim(),
                        category,
                        description: description.trim() === "" ? null : description.trim(),
                        rarity,
                        requires_attunement: attunement,
                        weight: parsedWeight ?? null,
                        base_cost_gp: parsedCost ?? null,
                        canon_status: status,
                    })
                }}
            >
                <TextField
                    id="item-name"
                    label="Name"
                    required
                    value={name}
                    onChange={setName}
                    maxLength={options.limits.name_max_length}
                    error={problems.name ?? null}
                />
                <SelectField
                    id="item-category"
                    label="Category"
                    required
                    value={category}
                    placeholder="Choose a category"
                    options={options.categories}
                    onChange={setCategory}
                    error={problems.category ?? null}
                />
                <SelectField id="item-rarity" label="Rarity" value={rarity} options={options.rarities} onChange={setRarity} />
                <label>
                    <input
                        type="checkbox"
                        checked={attunement}
                        onChange={(event) => setAttunement(event.target.checked)}
                    />{" "}
                    Requires attunement
                </label>
                <TextField
                    id="item-weight"
                    label="Weight (optional)"
                    value={weight}
                    onChange={setWeight}
                    error={problems.weight ?? null}
                />
                <TextField
                    id="item-cost"
                    label="Value in gold (optional)"
                    value={cost}
                    onChange={setCost}
                    error={problems.cost ?? null}
                />
                <TextAreaField
                    id="item-description"
                    label="Description (optional)"
                    value={description}
                    onChange={setDescription}
                    maxLength={options.limits.description_max_length}
                />
                <SelectField
                    id="item-status"
                    label="Status"
                    hint="A draft cannot be used for new items yet."
                    value={status}
                    options={options.canon_states}
                    onChange={setStatus}
                />
                <button type="submit" className="authoring-button" disabled={busy}>
                    {existing === null ? "Create item definition" : "Save item definition"}
                </button>
            </form>
        </>
    )
}
