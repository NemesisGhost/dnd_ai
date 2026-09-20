import {
    act,
    renderHook,
    waitFor,
} from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { AuditHistoryRequestError } from "../api/auditHistory"
import {
    EMPTY_AUDIT_HISTORY_FILTERS,
} from "../types/auditHistory"
import type {
    AuditHistoryFilters,
    AuditHistoryItem,
    AuditHistoryPage,
} from "../types/auditHistory"
import { useAuditHistory } from "./useAuditHistory"

const { fetchAuditHistoryMock, reloadMock } = vi.hoisted(
    () => ({
        fetchAuditHistoryMock: vi.fn(),
        reloadMock: vi.fn(),
    }),
)

vi.mock("../api/auditHistory", async (importOriginal) => {
    const actual =
        await importOriginal<
            typeof import("../api/auditHistory")
        >()
    return {
        ...actual,
        fetchAuditHistory: fetchAuditHistoryMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        reload: reloadMock,
    }),
}))

function item(id: number, label: string): AuditHistoryItem {
    return {
        change_log_id: id,
        occurred_at: "2026-09-18T21:00:00Z",
        category: "role",
        action_label: label,
        actor_label: "GM Alex",
        actor_type: "user",
        target_label: "Player Sam",
        target_type: "account",
        change_summary: null,
        outcome: null,
    }
}

beforeEach(() => {
    fetchAuditHistoryMock.mockReset()
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

describe("useAuditHistory", () => {
    it("loads the first page for a campaign", async () => {
        const page: AuditHistoryPage = {
            items: [item(1, "Role changed")],
            next_cursor: "cursor-1",
        }
        fetchAuditHistoryMock.mockResolvedValue(page)

        const { result } = renderHook(() =>
            useAuditHistory(
                "campaign-a",
                EMPTY_AUDIT_HISTORY_FILTERS,
            ),
        )

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                items: page.items,
                nextCursor: "cursor-1",
                isLoadingMore: false,
                loadMoreError: false,
            })
        })

        expect(fetchAuditHistoryMock).toHaveBeenCalledWith(
            "campaign-a",
            EMPTY_AUDIT_HISTORY_FILTERS,
            null,
            expect.any(AbortSignal),
        )
    })

    it.each([403, 404])(
        "treats HTTP %s as unavailable",
        async (status) => {
            fetchAuditHistoryMock.mockRejectedValue(
                new AuditHistoryRequestError(status),
            )

            const { result } = renderHook(() =>
                useAuditHistory(
                    "campaign-a",
                    EMPTY_AUDIT_HISTORY_FILTERS,
                ),
            )

            await waitFor(() => {
                expect(result.current.state).toEqual({
                    status: "unavailable",
                })
            })
        },
    )

    it("reloads the session after an unauthorized response", async () => {
        fetchAuditHistoryMock.mockRejectedValue(
            new AuditHistoryRequestError(401),
        )

        renderHook(() =>
            useAuditHistory(
                "campaign-a",
                EMPTY_AUDIT_HISTORY_FILTERS,
            ),
        )

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
    })

    it("returns a recoverable error for other failures and supports retry", async () => {
        const requestError = new Error("boom")
        fetchAuditHistoryMock
            .mockRejectedValueOnce(requestError)
            .mockResolvedValueOnce({
                items: [item(1, "Role changed")],
                next_cursor: null,
            })

        const { result } = renderHook(() =>
            useAuditHistory(
                "campaign-a",
                EMPTY_AUDIT_HISTORY_FILTERS,
            ),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "error",
                error: requestError,
            })
        })

        act(() => {
            result.current.retry()
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state.status).toBe(
                "success",
            )
        })

        expect(fetchAuditHistoryMock).toHaveBeenCalledTimes(
            2,
        )
    })

    it("resets to loading and aborts the in-flight request when the campaign changes", async () => {
        let resolveFirst:
            | ((page: AuditHistoryPage) => void)
            | undefined
        const firstRequest = new Promise<AuditHistoryPage>(
            (resolve) => {
                resolveFirst = resolve
            },
        )
        let firstSignal: AbortSignal | undefined

        fetchAuditHistoryMock.mockImplementationOnce(
            (
                _campaignId: string,
                _filters: AuditHistoryFilters,
                _cursor: string | null,
                signal?: AbortSignal,
            ) => {
                firstSignal = signal
                return firstRequest
            },
        )
        fetchAuditHistoryMock.mockResolvedValueOnce({
            items: [item(2, "Member added")],
            next_cursor: null,
        })

        const { result, rerender } = renderHook(
            ({ campaignId }: { campaignId: string }) =>
                useAuditHistory(
                    campaignId,
                    EMPTY_AUDIT_HISTORY_FILTERS,
                ),
            { initialProps: { campaignId: "campaign-a" } },
        )

        await waitFor(() => {
            expect(firstSignal).toBeDefined()
        })

        rerender({ campaignId: "campaign-b" })

        expect(result.current.state).toEqual({
            status: "loading",
        })
        expect(firstSignal?.aborted).toBe(true)

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                items: [item(2, "Member added")],
                nextCursor: null,
                isLoadingMore: false,
                loadMoreError: false,
            })
        })

        // The first (aborted, campaign-a) request resolving late must
        // never overwrite campaign-b's already-successful state.
        act(() => {
            resolveFirst?.({
                items: [item(1, "Role changed")],
                next_cursor: null,
            })
        })

        expect(result.current.state).toEqual({
            status: "success",
            items: [item(2, "Member added")],
            nextCursor: null,
            isLoadingMore: false,
            loadMoreError: false,
        })
    })

    it("resets to loading when the filters change", async () => {
        fetchAuditHistoryMock.mockResolvedValue({
            items: [item(1, "Role changed")],
            next_cursor: null,
        })

        const { result, rerender } = renderHook(
            ({
                filters,
            }: {
                filters: AuditHistoryFilters
            }) => useAuditHistory("campaign-a", filters),
            {
                initialProps: {
                    filters: EMPTY_AUDIT_HISTORY_FILTERS,
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state.status).toBe(
                "success",
            )
        })

        rerender({
            filters: {
                ...EMPTY_AUDIT_HISTORY_FILTERS,
                category: "role",
            },
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(fetchAuditHistoryMock).toHaveBeenCalledWith(
                "campaign-a",
                {
                    ...EMPTY_AUDIT_HISTORY_FILTERS,
                    category: "role",
                },
                null,
                expect.any(AbortSignal),
            )
        })
    })

    it("appends a loadMore page to the existing items", async () => {
        fetchAuditHistoryMock
            .mockResolvedValueOnce({
                items: [item(1, "Role changed")],
                next_cursor: "cursor-1",
            })
            .mockResolvedValueOnce({
                items: [item(2, "Member added")],
                next_cursor: null,
            })

        const { result } = renderHook(() =>
            useAuditHistory(
                "campaign-a",
                EMPTY_AUDIT_HISTORY_FILTERS,
            ),
        )

        await waitFor(() => {
            expect(result.current.state.status).toBe(
                "success",
            )
        })

        act(() => {
            result.current.loadMore()
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                items: [
                    item(1, "Role changed"),
                    item(2, "Member added"),
                ],
                nextCursor: null,
                isLoadingMore: false,
                loadMoreError: false,
            })
        })

        expect(fetchAuditHistoryMock).toHaveBeenLastCalledWith(
            "campaign-a",
            EMPTY_AUDIT_HISTORY_FILTERS,
            "cursor-1",
            expect.any(AbortSignal),
        )
    })

    it("keeps existing items and reports loadMoreError on a loadMore failure", async () => {
        fetchAuditHistoryMock
            .mockResolvedValueOnce({
                items: [item(1, "Role changed")],
                next_cursor: "cursor-1",
            })
            .mockRejectedValueOnce(new Error("network down"))

        const { result } = renderHook(() =>
            useAuditHistory(
                "campaign-a",
                EMPTY_AUDIT_HISTORY_FILTERS,
            ),
        )

        await waitFor(() => {
            expect(result.current.state.status).toBe(
                "success",
            )
        })

        act(() => {
            result.current.loadMore()
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                items: [item(1, "Role changed")],
                nextCursor: "cursor-1",
                isLoadingMore: false,
                loadMoreError: true,
            })
        })
    })

    it("discards a loadMore response for a campaign the hook has already navigated away from", async () => {
        let resolveLoadMore:
            | ((page: AuditHistoryPage) => void)
            | undefined
        const loadMoreRequest = new Promise<AuditHistoryPage>(
            (resolve) => {
                resolveLoadMore = resolve
            },
        )

        fetchAuditHistoryMock
            .mockResolvedValueOnce({
                items: [item(1, "Role changed")],
                next_cursor: "cursor-1",
            })
            .mockReturnValueOnce(loadMoreRequest)
            .mockResolvedValueOnce({
                items: [item(3, "Campaign B event")],
                next_cursor: null,
            })

        const { result, rerender } = renderHook(
            ({ campaignId }: { campaignId: string }) =>
                useAuditHistory(
                    campaignId,
                    EMPTY_AUDIT_HISTORY_FILTERS,
                ),
            { initialProps: { campaignId: "campaign-a" } },
        )

        await waitFor(() => {
            expect(result.current.state.status).toBe(
                "success",
            )
        })

        act(() => {
            result.current.loadMore()
        })

        rerender({ campaignId: "campaign-b" })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                items: [item(3, "Campaign B event")],
                nextCursor: null,
                isLoadingMore: false,
                loadMoreError: false,
            })
        })

        act(() => {
            resolveLoadMore?.({
                items: [item(2, "Stale campaign-a item")],
                next_cursor: null,
            })
        })

        expect(result.current.state).toEqual({
            status: "success",
            items: [item(3, "Campaign B event")],
            nextCursor: null,
            isLoadingMore: false,
            loadMoreError: false,
        })
    })
})
