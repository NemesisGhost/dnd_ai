import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { usePlatformAccounts } from "./usePlatformAccounts"

const { fetchPlatformAccountsMock, reloadMock } = vi.hoisted(() => ({
    fetchPlatformAccountsMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock("../api/platformAccounts", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/platformAccounts")>()
    return {
        ...actual,
        fetchPlatformAccounts: fetchPlatformAccountsMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: { status: "authenticated" }, reload: reloadMock }),
}))

beforeEach(() => {
    fetchPlatformAccountsMock.mockReset()
    reloadMock.mockReset()
})

describe("usePlatformAccounts", () => {
    it("loads the first page", async () => {
        fetchPlatformAccountsMock.mockResolvedValue({
            items: [{ user_id: "user-1", display_name: "Admin" }],
            next_cursor: null,
        })

        const { result } = renderHook(() => usePlatformAccounts())
        expect(result.current.state).toEqual({ status: "loading" })

        await waitFor(() => {
            expect(result.current.state.status).toBe("success")
        })
        expect(fetchPlatformAccountsMock).toHaveBeenCalledWith(
            { q: undefined, cursor: undefined },
            expect.anything(),
        )
    })

    it("appends items on loadMore rather than replacing them", async () => {
        fetchPlatformAccountsMock.mockResolvedValueOnce({
            items: [{ user_id: "user-1" }],
            next_cursor: "cursor-1",
        })
        const { result } = renderHook(() => usePlatformAccounts())
        await waitFor(() => {
            expect(result.current.state.status).toBe("success")
        })

        fetchPlatformAccountsMock.mockResolvedValueOnce({
            items: [{ user_id: "user-2" }],
            next_cursor: null,
        })
        act(() => {
            result.current.loadMore()
        })

        await waitFor(() => {
            expect(result.current.state).toMatchObject({
                status: "success",
                items: [{ user_id: "user-1" }, { user_id: "user-2" }],
                nextCursor: null,
            })
        })
    })

    it("maps a 404 to denied, and 401 to a reload", async () => {
        fetchPlatformAccountsMock.mockRejectedValue(
            new PlatformAccountsRequestError(404, "not found"),
        )
        const { result } = renderHook(() => usePlatformAccounts())
        await waitFor(() => {
            expect(result.current.state).toEqual({ status: "denied" })
        })
    })

    it("resets the cursor when the query changes", async () => {
        fetchPlatformAccountsMock.mockResolvedValue({ items: [], next_cursor: "cursor-1" })
        const { result } = renderHook(() => usePlatformAccounts())
        await waitFor(() => {
            expect(result.current.state.status).toBe("success")
        })

        act(() => {
            result.current.loadMore()
        })
        await waitFor(() => {
            expect(fetchPlatformAccountsMock).toHaveBeenCalledWith(
                { q: undefined, cursor: "cursor-1" },
                expect.anything(),
            )
        })

        fetchPlatformAccountsMock.mockClear()
        act(() => {
            result.current.setQuery("gm")
        })
        await waitFor(() => {
            expect(fetchPlatformAccountsMock).toHaveBeenCalledWith(
                { q: "gm", cursor: undefined },
                expect.anything(),
            )
        })
    })
})
