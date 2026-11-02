import { useState } from "react"
import type { ReferenceOption } from "../authoring/ReferenceCombobox"

export type MoveAction = "give" | "place"
// Who owns the item afterwards. There is no default: ownership is its own decision.
export type OwnershipChoice = "keep" | "recipient"

export interface ItemDrafts {
    // The world time of the next command (empty: the campaign clock).
    when: string
    setWhen: (value: string) => void
    // Choosing an action only reveals its inputs; nothing is sent.
    action: MoveAction | null
    setAction: (value: MoveAction | null) => void
    holder: ReferenceOption | null
    setHolder: (value: ReferenceOption | null) => void
    quantity: string
    setQuantity: (value: string) => void
    ownership: OwnershipChoice | null
    setOwnership: (value: OwnershipChoice | null) => void
    place: ReferenceOption | null
    setPlace: (value: ReferenceOption | null) => void
    amount: string
    setAmount: (value: string) => void
    clearGive: () => void
    clearPlace: () => void
    // What has been entered and not yet sent, named for the unsaved-input guard.
    unsaved: string[]
}

// Everything typed or chosen in the Use-in-play sections. It lives above the sections (which are
// all mounted) so switching stage, a refused command or a reload of the item never discards it,
// and each section clears only what its own successful command consumed.
export function useItemDrafts(): ItemDrafts {
    const [when, setWhen] = useState("")
    const [action, setAction] = useState<MoveAction | null>(null)
    const [holder, setHolder] = useState<ReferenceOption | null>(null)
    const [quantity, setQuantity] = useState("1")
    const [ownership, setOwnership] = useState<OwnershipChoice | null>(null)
    const [place, setPlace] = useState<ReferenceOption | null>(null)
    const [amount, setAmount] = useState("")
    const unsaved = [
        holder !== null || ownership !== null || quantity !== "1" ? "giving it away" : null,
        place !== null ? "where to place it" : null,
        amount.trim() !== "" ? "an amount" : null,
    ].filter((part) => part !== null)
    return {
        when,
        setWhen,
        action,
        setAction,
        holder,
        setHolder,
        quantity,
        setQuantity,
        ownership,
        setOwnership,
        place,
        setPlace,
        amount,
        setAmount,
        clearGive: () => {
            setHolder(null)
            setOwnership(null)
            setQuantity("1")
        },
        clearPlace: () => setPlace(null),
        unsaved,
    }
}
