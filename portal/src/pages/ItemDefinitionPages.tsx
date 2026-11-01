import { useEffect, useRef, useState } from "react"
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router"
import {
    createItemDefinition,
    itemDefinitionOptionsPath,
    itemDefinitionPath,
    itemDefinitionsPath,
    updateItemDefinition,
} from "../api/itemDefinitions"
import { useAnnounce } from "../components/authoring/announcer"
import { MutationStatusMessage, SavedNotice, StaleWriteNotice } from "../components/authoring/feedback"
import { SelectField, TextAreaField, TextField } from "../components/authoring/fields"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import type { RefreshOutcome } from "../hooks/useAuthoringMutation"
import { retryFailedReads, useAuthoringResource } from "../hooks/useAuthoringResource"
import { useConfirmedRefresh } from "../hooks/useConfirmedRefresh"
import { useKeptData } from "../hooks/useKeptData"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { useHeldWorldCapability, WORLD_CANON_EDIT, WORLD_CANON_READ_PRIVATE } from "../hooks/useWorldCapability"
import { useDefinitionsBackPath } from "../hooks/useItemsBackPath"
import { usePageArrival } from "../hooks/usePageArrival"
import type {
    ItemDefinition,
    ItemDefinitionBody,
    ItemDefinitionList,
    ItemDefinitionOptions,
} from "../types/itemDefinitions"
import { StaleReadNotice } from "../components/StaleReadNotice"
import { ReadTerminal } from "../components/authoring/ReadState"
import "../components/authoring/authoring.css"

const AMOUNT = /^\d+(\.\d{1,2})?$/

// An empty box is "not set"; anything else must be a non-negative amount with at most two decimals.
function parseAmount(value: string): number | null | undefined {
    const trimmed = value.trim()
    if (trimmed === "") return null
    return AMOUNT.test(trimmed) ? Number(trimmed) : undefined
}

// The catalog is the world's authoring side (drafts and homebrew in preparation), read only with the
// world's private-read authority. A campaign-only GM still picks published definitions when creating
// an item (the item options), which this page does not touch.
const WORLD_ROLE_NEEDED =
    "Item definitions are the shared world's authoring catalog, including drafts, and need a world role to read. You can still choose a published definition when you create an item; ask the world owner for a world role to manage definitions."

// Creating and changing a definition needs the world's edit authority (the commands check
// `world.canon.edit`); a Reviewer reads the catalog but is not offered either.
const EDIT_AUTHORITY_NEEDED =
    "Creating and editing item definitions needs the world Editor role. You can read the catalog; ask the world owner for the Editor role to change it."

const campaignBase = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}/item-definitions`

// /app/:campaignId/item-definitions — the generic definitions of the ruleset and this world's
// homebrew. Only homebrew can be edited.
export function ItemDefinitionsPage() {
    const { campaignId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const canReadPrivate = useHeldWorldCapability(campaignId, WORLD_CANON_READ_PRIVATE)
    const allowed = canEdit && canReadPrivate
    const canChange = useHeldWorldCapability(campaignId, WORLD_CANON_EDIT)
    // The filters live in the address (`?category=&homebrew=1`), so Back, a reload and a shared
    // link restore them.
    const [params, setParams] = useSearchParams()
    const location = useLocation()
    const category = params.get("category") ?? ""
    const homebrewOnly = params.get("homebrew") === "1"
    const setFilter = (key: string, value: string | null) => {
        const next = new URLSearchParams(params)
        if (value === null || value === "") next.delete(key)
        else next.set(key, value)
        setParams(next, { replace: true })
    }
    const options = useAuthoringResource<ItemDefinitionOptions>(
        allowed ? itemDefinitionOptionsPath(campaignId) : null,
    )
    const list = useAuthoringResource<ItemDefinitionList>(allowed ? itemDefinitionsPath(campaignId) : null)
    const headingRef = usePageArrival(list.state.kind !== "loading")
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
            ) : !canReadPrivate ? (
                <p role="alert">{WORLD_ROLE_NEEDED}</p>
            ) : list.state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : list.state.kind !== "ready" ? (
                <ReadTerminal
                    states={[list.state, options.state]}
                    what="list of item definitions"
                    onRetry={() => retryFailedReads(list, options)}
                    back={{ to: `/app/${encodeURIComponent(campaignId)}/home`, label: "Back to the campaign" }}
                />
            ) : (
                <>
                    <p className="authoring-note">
                        Generic definitions come with the ruleset and cannot be changed. Definitions you create
                        belong to this world only.
                    </p>
                    {canChange ? (
                        <p>
                            <Link
                                className="authoring-button"
                                to={`${campaignBase(campaignId)}/new`}
                                state={{ definitionsSearch: location.search }}
                            >
                                New item definition
                            </Link>
                        </p>
                    ) : (
                        <p className="authoring-note">{EDIT_AUTHORITY_NEEDED}</p>
                    )}
                    <form noValidate aria-label="Filter item definitions" className="authoring-form">
                        {options.state.kind === "ready" ? (
                            <SelectField
                                id="item-filter-category"
                                label="Category"
                                value={category}
                                placeholder="All categories"
                                options={options.state.data.categories}
                                onChange={(value) => setFilter("category", value)}
                            />
                        ) : options.state.kind === "loading" ? (
                            <p role="status">Loading categories…</p>
                        ) : (
                            // The list is usable without the categories, but a missing catalog is
                            // said to be missing, never shown as an empty choice.
                            <ReadTerminal
                                states={[options.state]}
                                what="category filter"
                                onRetry={options.refetch}
                                pageTitle={false}
                            />
                        )}
                        <label>
                            <input
                                type="checkbox"
                                checked={homebrewOnly}
                                onChange={(event) => setFilter("homebrew", event.target.checked ? "1" : null)}
                            />{" "}
                            Show only this world&apos;s definitions
                        </label>
                    </form>
                    {items.length === 0 ? (
                        <p>No item definitions match.</p>
                    ) : (
                        <ul className="op-list">
                            {items.map((item) => (
                                <li key={item.item_definition_id}>
                                    {item.name} ({item.category_label}, {item.rarity.replace(/_/g, " ")})
                                    {item.canon_status !== "canon" ? " (draft)" : ""}
                                    {item.is_homebrew && canChange ? (
                                        <>
                                            {" "}
                                            <Link
                                                to={`${campaignBase(campaignId)}/${encodeURIComponent(item.item_definition_id)}`}
                                                state={{ definitionsSearch: location.search }}
                                            >
                                                Edit {item.name}
                                            </Link>
                                        </>
                                    ) : item.is_homebrew ? (
                                        " (this world's)"
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
    const listPath = useDefinitionsBackPath(campaignId)
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const canReadPrivate = useHeldWorldCapability(campaignId, WORLD_CANON_READ_PRIVATE)
    const canChange = useHeldWorldCapability(campaignId, WORLD_CANON_EDIT)
    const allowed = canEdit && canReadPrivate && canChange
    const options = useAuthoringResource<ItemDefinitionOptions>(
        allowed ? itemDefinitionOptionsPath(campaignId) : null,
    )
    const existing = useAuthoringResource<ItemDefinition>(
        !allowed || definitionId === undefined ? null : itemDefinitionPath(campaignId, definitionId),
    )
    // The last definition that was read. A refresh that fails recoverably (after a save, say) keeps the
    // form on it, marked stale; a refusal or a missing record discards it and fails closed.
    const kept = useKeptData(existing.state)
    const current = definitionId === undefined ? null : kept.data
    // Settled, not only ready: a read that ended in a refusal or a failure also takes the heading's focus.
    const ready =
        options.state.kind !== "loading" && (definitionId === undefined || existing.state.kind !== "loading")
    const headingRef = usePageArrival(ready)
    return (
        <section className="authoring-page" aria-labelledby="item-definition-heading">
            <nav aria-label="Breadcrumb" className="authoring-page__breadcrumb">
                <ol className="session-run__breadcrumb">
                    <li>
                        <Link to={listPath}>Item definitions</Link>
                    </li>
                    <li aria-current="page">
                        {definitionId === undefined
                            ? "New item definition"
                            : current !== null
                              ? current.name
                              : "Edit item definition"}
                    </li>
                </ol>
            </nav>
            <h1 id="item-definition-heading" ref={headingRef} tabIndex={-1}>
                {definitionId === undefined ? "New item definition" : "Edit item definition"}
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to edit item definitions.</p>
            ) : !canReadPrivate ? (
                <p role="alert">{WORLD_ROLE_NEEDED}</p>
            ) : !canChange ? (
                <p role="alert">{EDIT_AUTHORITY_NEEDED}</p>
            ) : options.state.kind === "loading" || (definitionId !== undefined && existing.state.kind === "loading") ? (
                <p role="status">Loading…</p>
            ) : options.state.kind !== "ready" || (definitionId !== undefined && current === null) ? (
                <ReadTerminal
                    states={definitionId === undefined ? [options.state] : [existing.state, options.state]}
                    what={definitionId === undefined ? "form" : "item definition"}
                    onRetry={() => retryFailedReads(options, existing)}
                    back={{ to: listPath, label: "Back to item definitions" }}
                />
            ) : current !== null && !current.can_edit ? (
                <p>This is a generic definition from the ruleset and cannot be changed.</p>
            ) : (
                // Keyed by the record, not its version: a save and its re-read update this form in
                // place, so the inputs, focus and scroll stay, and a different definition starts clean.
                <DefinitionForm
                    key={definitionId ?? "new"}
                    campaignId={campaignId}
                    options={options.state.data}
                    existing={current}
                    stale={kept.stale}
                    refetch={existing.refetch}
                    listPath={listPath}
                />
            )}
        </section>
    )
}

interface Values {
    name: string
    category: string
    rarity: string
    attunement: boolean
    weight: string
    cost: string
    description: string
    status: string
}

const FIELD_LABELS: Record<keyof Values, string> = {
    name: "Name",
    category: "Category",
    rarity: "Rarity",
    attunement: "Requires attunement",
    weight: "Weight",
    cost: "Value in gold",
    description: "Description",
    status: "Status",
}

function baselineOf(existing: ItemDefinition | null): Values {
    return {
        name: existing?.name ?? "",
        category: existing?.category ?? "",
        rarity: existing?.rarity ?? "common",
        attunement: existing?.requires_attunement ?? false,
        weight: existing?.weight === null || existing === null ? "" : String(existing.weight),
        cost: existing?.base_cost_gp === null || existing === null ? "" : String(existing.base_cost_gp),
        description: existing?.description ?? "",
        status: existing?.canon_status ?? "draft",
    }
}

// The row version travels in the body so an attempt against another version is a different request
// (a new Idempotency-Key), and a retry of an unresolved attempt re-sends the version it was made against.
type SaveBody = ItemDefinitionBody & { expected_row_version?: number }

function DefinitionForm({
    campaignId,
    options,
    existing,
    stale,
    refetch,
    listPath,
}: {
    campaignId: string
    options: ItemDefinitionOptions
    existing: ItemDefinition | null
    // The definition shown is the last good read because the latest one failed.
    stale: boolean
    refetch: () => Promise<RefreshOutcome>
    // The list the person came from, with its filters.
    listPath: string
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const navigate = useNavigate()
    // Only the fields the person changed are held; everything else follows the loaded definition, so a
    // read never overwrites typed input and a save only forgets what it actually sent.
    const baseline = baselineOf(existing)
    const [edits, setEdits] = useState<Partial<Values>>({})
    const [problems, setProblems] = useState<Record<string, string>>({})
    // A confirmed save the shown definition does not reflect yet, and the values that save sent.
    const [unreconciled, setUnreconciled] = useState<{ version: number; sent: Partial<Values> } | null>(null)
    const [savedShown, setSavedShown] = useState(false)
    // The values of each attempt, by the body it sent, so the confirmed attempt (which can be an earlier
    // retry) is the one that is forgotten.
    const attempts = useRef(new Map<string, Partial<Values>>())
    const inFlight = useRef(false)
    const mounted = useRef(true)
    useEffect(() => {
        mounted.current = true
        return () => {
            mounted.current = false
        }
    }, [])

    const valueOf = <K extends keyof Values>(field: K): Values[K] => (edits[field] ?? baseline[field]) as Values[K]
    const dirtyFields = (Object.keys(edits) as (keyof Values)[]).filter(
        (field) => edits[field] !== undefined && edits[field] !== baseline[field],
    )
    const dirty = dirtyFields.length > 0

    function setField<K extends keyof Values>(field: K, value: Values[K]) {
        setEdits((previous) => {
            const next = { ...previous }
            // Back to the loaded value is no change at all.
            if (value === baseline[field]) delete next[field]
            else next[field] = value
            return next
        })
        setSavedShown(false)
    }

    const mutation = useAuthoringMutation<SaveBody, ItemDefinition>({
        scopeKey: `item-definition:${existing?.item_definition_id ?? "new"}`,
        request: (body, ctx) =>
            existing === null
                ? createItemDefinition(campaignId, body, ctx)
                : updateItemDefinition(
                      campaignId,
                      existing.item_definition_id,
                      { ...body, expected_row_version: body.expected_row_version ?? existing.row_version },
                      ctx,
                  ),
        ownsRefreshNotice: true,
        onSuccess: async (result, body) => {
            if (existing === null) {
                announce("Item definition created")
                void navigate(listPath)
                return
            }
            setUnreconciled({ version: result.row_version, sent: attempts.current.get(JSON.stringify(body)) ?? {} })
            const outcome = await refetch()
            if (outcome === "ok" && mounted.current) announce("Item definition saved")
            return outcome
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const busy = mutation.status.kind === "pending"
    useEffect(() => {
        if (mutation.status.kind !== "pending") inFlight.current = false
    }, [mutation.status])

    // The shown definition now includes the confirmed save: it becomes the baseline, and only the edits
    // that still equal what that save sent are forgotten. Anything typed since stays, and stays dirty.
    // Adjusted while rendering (as useKeptData does), so a read that worked is never a render behind.
    if (unreconciled !== null && existing !== null && existing.row_version >= unreconciled.version) {
        const sent = unreconciled.sent
        setEdits((previous) => {
            const next = { ...previous }
            for (const field of Object.keys(sent) as (keyof Values)[]) {
                if (next[field] === sent[field]) delete next[field]
            }
            return next
        })
        setUnreconciled(null)
        setSavedShown(true)
    }

    const confirmed = useConfirmedRefresh({
        status: mutation.status,
        reset: mutation.reset,
        what: "item definition",
        message: "Item definition saved",
        read: refetch,
        pageStale: stale,
    })
    // The shown version is behind a confirmed save until a read works: saving from it would be refused.
    const held = existing !== null && confirmed.held

    function submit() {
        if (busy || held || inFlight.current) return
        const found: Record<string, string> = {}
        const name = valueOf("name")
        const weight = valueOf("weight")
        const cost = valueOf("cost")
        if (name.trim() === "") found.name = "Enter a name."
        if (valueOf("category") === "") found.category = "Choose a category."
        const parsedWeight = parseAmount(weight)
        const parsedCost = parseAmount(cost)
        if (parsedWeight === undefined) found.weight = "Enter a number such as 3 or 2.5."
        if (parsedCost === undefined) found.cost = "Enter an amount in gold such as 50 or 0.5."
        setProblems(found)
        if (Object.keys(found).length > 0) return
        const description = valueOf("description")
        const body: SaveBody = {
            name: name.trim(),
            category: valueOf("category"),
            description: description.trim() === "" ? null : description.trim(),
            rarity: valueOf("rarity"),
            requires_attunement: valueOf("attunement"),
            weight: parsedWeight ?? null,
            base_cost_gp: parsedCost ?? null,
            canon_status: valueOf("status"),
            ...(existing === null ? {} : { expected_row_version: existing.row_version }),
        }
        const sent: Partial<Values> = {}
        for (const field of dirtyFields) (sent as Record<string, unknown>)[field] = edits[field]
        attempts.current.set(JSON.stringify(body), sent)
        setSavedShown(false)
        if (mutation.submit(body) === "sent") inFlight.current = true
    }

    const yourChanges = dirty ? (
        <p>Your unsaved changes: {dirtyFields.map((field) => FIELD_LABELS[field]).join(", ")}.</p>
    ) : undefined

    return (
        <form
            noValidate
            aria-label="Item definition"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                submit()
            }}
        >
            <TextField
                id="item-name"
                label="Name"
                required
                value={valueOf("name")}
                onChange={(value) => setField("name", value)}
                maxLength={options.limits.name_max_length}
                error={problems.name ?? null}
            />
            <SelectField
                id="item-category"
                label="Category"
                required
                value={valueOf("category")}
                placeholder="Choose a category"
                options={options.categories}
                onChange={(value) => setField("category", value)}
                error={problems.category ?? null}
            />
            <SelectField
                id="item-rarity"
                label="Rarity"
                value={valueOf("rarity")}
                options={options.rarities}
                onChange={(value) => setField("rarity", value)}
            />
            <label>
                <input
                    type="checkbox"
                    checked={valueOf("attunement")}
                    onChange={(event) => setField("attunement", event.target.checked)}
                />{" "}
                Requires attunement
            </label>
            <TextField
                id="item-weight"
                label="Weight (optional)"
                value={valueOf("weight")}
                onChange={(value) => setField("weight", value)}
                error={problems.weight ?? null}
            />
            <TextField
                id="item-cost"
                label="Value in gold (optional)"
                value={valueOf("cost")}
                onChange={(value) => setField("cost", value)}
                error={problems.cost ?? null}
            />
            <TextAreaField
                id="item-description"
                label="Description (optional)"
                value={valueOf("description")}
                onChange={(value) => setField("description", value)}
                maxLength={options.limits.description_max_length}
            />
            <SelectField
                id="item-status"
                label="Status"
                hint="A draft cannot be used for new items yet."
                value={valueOf("status")}
                options={options.canon_states}
                onChange={(value) => setField("status", value)}
            />
            {stale ? <StaleReadNotice what="item definition" onRetry={() => void refetch()} /> : null}
            {error?.kind === "stale" ? (
                <StaleWriteNotice
                    yourChanges={yourChanges}
                    onLoadLatest={() => {
                        mutation.reset()
                        void refetch()
                    }}
                />
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : confirmed.notice !== null ? (
                confirmed.notice
            ) : savedShown ? (
                <SavedNotice>
                    <p>Item definition saved.</p>
                    {dirty ? <p>Your newer changes are not saved yet.</p> : null}
                </SavedNotice>
            ) : null}
            {held ? (
                <p id="item-save-held" className="authoring-note">
                    Load the latest version before saving again.
                </p>
            ) : null}
            {/* Held with aria-disabled, not `disabled`: a disabled button that has focus drops it, and the
                form's submit handler refuses a held or pending save whichever way it is submitted. */}
            <button
                type="submit"
                className="authoring-button"
                aria-disabled={busy || held}
                aria-busy={busy}
                aria-describedby={held ? "item-save-held" : undefined}
            >
                {existing === null ? "Create item definition" : "Save item definition"}
            </button>
            {busy ? <span className="authoring-note"> Saving…</span> : null}
        </form>
    )
}
