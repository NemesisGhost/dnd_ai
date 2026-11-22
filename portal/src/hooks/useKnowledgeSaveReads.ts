import { useCallback, useEffect, useRef, useState } from "react"
import { useAnnounce } from "../components/authoring/announcer"
import type { RefreshOutcome } from "./useAuthoringMutation"
import type { RefetchOutcome } from "./useAuthoringResource"
import { combineRefetchOutcomes } from "../utils/refreshOutcome"

// The reads a confirmed Knowledge claim save depends on, tracked for the save that owns them
// (docs/reference/portal-behavior.md §5.11). A claim save reads the claim's authoring view (its row
// version and editor) and the audience-safe detail; a lifecycle step reads those and the lifecycle.
// Each read is its own fact: one that failed does not make the others "behind", and a later read of
// the same resource that is applied satisfies every save still waiting for it, whoever started it.
export type SaveReadKey = "authoring" | "detail" | "lifecycle"
export type SaveKind = "claim" | "lifecycle"

type ReadState = "applied" | "outstanding"

interface SaveEpisode {
    id: number
    kind: SaveKind
    // What the write is announced as, once its last outstanding read is applied.
    done: string
    reads: Partial<Record<SaveReadKey, ReadState>>
}

// What a person is told is out of date, in the page's words, never a record's.
const PARTS: Record<SaveReadKey, string> = {
    authoring: "the claim's editor and version",
    detail: "the claim's details",
    lifecycle: "the claim's status",
}
const ORDER: readonly SaveReadKey[] = ["authoring", "detail", "lifecycle"]

const outstandingOf = (episode: SaveEpisode): SaveReadKey[] =>
    ORDER.filter((key) => episode.reads[key] === "outstanding")

export interface KnowledgeSaveReads {
    // Records a confirmed save and what each of its reads did. Returns what the mutation should
    // report: "ok" only when every read was applied (the caller then announces the write itself).
    // Otherwise the save is tracked here until every outstanding read has been applied, and it is
    // then announced as done exactly once.
    open: (
        kind: SaveKind,
        done: string,
        outcomes: Partial<Record<SaveReadKey, RefetchOutcome>>,
    ) => RefreshOutcome
    // A read the next claim save would send a row version from is outstanding for some save.
    authoringHeld: boolean
    // What is out of date for the open saves of this kind ("the claim's details"), or null.
    notice: (kind: SaveKind) => string | null
}

// `scope` names the record, perspective and user the page shows: a save recorded under another scope
// is forgotten. `applied` carries, per resource, a value that changes whenever a read of it is applied
// (null while there is none), so a read this hook did not start still counts.
export function useKnowledgeSaveReads({
    scope,
    applied,
}: {
    scope: string
    applied: Record<SaveReadKey, unknown>
}): KnowledgeSaveReads {
    const announce = useAnnounce()
    const [episodes, setEpisodes] = useState<SaveEpisode[]>([])
    const [seenScope, setSeenScope] = useState(scope)
    if (seenScope !== scope) {
        setSeenScope(scope)
        setEpisodes([])
    }
    const nextId = useRef(0)
    // Episodes already announced: an episode is announced once, whatever re-runs the effect below.
    const announced = useRef(new Set<number>())
    const announceRef = useRef(announce)
    useEffect(() => {
        announceRef.current = announce
    })

    // An applied read of a resource satisfies the saves waiting for it.
    const seen = useRef(applied)
    useEffect(() => {
        const previous = seen.current
        seen.current = applied
        const changed = ORDER.filter((key) => applied[key] !== null && applied[key] !== previous[key])
        if (changed.length === 0) return
        setEpisodes((current) =>
            current.some((episode) => changed.some((key) => episode.reads[key] === "outstanding"))
                ? current.map((episode) => ({
                      ...episode,
                      reads: Object.fromEntries(
                          Object.entries(episode.reads).map(([key, state]) => [
                              key,
                              changed.includes(key as SaveReadKey) ? "applied" : state,
                          ]),
                      ),
                  }))
                : current,
        )
    }, [applied.authoring, applied.detail, applied.lifecycle]) // eslint-disable-line react-hooks/exhaustive-deps

    // A save whose last read has been applied is announced as done, once. It is dropped from the list the
    // next time one is recorded or applied (`announced` is what keeps it from being announced again).
    useEffect(() => {
        for (const episode of episodes) {
            if (outstandingOf(episode).length > 0 || announced.current.has(episode.id)) continue
            announced.current.add(episode.id)
            announceRef.current(episode.done)
        }
    }, [episodes])

    const open = useCallback<KnowledgeSaveReads["open"]>((kind, done, outcomes) => {
        const reads: SaveEpisode["reads"] = {}
        for (const key of ORDER) {
            const outcome = outcomes[key]
            if (outcome !== undefined) reads[key] = outcome === "ok" ? "applied" : "outstanding"
        }
        const episode: SaveEpisode = { id: ++nextId.current, kind, done, reads }
        if (outstandingOf(episode).length > 0) {
            setEpisodes((current) => [...current.filter((other) => !announced.current.has(other.id)), episode])
        }
        return combineRefetchOutcomes(Object.values(outcomes))
    }, [])

    const notice = useCallback(
        (kind: SaveKind): string | null => {
            const keys = ORDER.filter((key) =>
                episodes.some((episode) => episode.kind === kind && episode.reads[key] === "outstanding"),
            )
            return keys.length === 0 ? null : `Out of date: ${keys.map((key) => PARTS[key]).join("; ")}.`
        },
        [episodes],
    )

    return {
        open,
        authoringHeld: episodes.some((episode) => episode.reads.authoring === "outstanding"),
        notice,
    }
}
