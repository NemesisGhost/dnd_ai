import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { UpdateAccessGroupRequestError } from "../api/updateAccessGroup"
import { useUpdateAccessGroup } from "./useUpdateAccessGroup"

const { updateAccessGroupMock, reloadMock, sessionStateRef } = vi.hoisted(
    () => ({
        updateAccessGroupMock: vi.fn(),
        reloadMock: vi.fn(),
        sessionStateRef: {
            current: {
                status: "authenticated" as const,
                bootstrap: { csrf_token: "fixture-csrf-token" },
            },
        },
    }),
)

vi.mock("../api/updateAccessGroup", async (importOriginal) => {
    const actual =
        await importOriginal<typeof import("../api/updateAccessGroup")>()
    return { ...actual, updateAccessGroup: updateAccessGroupMock }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

beforeEach(() => {
    updateAccessGroupMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useUpdateAccessGroup", () => {
    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: {
            access_group_id: string
            name: string
        }) => void
        updateAccessGroupMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useUpdateAccessGroup("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("group-1", "Renamed", null)
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(updateAccessGroupMock).toHaveBeenCalledWith(
            "campaign-a",
            "group-1",
            "Renamed",
            null,
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )

        await act(async () => {
            resolveRequest({ access_group_id: "group-1", name: "Renamed" })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("goes denied on a 403/404 response", async () => {
        updateAccessGroupMock.mockRejectedValue(
            new UpdateAccessGroupRequestError(404),
        )

        const { result } = renderHook(() =>
            useUpdateAccessGroup("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("group-1", "Renamed", null)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })

    it("goes conflict on a 409/400 response (including a no-op or duplicate name)", async () => {
        updateAccessGroupMock.mockRejectedValue(
            new UpdateAccessGroupRequestError(409),
        )

        const { result } = renderHook(() =>
            useUpdateAccessGroup("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("group-1", "Renamed", null)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })
})
