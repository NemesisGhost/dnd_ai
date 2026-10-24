import { useState } from "react"
import type { ReactNode } from "react"
import { Link } from "react-router"
import { fetchWorldEntities } from "../../api/world"
import type { ItemView } from "../../types/items"
import type { WorldCategory } from "../../types/world"
import { humanizeCode } from "../../utils/humanize"
import { isPlaced, leavesText } from "../../utils/itemState"
import { canonStatusLabel } from "../../utils/lifecycleNextStep"
import { ConfirmDialog } from "../authoring/ConfirmDialog"
import { RadioGroupField, TextField } from "../authoring/fields"
import { ReferenceCombobox } from "../authoring/ReferenceCombobox"
import type { ReferenceOption } from "../authoring/ReferenceCombobox"
import type { ItemGuidance, ItemSection } from "./itemStages"
import type { ItemDrafts, MoveAction, OwnershipChoice } from "./useItemDrafts"
import type { ItemOperations } from "./useItemOperation"
import "../authoring/authoring.css"

interface SectionProps {
    campaignId: string
    view: ItemView
    ops: ItemOperations
    drafts: ItemDrafts
    guidance: ItemGuidance | null
    // Where a section of the page is, as an address.
    sectionHref: (section: ItemSection) => string
    linkState?: object
}

const wholeNumber = (value: string, max: number): number | null => {
    const parsed = Number(value)
    return value.trim() !== "" && Number.isInteger(parsed) && parsed >= 1 && parsed <= max ? parsed : null
}

// What stops every Use-in-play section, in words and with the step that unlocks it. Null when the
// item can be operated on. A section the item cannot use yet explains why instead of a disabled form.
function blockerOf({ view, guidance, sectionHref, linkState }: SectionProps): ReactNode {
    if (!view.can_operate) {
        const next =
            guidance === null ? null : (
                <>
                    {" "}
                    Next:{" "}
                    <Link to={sectionHref(guidance.section)} state={linkState}>
                        {guidance.text} ›
                    </Link>
                </>
            )
        return view.lifecycle_status === "archived" ? (
            <p role="status">
                This item is archived. What happened to it is kept, but nothing can change until it is restored.
                {next}
            </p>
        ) : (
            <p role="status">
                Only a published item can be used in play. This item is {canonStatusLabel(view.canon_status)}.
                {next}
            </p>
        )
    }
    if (view.is_destroyed) {
        return <p role="status">This item is destroyed. Nothing more can be done to it.</p>
    }
    return null
}

function searcher(campaignId: string, category: WorldCategory, exclude: string | null) {
    return async (query: string, signal: AbortSignal): Promise<ReferenceOption[]> => {
        const page = await fetchWorldEntities(campaignId, { category, query, limit: 10 }, signal)
        return page.items
            .filter((i) => (i.canon_status === undefined || i.canon_status === "canon") && i.entity_id !== exclude)
            .map((i) => ({ id: i.entity_id, label: i.name, detail: humanizeCode(i.entity_type_code) }))
    }
}

const MOVE_OPTIONS = [
    { value: "give", label: "Give to a character" },
    { value: "place", label: "Place at a location" },
] as const

// Give to a character or place at a location: two alternatives, one chosen at a time. Choosing
// only reveals that action's inputs; the command is sent by its own button. Ownership is separate
// from possession: giving asks about it explicitly, placing never touches it.
export function ItemMoveSection(props: SectionProps) {
    const { campaignId, view, ops, drafts, sectionHref, linkState } = props
    const blocker = blockerOf(props)
    if (blocker !== null) return <>{blocker}</>

    const placed = isPlaced(view)
    // An equipped or attuned item stays with its carrier until that is undone.
    if (view.holder !== null && (view.is_equipped || view.attuned_to !== null)) {
        return (
            <p role="status">
                {view.holder.name} has it {view.is_equipped ? "equipped" : "attuned"}, so it cannot be given away or
                placed.{" "}
                <Link to={sectionHref("equipment")} state={linkState}>
                    {view.is_equipped ? "Unequip it" : "End the attunement"} first ›
                </Link>
            </p>
        )
    }

    const leaves = leavesText(view)
    const ownerStays = view.owner !== null ? ` The owner stays ${view.owner.name}.` : " It has no recorded owner."

    const give = () => {
        if (drafts.holder === null) return ops.reject("move", "Choose who receives it.")
        const count = placed ? 1 : wholeNumber(drafts.quantity, 9999)
        if (count === null) return ops.reject("move", "Enter a quantity from 1 to 9999.")
        if (drafts.ownership === null) return ops.reject("move", "Choose who owns it afterwards.")
        const makeOwner = drafts.ownership === "recipient"
        ops.run({
            section: "move",
            operation: placed ? "transfer" : "award",
            body: placed
                ? { holder_entity_id: drafts.holder.id, transfer_ownership: makeOwner }
                : { holder_entity_id: drafts.holder.id, quantity: count, set_owner: makeOwner },
            done: placed ? "Item given" : "Item awarded",
            after: drafts.clearGive,
        })
    }
    const placeHere = () => {
        if (drafts.place === null) return ops.reject("move", "Choose a place.")
        ops.run({
            section: "move",
            operation: "transfer",
            body: { location_id: drafts.place.id },
            done: "Item placed",
            after: drafts.clearPlace,
        })
    }

    return (
        <>
            {ops.feedback("move")}
            <RadioGroupField
                legend="What happened?"
                hint="Choosing one only shows its details. Nothing is recorded until you press its button."
                value={drafts.action ?? ""}
                options={MOVE_OPTIONS}
                onChange={(value) => drafts.setAction(value as MoveAction)}
            />
            {drafts.action === "give" ? (
                <form
                    noValidate
                    aria-label="Give this item to a character"
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        give()
                    }}
                >
                    <ReferenceCombobox
                        id="item-give-holder"
                        label="Give to"
                        value={drafts.holder}
                        onChange={drafts.setHolder}
                        search={searcher(campaignId, "character", view.holder?.entity_id ?? null)}
                        placeholder="Search characters"
                    />
                    {!placed ? (
                        <TextField
                            id="item-give-quantity"
                            label="Quantity"
                            value={drafts.quantity}
                            onChange={drafts.setQuantity}
                        />
                    ) : null}
                    {leaves !== null ? <p className="authoring-note">{leaves}</p> : null}
                    <RadioGroupField
                        legend="Ownership afterwards"
                        hint="Who has it and who owns it are separate."
                        value={drafts.ownership ?? ""}
                        options={[
                            {
                                value: "keep",
                                label:
                                    view.owner !== null
                                        ? `Keep the current owner (${view.owner.name})`
                                        : "Leave it without an owner",
                            },
                            {
                                value: "recipient",
                                label: `Make ${drafts.holder?.label ?? "the new carrier"} the owner`,
                            },
                        ]}
                        onChange={(value) => drafts.setOwnership(value as OwnershipChoice)}
                    />
                    <button type="submit" className="authoring-button" disabled={ops.busy}>
                        Give item
                    </button>
                </form>
            ) : null}
            {drafts.action === "place" ? (
                <form
                    noValidate
                    aria-label="Place this item at a location"
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        placeHere()
                    }}
                >
                    <ReferenceCombobox
                        id="item-place"
                        label="Place at"
                        value={drafts.place}
                        onChange={drafts.setPlace}
                        search={searcher(campaignId, "location", view.location?.entity_id ?? null)}
                        placeholder="Search places"
                    />
                    <p className="authoring-note">
                        {leaves !== null ? `${leaves}${ownerStays}` : "Ownership is not changed by placing it."}
                        {!placed ? " Placing does not set a quantity; give it to a character to record one." : ""}
                    </p>
                    <button type="submit" className="authoring-button" disabled={ops.busy}>
                        Place item
                    </button>
                </form>
            ) : null}
        </>
    )
}

export function ItemEquipmentSection(props: SectionProps) {
    const { view, ops } = props
    const blocker = blockerOf(props)
    if (blocker !== null) return <>{blocker}</>
    if (view.holder === null) {
        return <p role="status">Only a carried item can be equipped or attuned. Give it to a character first.</p>
    }
    const holder = view.holder
    return (
        <>
            {ops.feedback("equipment")}
            <p>
                <button
                    type="button"
                    className="authoring-button"
                    disabled={ops.busy}
                    onClick={() =>
                        ops.run({
                            section: "equipment",
                            operation: view.is_equipped ? "unequip" : "equip",
                            body: {},
                            done: view.is_equipped ? "Item unequipped" : "Item equipped",
                        })
                    }
                >
                    {view.is_equipped ? "Unequip" : "Equip"}
                </button>
            </p>
            {view.requires_attunement ? (
                <p>
                    {view.attuned_to === null ? (
                        <button
                            type="button"
                            className="authoring-button"
                            disabled={ops.busy}
                            onClick={() =>
                                ops.run({
                                    section: "equipment",
                                    operation: "attune",
                                    body: { character_id: holder.entity_id },
                                    done: "Item attuned",
                                })
                            }
                        >
                            Attune to {holder.name}
                        </button>
                    ) : (
                        <button
                            type="button"
                            className="authoring-button"
                            disabled={ops.busy}
                            onClick={() =>
                                ops.run({
                                    section: "equipment",
                                    operation: "end-attunement",
                                    body: {},
                                    done: "Attunement ended",
                                })
                            }
                        >
                            End attunement
                        </button>
                    )}
                </p>
            ) : (
                <p className="authoring-note">This kind of item does not need attunement.</p>
            )}
        </>
    )
}

export function ItemConditionSection(props: SectionProps) {
    const { view, ops, drafts } = props
    const [confirmDestroy, setConfirmDestroy] = useState(false)
    const blocker = blockerOf(props)
    if (blocker !== null) return <>{blocker}</>
    if (!isPlaced(view)) {
        return <p role="status">Give it to someone or place it first; then it can be used, damaged or repaired.</p>
    }
    return (
        <>
            {ops.feedback("condition")}
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
                    value={drafts.amount}
                    onChange={drafts.setAmount}
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
                        disabled={ops.busy}
                        onClick={() => {
                            const value = wholeNumber(drafts.amount, max)
                            if (value === null) return ops.reject("condition", `Enter a whole number from 1 to ${max}.`)
                            ops.run({
                                section: "condition",
                                operation,
                                body: { amount: value },
                                done: message,
                                after: () => drafts.setAmount(""),
                            })
                        }}
                    >
                        {label}
                    </button>
                ))}
            </form>
            <p>
                <button
                    type="button"
                    className="authoring-button"
                    disabled={ops.busy || view.attuned_to !== null}
                    onClick={() => setConfirmDestroy(true)}
                >
                    Destroy item
                </button>
                {view.attuned_to !== null ? (
                    <span className="authoring-field__hint"> End the attunement first.</span>
                ) : null}
            </p>
            <ConfirmDialog
                open={confirmDestroy}
                title="Destroy this item?"
                description="A destroyed item stays in history but takes no further changes. A mistaken destruction can be undone only while it is the item's latest event."
                confirmLabel="Destroy item"
                pending={ops.busy}
                onConfirm={() => {
                    setConfirmDestroy(false)
                    ops.run({ section: "condition", operation: "destroy", body: {}, done: "Item destroyed" })
                }}
                onCancel={() => setConfirmDestroy(false)}
            />
        </>
    )
}
