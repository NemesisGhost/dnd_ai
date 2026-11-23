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

        const { result } = renderHook(() => usePlatformAccounts(""))
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
        const { result } = renderHook(() => usePlatformAccounts(""))
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
        const { result } = renderHook(() => usePlatformAccounts(""))
        await waitFor(() => {
            expect(result.current.state).toEqual({ status: "denied" })
        })
    })

    it("takes the search from the page and starts over on a changed one", async () => {
        fetchPlatformAccountsMock.mockResolvedValue({ items: [], next_cursor: null })
        const { result } = renderHook(() => usePlatformAccounts("ali"))
        await waitFor(() => {
            expect(result.current.state.status).toBe("success")
        })
        expect(fetchPlatformAccountsMock).toHaveBeenCalledWith(
            { q: "ali", cursor: undefined },
            expect.anything(),
        )
    })

    it("resets the cursor when the query changes", async () => {
        fetchPlatformAccountsMock.mockResolvedValue({ items: [], next_cursor: "cursor-1" })
        const { result, rerender } = renderHook(({ q }) => usePlatformAccounts(q), {
            initialProps: { q: "" },
        })
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
        rerender({ q: "gm" })
        await waitFor(() => {
            expect(fetchPlatformAccountsMock).toHaveBeenCalledWith(
                { q: "gm", cursor: undefined },
                expect.anything(),
            )
        })
    })
})

describe("usePlatformAccounts.replaceAccount", () => {
    it("replaces the listed account in place: no loading state and no refetch", async () => {
        fetchPlatformAccountsMock.mockResolvedValue({
            items: [
                { user_id: "user-1", display_name: "Alice", system_roles: ["player"] },
                { user_id: "user-2", display_name: "Bob", system_roles: ["player"] },
            ],
            next_cursor: null,
        })
        const { result } = renderHook(() => usePlatformAccounts(""))
        await waitFor(() => expect(result.current.state.status).toBe("success"))

        act(() => result.current.replaceAccount({ user_id: "user-1", display_name: "Alice", system_roles: ["gm"] } as never))

        expect(result.current.state.status).toBe("success")
        expect(result.current.state).toMatchObject({
            items: [{ user_id: "user-1", system_roles: ["gm"] }, { user_id: "user-2", system_roles: ["player"] }],
        })
        expect(fetchPlatformAccountsMock).toHaveBeenCalledTimes(1)
    })

    it("does nothing for an account that is not listed or while loading", async () => {
        fetchPlatformAccountsMock.mockResolvedValue({ items: [{ user_id: "user-1" }], next_cursor: null })
        const { result } = renderHook(() => usePlatformAccounts(""))
        act(() => result.current.replaceAccount({ user_id: "user-1" } as never))
        expect(result.current.state).toEqual({ status: "loading" })
        await waitFor(() => expect(result.current.state.status).toBe("success"))
        act(() => result.current.replaceAccount({ user_id: "user-9", system_roles: ["gm"] } as never))
        expect(result.current.state).toMatchObject({ items: [{ user_id: "user-1" }] })
        expect((result.current.state as { items: unknown[] }).items).toHaveLength(1)
    })
})
