import { useContext, useLayoutEffect, useState } from "react"
import { UNSAFE_DataRouterContext, useLocation, useNavigate, useSearchParams } from "react-router"
import { replaceOwnEntry } from "../../navigation/replaceOwnEntry"

export interface StagedSectionRef<S extends string, K extends string> {
    key: K
    stage: S
}

export interface StagedNavigation<S extends string, K extends string> {
    section: K
    stage: S
    // The address (query only) that opens a section. Every other query parameter is carried along.
    sectionHref: (key: K) => string
    // The address of a stage: its remembered section, else its first.
    stageHref: (stage: S) => string
}

// The current section lives in `?section=`; the stage follows from it. A user's change pushes a
// history entry (Back and Forward walk the sections); fixing a missing or unknown value replaces
// it. The query is the only thing that changes, so the page stays mounted and drafts survive.
// `sections` are the ones this record has; a key that is not among them is unknown. `ready` holds
// the normalisation back until the default can be derived from the loaded record. `aliases` maps a
// section key an older address may still carry to the section that replaced it; the address is
// rewritten (replacing the entry) once `ready`, and only when that section exists on this record.
export function useStagedNavigation<S extends string, K extends string>(
    sections: readonly StagedSectionRef<S, K>[],
    defaultSection: K,
    { ready, aliases }: { ready: boolean; aliases?: Readonly<Record<string, K>> },
): StagedNavigation<S, K> {
    const [params] = useSearchParams()
    const navigate = useNavigate()
    const dataRouter = useContext(UNSAFE_DataRouterContext)?.router ?? null
    // The entry this render is for. The write below is owned by it (see the effect).
    const location = useLocation()
    const requested = params.get("section")
    const aliased: string | null =
        requested !== null && aliases !== undefined && Object.prototype.hasOwnProperty.call(aliases, requested)
            ? aliases[requested]!
            : requested
    const parsed = sections.find((s) => s.key === aliased)?.key ?? null
    const section = parsed ?? defaultSection
    const stageOf = (key: K): S => (sections.find((s) => s.key === key) ?? sections[0]!).stage
    const stage = stageOf(section)
    const [remembered, setRemembered] = useState<Partial<Record<S, K>>>({})

    // A layout effect, not a passive one: a passive effect can be flushed after a person has already
    // followed a section link (React runs a pending one at the start of the render that link causes),
    // and its closure still holds the address from before, so it would replace the section they just
    // chose with the default. In a layout effect nothing can happen between the render and this.
    //
    // The write belongs to this entry (navigation/replaceOwnEntry.ts, the one implementation of entry-bound
    // replacements): it is made only while the router's actual current location is still this entry and
    // nothing is pending or waiting on a decision, and it is abandoned the moment a newer location exists
    // (PUSH, POP, another REPLACE) or the effect is cleaned up. The query and state are taken from the
    // router's own copy of the entry, so a render that lags a departure can neither overwrite the
    // destination nor cut across a blocked navigation. A kept (Stay) entry is normalized afterwards; a left
    // one is never touched. The mark (navigation/entryStamp.ts) only declares what the write is.
    useLayoutEffect(() => {
        if (ready && (parsed === null || parsed !== requested)) {
            return replaceOwnEntry({
                router: dataRouter,
                navigate,
                location,
                entryKey: location.key,
                writer: "normalization",
                next: (current) => {
                    const query = new URLSearchParams(current.search)
                    query.set("section", section)
                    // The router state names where the record was opened from; replacing the address must
                    // keep it. An object is needed to carry the mark; an entry with no object state has no
                    // selection arrival to keep.
                    const state: unknown =
                        typeof current.state === "object" && current.state !== null ? { ...current.state } : current.state
                    // The address is rewritten without a fragment, as before: an older address may carry one
                    // that the page maps to a section (aliases).
                    return { search: `?${query.toString()}`, state, hash: "" }
                },
            })
        }
        return undefined
    }, [ready, parsed, requested, section, dataRouter, navigate, location])

    // Remember the section last shown in each stage (adjusted during render, not in an effect).
    if (remembered[stage] !== section) {
        setRemembered({ ...remembered, [stage]: section })
    }

    const sectionHref = (key: K): string => {
        const next = new URLSearchParams(params)
        next.set("section", key)
        return `?${next.toString()}`
    }
    const stageHref = (target: S): string =>
        sectionHref(
            target === stage
                ? section
                : (remembered[target] ?? sections.find((s) => s.stage === target)?.key ?? section),
        )
    return { section, stage, sectionHref, stageHref }
}
