import { useAuthoringResource } from "./useAuthoringResource"
import type { RefetchOutcome, UseAuthoringResourceResult } from "./useAuthoringResource"

// The result of a read that was never sent because the server has not said it is the caller's to
// make. It reads as "denied" so every consumer already has the right words for it, and it has no
// request to retry.
const WITHHELD = {
    state: { kind: "denied" },
    refetch: async (): Promise<RefetchOutcome> => "failed",
    refreshOk: { current: false },
} as const

// An authoring read that is sent only while `allowed`. Use it for the private side of a record: the
// server's per-record eligibility (`authoring.can_read_private`, utils/recordAuthoring) says whether
// the read is the caller's to make, and a read that would be refused is not issued at all, so a
// denied preparation section can never blank or delay an otherwise permitted published or runtime
// record. When `allowed` turns false the data already held is dropped with the request.
export function useGatedAuthoringResource<T>(path: string, allowed: boolean): UseAuthoringResourceResult<T> {
    const resource = useAuthoringResource<T>(allowed ? path : null)
    return allowed ? resource : (WITHHELD as UseAuthoringResourceResult<T>)
}
