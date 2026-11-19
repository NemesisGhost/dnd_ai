import { useCallback, useState } from "react"

interface DisclosureState {
    campaignId: string
    // Member cards that are expanded, and members whose access explanation is open, by the stable
    // campaign membership id (never by display name or list position).
    cards: ReadonlySet<string>
    explanations: ReadonlySet<string>
}

export interface AccessDisclosure {
    isCardOpen: (membershipId: string) => boolean
    setCardOpen: (membershipId: string, open: boolean) => void
    isExplanationOpen: (membershipId: string) => boolean
    toggleExplanation: (membershipId: string) => void
    // Forgets every id that is not in `current`, so a member who left cannot reopen by reappearing.
    prune: (current: ReadonlySet<string>) => void
}

const EMPTY: ReadonlySet<string> = new Set()

function fresh(campaignId: string): DisclosureState {
    return { campaignId, cards: EMPTY, explanations: EMPTY }
}

function withToggled(set: ReadonlySet<string>, id: string, present: boolean): ReadonlySet<string> {
    if (set.has(id) === present) return set
    const next = new Set(set)
    if (present) next.add(id)
    else next.delete(id)
    return next
}

// Which member cards and access explanations are open, held above the access overview boundary so
// they survive the overview's own reload. Scoped to the campaign: a state kept for another campaign
// reads as empty, so nothing carries over a campaign change. It holds only ids, never any access data.
export function useAccessDisclosure(campaignId: string): AccessDisclosure {
    const [state, setState] = useState<DisclosureState>(() => fresh(campaignId))
    const current = state.campaignId === campaignId ? state : fresh(campaignId)

    const update = useCallback(
        (change: (base: DisclosureState) => DisclosureState) => {
            setState((previous) => change(previous.campaignId === campaignId ? previous : fresh(campaignId)))
        },
        [campaignId],
    )

    const setCardOpen = useCallback(
        (id: string, open: boolean) =>
            update((base) => {
                const cards = withToggled(base.cards, id, open)
                return cards === base.cards ? base : { ...base, cards }
            }),
        [update],
    )
    const toggleExplanation = useCallback(
        (id: string) =>
            update((base) => ({ ...base, explanations: withToggled(base.explanations, id, !base.explanations.has(id)) })),
        [update],
    )
    const prune = useCallback(
        (keep: ReadonlySet<string>) =>
            update((base) => {
                const cards = new Set([...base.cards].filter((id) => keep.has(id)))
                const explanations = new Set([...base.explanations].filter((id) => keep.has(id)))
                if (cards.size === base.cards.size && explanations.size === base.explanations.size) return base
                return { ...base, cards, explanations }
            }),
        [update],
    )

    return {
        isCardOpen: (id) => current.cards.has(id),
        setCardOpen,
        isExplanationOpen: (id) => current.explanations.has(id),
        toggleExplanation,
        prune,
    }
}
