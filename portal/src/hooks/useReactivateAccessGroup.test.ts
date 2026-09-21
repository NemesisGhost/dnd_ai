import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ReactivateAccessGroupRequestError } from "../api/reactivateAccessGroup"
import { useReactivateAccessGroup } from "./useReactivateAccessGroup"

const { reactivateAccessGroupMock, reloadMock, sessionStateRef } = vi.hoisted(
    () => ({
        reactivateAccessGroupMock: vi.fn(),
        reloadMock: vi.fn(),
        sessionStateRef: {
            current: {
                status: "authenticated" as const,
                bootstrap: { csrf_token: "fixture-csrf-token" },
            },
        },
    }),
)

vi.mock("../api/reactivateAccessGroup", async (importOriginal) => {
    const actual =
        await importOriginal<typeof import("../api/reactivateAccessGroup")>()
    return { ...actual, reactivateAccessGroup: reactivateAccessGroupMock }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

beforeEach(() => {
    reactivateAccessGroupMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useReactivateAccessGroup", () => {
    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: {
            access_group_id: string
            name: string
        }) => void
        reactivateAccessGroupMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useReactivateAccessGroup("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("group-1")
        })

        expect(result.current.status).toEqual({ kind: "pending" })

        await act(async () => {
            resolveRequest({ access_group_id: "group-1", name: "Lore Circle" })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("goes conflict on a 409 (inactive campaign) response", async () => {
        reactivateAccessGroupMock.mockRejectedValue(
            new ReactivateAccessGroupRequestError(409),
        )

        const { result } = renderHook(() =>
            useReactivateAccessGroup("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("group-1")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })
})
