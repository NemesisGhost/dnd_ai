import { useAuthoringResource } from "./useAuthoringResource"
import { useKept } from "./useKeptResource"

// One authoring read of a record together with the limits and choices its forms need, read as one
// thing: every section that uses it names the same version, and a failed refresh keeps what the
// last good read held so unsent input in those sections survives.
export interface PairedRead<T, O> {
    view: T | null
    options: O | null
    // "failed" is a read that did not succeed but may be tried again; "unavailable" is a denied or
    // missing answer, which fails closed.
    status: "loading" | "ready" | "failed" | "unavailable"
    // The latest read failed; `view` is the last one that succeeded.
    stale: boolean
    // Reads the record again.
    reload: () => Promise<void>
}

// A null path requests nothing (the record is not one this read applies to).
export function usePairedRead<T, O>(path: string | null, optionsPath: string | null): PairedRead<T, O> {
    const record = useAuthoringResource<T>(path)
    const options = useAuthoringResource<O>(optionsPath)
    const view = useKept(record.state)
    const choices = useKept(options.state)
    const closed =
        record.state.kind === "denied" ||
        record.state.kind === "unavailable" ||
        options.state.kind === "denied" ||
        options.state.kind === "unavailable"
    const status: PairedRead<T, O>["status"] = closed
        ? "unavailable"
        : view !== null && choices !== null
          ? "ready"
          : record.state.kind === "error" || options.state.kind === "error"
            ? "failed"
            : "loading"
    return {
        view: closed ? null : view,
        options: closed ? null : choices,
        status,
        stale: record.state.kind === "error" || options.state.kind === "error",
        reload: async () => {
            await Promise.all([record.refetch(), options.state.kind === "ready" ? Promise.resolve() : options.refetch()])
        },
    }
}
