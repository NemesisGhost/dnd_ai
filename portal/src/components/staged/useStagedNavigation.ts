import { useEffect, useState } from "react"
import { useLocation, useSearchParams } from "react-router"

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
    const [params, setParams] = useSearchParams()
    // The router state names where the record was opened from; replacing the address must keep it.
    const { state } = useLocation()
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

    useEffect(() => {
        if (ready && (parsed === null || parsed !== requested)) {
            const next = new URLSearchParams(params)
            next.set("section", section)
            setParams(next, { replace: true, state })
        }
    }, [ready, parsed, requested, section, params, setParams, state])

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
