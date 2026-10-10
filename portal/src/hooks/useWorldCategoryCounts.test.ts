import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fetchWorldCategoryCounts } from "../api/world"
import type { WorldCategoryCounts } from "../types/world"
import { useWorldCategoryCounts } from "./useWorldCategoryCounts"

vi.mock("../api/world", () => ({ fetchWorldCategoryCounts: vi.fn() }))

const fetchMock = vi.mocked(fetchWorldCategoryCounts)

const counts = (total: number): WorldCategoryCounts => ({
    counts: { location: total, character: 0, organization: 0, religion: 0, item: 0, event: 0 },
    total,
})

interface Deferred {
    resolve: (value: WorldCategoryCounts) => void
    reject: (reason: unknown) => void
    signal: AbortSignal | undefined
}

let pending: Deferred[] = []

beforeEach(() => {
    pending = []
    fetchMock.mockReset()
    fetchMock.mockImplementation(
        (_campaign, _parameters, signal) =>
            new Promise<WorldCategoryCounts>((resolve, reject) => {
                pending.push({ resolve, reject, signal })
            }),
    )
})

afterEach(() => {
    vi.restoreAllMocks()
})

describe("useWorldCategoryCounts", () => {
    it("shows no counts while loading, then the server totals", async () => {
        const { result } = renderHook(() => useWorldCategoryCounts("c", "", false))

        expect(result.current).toBeNull()
        expect(fetchMock).toHaveBeenCalledWith("c", { query: "", includeHidden: false }, expect.anything())

        await act(async () => pending[0]!.resolve(counts(25)))

        expect(result.current).toEqual(counts(25))
    })

    it("shows no counts (not zeros) after a failure", async () => {
        const { result } = renderHook(() => useWorldCategoryCounts("c", "", false))

        await act(async () => pending[0]!.reject(new Error("boom")))

        expect(result.current).toBeNull()
    })

    it("hides the old totals while a new search loads and ignores a superseded answer", async () => {
        const { result, rerender } = renderHook(
            ({ q }) => useWorldCategoryCounts("c", q, false),
            { initialProps: { q: "" } },
        )
        await act(async () => pending[0]!.resolve(counts(25)))
        expect(result.current?.total).toBe(25)

        rerender({ q: "har" })
        expect(result.current).toBeNull()
        expect(fetchMock).toHaveBeenLastCalledWith("c", { query: "har", includeHidden: false }, expect.anything())

        rerender({ q: "harb" })
        expect(pending[1]!.signal?.aborted).toBe(true)

        // The older request answers last-but-late: it must not replace newer results.
        await act(async () => pending[2]!.resolve(counts(2)))
        await act(async () => pending[1]!.resolve(counts(9)))

        await waitFor(() => expect(result.current?.total).toBe(2))
    })

    it("refetches for a changed campaign or draft preview but not otherwise", async () => {
        const { rerender } = renderHook(
            ({ c, h }) => useWorldCategoryCounts(c, "", h),
            { initialProps: { c: "a", h: false } },
        )
        rerender({ c: "a", h: false })
        expect(fetchMock).toHaveBeenCalledTimes(1)

        rerender({ c: "a", h: true })
        rerender({ c: "b", h: true })
        expect(fetchMock).toHaveBeenCalledTimes(3)
    })
})
