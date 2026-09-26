import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { DeactivateAccessGroupRequestError } from "../api/deactivateAccessGroup"
import { useDeactivateAccessGroup } from "./useDeactivateAccessGroup"

const { deactivateAccessGroupMock, reloadMock, sessionStateRef } = vi.hoisted(
    () => ({
        deactivateAccessGroupMock: vi.fn(),
        reloadMock: vi.fn(),
        sessionStateRef: {
            current: {
                status: "authenticated" as const,
                bootstrap: { csrf_token: "fixture-csrf-token" },
            },
        },
    }),
)

vi.mock("../api/deactivateAccessGroup", async (importOriginal) => {
    const actual =
        await importOriginal<typeof import("../api/deactivateAccessGroup")>()
    return { ...actual, deactivateAccessGroup: deactivateAccessGroupMock }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

beforeEach(() => {
    deactivateAccessGroupMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useDeactivateAccessGroup", () => {
    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: {
            access_group_id: string
            name: string
        }) => void
        deactivateAccessGroupMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useDeactivateAccessGroup("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("group-1")
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(deactivateAccessGroupMock).toHaveBeenCalledWith(
            "campaign-a",
            "group-1",
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )

        await act(async () => {
            resolveRequest({ access_group_id: "group-1", name: "Lore Circle" })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("ignores a second submit while one is already pending", () => {
        deactivateAccessGroupMock.mockReturnValue(new Promise(() => {}))

        const { result } = renderHook(() =>
            useDeactivateAccessGroup("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("group-1")
        })
        act(() => {
            result.current.submit("group-1")
        })

        expect(deactivateAccessGroupMock).toHaveBeenCalledTimes(1)
    })

    it("goes denied on a 403/404 response", async () => {
        deactivateAccessGroupMock.mockRejectedValue(
            new DeactivateAccessGroupRequestError(404),
        )

        const { result } = renderHook(() =>
            useDeactivateAccessGroup("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("group-1")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })

    it("goes conflict on a 409 response", async () => {
        deactivateAccessGroupMock.mockRejectedValue(
            new DeactivateAccessGroupRequestError(409),
        )

        const { result } = renderHook(() =>
            useDeactivateAccessGroup("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("group-1")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })
})
