import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { useAnnounce } from "../components/authoring/announcer"
import type { RefreshOutcome } from "./useAuthoringMutation"
import type { RefetchOutcome } from "./useAuthoringResource"

// The reads a confirmed Knowledge claim save depends on, tracked for the save that owns them
// (docs/reference/portal-behavior.md §5.11). A claim save reads the claim's authoring view (its row
// version and editor) and the audience-safe detail; a lifecycle step reads those and the lifecycle.
// Each read is its own fact: one that failed does not make the others "behind", and a later read of
// the same resource that is applied satisfies every save still waiting for it, whoever started it.
export type SaveReadKey = "authoring" | "detail" | "lifecycle"
export type SaveKind = "claim" | "lifecycle"

// What one read did. "closed" is a refusal (403/404): an authoritative result, not a failure.
export type ReadOutcome = RefetchOutcome | "closed"

// applied      the read was applied.
// outstanding  the read failed recoverably: a read again may recover it.
// pending      the read was superseded by a newer one: that one's answer decides it.
// closed       the answer was a refusal: nothing is held for it, and nothing is read again.
type ReadState = "applied" | "outstanding" | "pending" | "closed"

interface SaveEpisode {
    id: number
    kind: SaveKind
    // What the write is announced as, once its last unresolved read is resolved.
    done: string
    reads: Partial<Record<SaveReadKey, ReadState>>
}

const SAVED_BUT = "Saved, but the latest data could not be loaded."

// What a person is told is out of date, in the page's words, never a record's.
const PARTS: Record<SaveReadKey, string> = {
    authoring: "the claim's editor and version",
    detail: "the claim's details",
    lifecycle: "the claim's status",
}
const ORDER: readonly SaveReadKey[] = ["authoring", "detail", "lifecycle"]

type Closed = { authoring: boolean; lifecycle: boolean }

// A read of a resource whose latest answer is a refusal is closed whatever it was waiting for.
function stateOf(episode: SaveEpisode, key: SaveReadKey, closed: Closed): ReadState | undefined {
    const state = episode.reads[key]
    if ((state === "outstanding" || state === "pending") && key !== "detail" && closed[key]) return "closed"
    return state
}
const keysIn = (episode: SaveEpisode, closed: Closed, ...states: ReadState[]): SaveReadKey[] =>
    ORDER.filter((key) => {
        const state = stateOf(episode, key, closed)
        return state !== undefined && states.includes(state)
    })
const unresolved = (episode: SaveEpisode, closed: Closed) => keysIn(episode, closed, "outstanding", "pending")

const stateFor = (outcome: ReadOutcome): ReadState =>
    outcome === "ok" ? "applied" : outcome === "closed" ? "closed" : outcome === "failed" ? "outstanding" : "pending"

// What the mutation (or the lifecycle panel) is told: "ok" when nothing is waiting on a failure or a
// newer read. A refusal is a result, so it does not make a write "behind".
export function reportOutcome(outcomes: Partial<Record<SaveReadKey, ReadOutcome>>): RefreshOutcome {
    const all = Object.values(outcomes)
    if (all.includes("failed")) return "failed"
    return all.includes("superseded") ? "superseded" : "ok"
}

export interface KnowledgeSaveReads {
    // The record, perspective and user these saves belong to. A caller captures it when its save is
    // confirmed and passes it back, so an answer that arrives after the page moved on changes nothing.
    scope: string
    // Records a confirmed save and what each of its reads did. Returns what the mutation (or lifecycle
    // panel) should report: "ok" when nothing is waiting. A claim save that is complete is announced here;
    // otherwise the save is tracked until every unresolved read is resolved, and is then announced as done
    // exactly once. A refusal of the detail replaces the page: the save is done and nothing is held.
    open: (
        kind: SaveKind,
        done: string,
        outcomes: Partial<Record<SaveReadKey, ReadOutcome>>,
        startedIn: string,
    ) => RefreshOutcome
    // What a read of a save's outstanding resources did, so the saves waiting on them can settle.
    observe: (outcomes: Partial<Record<SaveReadKey, ReadOutcome>>, startedIn: string) => void
    // The next claim save would send a row version from a read that has not been applied.
    authoringHeld: boolean
    // The reads of this kind's open saves that failed and may be read again.
    outstanding: (kind: SaveKind) => SaveReadKey[]
    // What is out of date for the open saves of this kind ("the claim's details"), or null.
    notice: (kind: SaveKind) => string | null
}

// `scope` names the record, perspective and user the page shows: a save recorded under another scope
// is forgotten. `applied` carries, per resource, a value that changes whenever a read of it is applied
// (null while there is none), so a read this hook did not start still counts. `closed` says a resource's
// latest answer is a refusal.
export function useKnowledgeSaveReads({
    scope,
    applied,
    closed,
}: {
    scope: string
    applied: Record<SaveReadKey, unknown>
    closed: Closed
}): KnowledgeSaveReads {
    const announce = useAnnounce()
    const [episodes, setEpisodes] = useState<SaveEpisode[]>([])
    const [seenScope, setSeenScope] = useState(scope)
    if (seenScope !== scope) {
        setSeenScope(scope)
        setEpisodes([])
    }
    const nextId = useRef(0)
    // Episodes already announced (done, or "saved, but"): each is announced once, whatever re-runs the effects.
    const announced = useRef(new Set<number>())
    const notified = useRef(new Set<number>())
    const live = useRef({ announce, scope, closed, mounted: false })
    useLayoutEffect(() => {
        live.current = { announce, scope, closed, mounted: true }
        return () => {
            live.current.mounted = false
        }
    })

    // An applied read of a resource satisfies the saves waiting for it.
    const seen = useRef(applied)
    useEffect(() => {
        const previous = seen.current
        seen.current = applied
        const changed = ORDER.filter((key) => applied[key] !== null && applied[key] !== previous[key])
        if (changed.length === 0) return
        setEpisodes((current) =>
            current.some((episode) => changed.some((key) => isWaiting(episode.reads[key])))
                ? current.map((episode) => ({
                      ...episode,
                      reads: Object.fromEntries(
                          Object.entries(episode.reads).map(([key, state]) => [
                              key,
                              changed.includes(key as SaveReadKey) && isWaiting(state) ? "applied" : state,
                          ]),
                      ),
                  }))
                : current,
        )
    }, [applied.authoring, applied.detail, applied.lifecycle]) // eslint-disable-line react-hooks/exhaustive-deps

    // A save whose last unresolved read is resolved is announced as done, once. It is dropped from the list
    // the next time one is recorded (`announced` is what keeps it from being announced again). A claim save
    // that has a read to read again says so once ("saved, but"), as the first failure of its read-back.
    useEffect(() => {
        for (const episode of episodes) {
            if (unresolved(episode, closed).length === 0) {
                if (announced.current.has(episode.id)) continue
                announced.current.add(episode.id)
                announce(episode.done)
            } else if (
                episode.kind === "claim" &&
                !notified.current.has(episode.id) &&
                keysIn(episode, closed, "outstanding").length > 0
            ) {
                notified.current.add(episode.id)
                announce(SAVED_BUT)
            }
        }
    }, [episodes, closed.authoring, closed.lifecycle, announce]) // eslint-disable-line react-hooks/exhaustive-deps

    const settle = useCallback(
        (current: SaveEpisode[], outcomes: Partial<Record<SaveReadKey, ReadOutcome>>): SaveEpisode[] =>
            current.map((episode) => {
                const reads = { ...episode.reads }
                for (const key of ORDER) {
                    const outcome = outcomes[key]
                    if (outcome !== undefined && isWaiting(reads[key])) reads[key] = stateFor(outcome)
                }
                return { ...episode, reads }
            }),
        [],
    )

    const open = useCallback<KnowledgeSaveReads["open"]>(
        (kind, done, outcomes, startedIn) => {
            const reported = reportOutcome(outcomes)
            // The page moved on (another record, perspective or user) while this save was being read back.
            if (startedIn !== live.current.scope) return reported
            // The detail was refused: the page is replaced by the unavailable result, the write is done, and
            // nothing is held or read again. A lifecycle step is announced by its panel on "ok".
            if (outcomes.detail === "closed") {
                if (kind === "claim" && live.current.mounted) live.current.announce(done)
                return "ok"
            }
            const reads: SaveEpisode["reads"] = {}
            for (const key of ORDER) {
                const outcome = outcomes[key]
                if (outcome !== undefined) reads[key] = stateFor(outcome)
            }
            const episode: SaveEpisode = { id: ++nextId.current, kind, done, reads }
            const complete = unresolved(episode, live.current.closed).length === 0
            setEpisodes((current) => [
                ...settle(current, outcomes).filter((other) => !announced.current.has(other.id)),
                ...(complete ? [] : [episode]),
            ])
            if (!complete) return reported
            if (kind === "claim" && live.current.mounted) live.current.announce(done)
            return "ok"
        },
        [settle],
    )

    const observe = useCallback<KnowledgeSaveReads["observe"]>(
        (outcomes, startedIn) => {
            if (startedIn !== live.current.scope) return
            setEpisodes((current) => settle(current, outcomes))
        },
        [settle],
    )

    const outstanding = useCallback(
        (kind: SaveKind): SaveReadKey[] =>
            ORDER.filter((key) =>
                episodes.some((episode) => episode.kind === kind && stateOf(episode, key, closed) === "outstanding"),
            ),
        [episodes, closed],
    )

    const notice = useCallback(
        (kind: SaveKind): string | null => {
            const keys = outstanding(kind)
            return keys.length === 0 ? null : `Out of date: ${keys.map((key) => PARTS[key]).join("; ")}.`
        },
        [outstanding],
    )

    return {
        scope,
        open,
        observe,
        authoringHeld: episodes.some((episode) => {
            const state = stateOf(episode, "authoring", closed)
            return state === "outstanding" || state === "pending"
        }),
        outstanding,
        notice,
    }
}

function isWaiting(state: ReadState | undefined): boolean {
    return state === "outstanding" || state === "pending"
}
