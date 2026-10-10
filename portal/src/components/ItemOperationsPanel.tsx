import { useState } from "react"
import { itemAuthoringPath, runItemOperation } from "../api/items"
import { fetchWorldEntities } from "../api/world"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import type { ItemView } from "../types/items"
import type { WorldCategory } from "../types/world"
import { useAnnounce } from "./authoring/announcer"
import { ConfirmDialog } from "./authoring/ConfirmDialog"
import { TextField } from "./authoring/fields"
import { MutationStatusMessage, StaleWriteNotice } from "./authoring/feedback"
import { ReferenceCombobox } from "./authoring/ReferenceCombobox"
import type { ReferenceOption } from "./authoring/ReferenceCombobox"
import { WorldTimePicker } from "./authoring/WorldTimePicker"
import "./authoring/authoring.css"

interface Props {
    campaignId: string
    itemId: string
    // Called after an operation so the page above can refresh what it shows.
    onChanged?: () => void
}

interface Command {
    operation: string
    body: Record<string, unknown>
    done: string
}

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    item_destroyed: "This item is destroyed.",
    item_already_placed: "This item already has a place. Move it instead.",
    item_not_held: "A character has to be carrying this item for that.",
    item_equipped: "Unequip the item first.",
    item_attuned: "End the attunement first.",
    item_operation_invalid: "That cannot be done to this item as it is now.",
    attunement_not_allowed: "This item cannot be attuned right now (it may not need attunement, may already be attuned, or the character has three attuned items).",
    item_destination_invalid: "Choose a published character or place in this world.",
    item_container_invalid: "That item cannot be placed in that container.",
    clock_required: "Set the campaign time first, or choose a time below.",
}

const humanize = (code: string): string => code.replace(/_/g, " ")

// GM controls for one item, under its world page: award it, move it, equip, use, damage, repair,
// destroy, attune. Each is one command that records an event at the chosen time (or the
// campaign clock) and names the last event this panel saw, so a change made elsewhere meanwhile
// is reported as stale instead of overwritten.
export function ItemOperationsPanel({ campaignId, itemId, onChanged }: Props) {
    if (!useCampaignCapability(campaignId, "canon.edit")) return null
    return <Loaded campaignId={campaignId} itemId={itemId} onChanged={onChanged} />
}

function Loaded({ campaignId, itemId, onChanged }: Props) {
    const { state, refetch } = useAuthoringResource<ItemView>(itemAuthoringPath(campaignId, itemId))
    if (state.kind !== "ready") return null
    return (
        <Panel
            key={state.data.last_event_id ?? "none"}
            campaignId={campaignId}
            view={state.data}
            refetch={async () => {
                await refetch()
                onChanged?.()
            }}
        />
    )
}

function Panel({
    campaignId,
    view,
    refetch,
}: {
    campaignId: string
    view: ItemView
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [when, setWhen] = useState("")
    const [holder, setHolder] = useState<ReferenceOption | null>(null)
    const [place, setPlace] = useState<ReferenceOption | null>(null)
    const [quantity, setQuantity] = useState("1")
    const [amount, setAmount] = useState("")
    const [makeOwner, setMakeOwner] = useState(true)
    const [problem, setProblem] = useState<string | null>(null)
    const [done, setDone] = useState<string | null>(null)
    const [confirmDestroy, setConfirmDestroy] = useState(false)

    const mutation = useAuthoringMutation<Command, unknown>({
        scopeKey: `item-operation:${view.item_instance_id}`,
        request: (command, ctx) =>
            runItemOperation(
                campaignId,
                view.item_instance_id,
                command.operation,
                {
                    expected_last_event_id: view.last_event_id,
                    ...(when === "" ? {} : { world_time_id: when }),
                    ...command.body,
                },
                ctx,
            ),
        onSuccess: async () => {
            const message = done
            setDone(null)
            setAmount("")
            setHolder(null)
            setPlace(null)
            setConfirmDestroy(false)
            await refetch()
            if (message !== null) announce(message)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const busy = mutation.status.kind === "pending"

    const run = (command: Command) => {
        setProblem(null)
        setDone(command.done)
        mutation.submit(command)
    }

    const wholeNumber = (value: string, max: number): number | null => {
        const parsed = Number(value)
        return value.trim() !== "" && Number.isInteger(parsed) && parsed >= 1 && parsed <= max
            ? parsed
            : null
    }

    function searcher(category: WorldCategory) {
        return async (query: string, signal: AbortSignal): Promise<ReferenceOption[]> => {
            const page = await fetchWorldEntities(campaignId, { category, query, limit: 10 }, signal)
            return page.items
                .filter((i) => i.canon_status === undefined || i.canon_status === "canon")
                .map((i) => ({ id: i.entity_id, label: i.name, detail: humanize(i.entity_type_code) }))
        }
    }

    if (!view.can_operate) {
        return (
            <section className="authoring-aside" aria-labelledby="item-ops-heading">
                <h2 id="item-ops-heading">Run this item</h2>
                <p>Publish this item to award it, move it or change its condition.</p>
            </section>
        )
    }

    const placed = view.holder !== null || view.container !== null || view.location !== null
    const held = view.holder !== null
    return (
        <section className="authoring-aside" aria-labelledby="item-ops-heading">
            <h2 id="item-ops-heading">Run this item</h2>
            {error?.kind === "stale" ? (
                <StaleWriteNotice
                    onLoadLatest={() => {
                        mutation.reset()
                        void refetch()
                    }}
                />
            ) : explained !== null ? (
                <p role="alert">{explained}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            {problem !== null ? <p role="alert">{problem}</p> : null}

            <dl className="authoring-fact-list">
                <dt>Carried by</dt>
                <dd>{view.holder?.name ?? "Nobody"}</dd>
                <dt>Lying at</dt>
                <dd>{view.location?.name ?? "Nowhere"}</dd>
                {view.container !== null ? (
                    <>
                        <dt>Inside</dt>
                        <dd>{view.container.name}</dd>
                    </>
                ) : null}
                <dt>Owner</dt>
                <dd>{view.owner?.name ?? "Nobody"}</dd>
                <dt>Quantity</dt>
                <dd>{view.quantity}</dd>
                <dt>Condition</dt>
                <dd>{view.condition_percentage === null ? "Undamaged" : `${view.condition_percentage}%`}</dd>
                <dt>Equipped</dt>
                <dd>{view.is_equipped ? "Yes" : "No"}</dd>
                {view.requires_attunement ? (
                    <>
                        <dt>Attuned to</dt>
                        <dd>{view.attuned_to?.name ?? "Nobody"}</dd>
                    </>
                ) : null}
            </dl>

            {view.is_destroyed ? (
                <p>This item is destroyed. Nothing more can be done to it.</p>
            ) : (
                <>
                    <WorldTimePicker
                        campaignId={campaignId}
                        id="item-ops-when"
                        label="When this happens"
                        hint="Leave empty to use the campaign time."
                        value={when}
                        onChange={setWhen}
                    />

                    {!placed ? (
                        <form
                            noValidate
                            aria-label="Award this item"
                            className="authoring-form"
                            onSubmit={(event) => {
                                event.preventDefault()
                                const count = wholeNumber(quantity, 9999)
                                if (holder === null || count === null) {
                                    setProblem("Choose who receives it and a quantity from 1 to 9999.")
                                    return
                                }
                                run({
                                    operation: "award",
                                    body: { holder_entity_id: holder.id, quantity: count, set_owner: makeOwner },
                                    done: "Item awarded",
                                })
                            }}
                        >
                            <ReferenceCombobox
                                id="item-award-holder"
                                label="Award to"
                                value={holder}
                                onChange={setHolder}
                                search={searcher("character")}
                                placeholder="Search characters"
                            />
                            <TextField id="item-award-quantity" label="Quantity" value={quantity} onChange={setQuantity} />
                            <label>
                                <input
                                    type="checkbox"
                                    checked={makeOwner}
                                    onChange={(event) => setMakeOwner(event.target.checked)}
                                />{" "}
                                They own it
                            </label>
                            <button type="submit" className="authoring-button" disabled={busy}>
                                Award item
                            </button>
                        </form>
                    ) : (
                        <>
                            <form
                                noValidate
                                aria-label="Give this item to a character"
                                className="authoring-form"
                                onSubmit={(event) => {
                                    event.preventDefault()
                                    if (holder === null) {
                                        setProblem("Choose who receives it.")
                                        return
                                    }
                                    run({
                                        operation: "transfer",
                                        body: { holder_entity_id: holder.id, transfer_ownership: makeOwner },
                                        done: "Item given",
                                    })
                                }}
                            >
                                <ReferenceCombobox
                                    id="item-give-holder"
                                    label="Give to"
                                    value={holder}
                                    onChange={setHolder}
                                    search={searcher("character")}
                                    placeholder="Search characters"
                                />
                                <label>
                                    <input
                                        type="checkbox"
                                        checked={makeOwner}
                                        onChange={(event) => setMakeOwner(event.target.checked)}
                                    />{" "}
                                    They own it
                                </label>
                                <button type="submit" className="authoring-button" disabled={busy}>
                                    Give item
                                </button>
                            </form>
                            <form
                                noValidate
                                aria-label="Leave this item at a place"
                                className="authoring-form"
                                onSubmit={(event) => {
                                    event.preventDefault()
                                    if (place === null) {
                                        setProblem("Choose a place.")
                                        return
                                    }
                                    run({
                                        operation: "transfer",
                                        body: { location_id: place.id },
                                        done: "Item placed",
                                    })
                                }}
                            >
                                <ReferenceCombobox
                                    id="item-place"
                                    label="Leave at"
                                    value={place}
                                    onChange={setPlace}
                                    search={searcher("location")}
                                    placeholder="Search places"
                                />
                                <button type="submit" className="authoring-button" disabled={busy}>
                                    Leave item
                                </button>
                            </form>
                        </>
                    )}

                    {held ? (
                        <p>
                            <button
                                type="button"
                                className="authoring-button"
                                disabled={busy}
                                onClick={() =>
                                    run({
                                        operation: view.is_equipped ? "unequip" : "equip",
                                        body: {},
                                        done: view.is_equipped ? "Item unequipped" : "Item equipped",
                                    })
                                }
                            >
                                {view.is_equipped ? "Unequip" : "Equip"}
                            </button>
                        </p>
                    ) : null}

                    {placed ? (
                        <form
                            noValidate
                            aria-label="Change this item"
                            className="authoring-form"
                            onSubmit={(event) => event.preventDefault()}
                        >
                            <TextField
                                id="item-amount"
                                label="Amount"
                                hint="Units used, or condition points (1 to 100) lost or restored."
                                value={amount}
                                onChange={setAmount}
                            />
                            {(
                                [
                                    ["consume", "Use", 9999, "Item used"],
                                    ["damage", "Damage", 100, "Item damaged"],
                                    ["repair", "Repair", 100, "Item repaired"],
                                ] as const
                            ).map(([operation, label, max, message]) => (
                                <button
                                    key={operation}
                                    type="button"
                                    className="authoring-button"
                                    disabled={busy}
                                    onClick={() => {
                                        const value = wholeNumber(amount, max)
                                        if (value === null) {
                                            setProblem(`Enter a whole number from 1 to ${max}.`)
                                            return
                                        }
                                        run({ operation, body: { amount: value }, done: message })
                                    }}
                                >
                                    {label}
                                </button>
                            ))}
                        </form>
                    ) : null}

                    {held && view.requires_attunement ? (
                        <p>
                            {view.attuned_to === null ? (
                                <button
                                    type="button"
                                    className="authoring-button"
                                    disabled={busy}
                                    onClick={() =>
                                        run({
                                            operation: "attune",
                                            body: { character_id: view.holder?.entity_id },
                                            done: "Item attuned",
                                        })
                                    }
                                >
                                    Attune to {view.holder?.name}
                                </button>
                            ) : (
                                <button
                                    type="button"
                                    className="authoring-button"
                                    disabled={busy}
                                    onClick={() =>
                                        run({ operation: "end-attunement", body: {}, done: "Attunement ended" })
                                    }
                                >
                                    End attunement
                                </button>
                            )}
                        </p>
                    ) : null}

                    {placed ? (
                        <p>
                            <button
                                type="button"
                                className="authoring-button"
                                disabled={busy}
                                onClick={() => setConfirmDestroy(true)}
                            >
                                Destroy item
                            </button>
                        </p>
                    ) : null}
                    <ConfirmDialog
                        open={confirmDestroy}
                        title="Destroy this item?"
                        description="A destroyed item stays in history but takes no further changes. A mistaken destruction can be undone only while it is the item's latest event."
                        confirmLabel="Destroy item"
                        pending={busy}
                        onConfirm={() => run({ operation: "destroy", body: {}, done: "Item destroyed" })}
                        onCancel={() => setConfirmDestroy(false)}
                    />
                </>
            )}
        </section>
    )
}
