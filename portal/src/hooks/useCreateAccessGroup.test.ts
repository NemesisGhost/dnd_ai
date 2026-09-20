import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { CreateAccessGroupRequestError } from "../api/createAccessGroup"
import { useCreateAccessGroup } from "./useCreateAccessGroup"

const { createAccessGroupMock, reloadMock, sessionStateRef } = vi.hoisted(
    () => ({
        createAccessGroupMock: vi.fn(),
        reloadMock: vi.fn(),
        sessionStateRef: {
            current: {
                status: "authenticated" as const,
                bootstrap: { csrf_token: "fixture-csrf-token" },
            },
        },
    }),
)

vi.mock("../api/createAccessGroup", async (importOriginal) => {
    const actual =
        await importOriginal<typeof import("../api/createAccessGroup")>()
    return { ...actual, createAccessGroup: createAccessGroupMock }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

beforeEach(() => {
    createAccessGroupMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useCreateAccessGroup", () => {
    it("starts idle", () => {
        const { result } = renderHook(() =>
            useCreateAccessGroup("campaign-a", vi.fn()),
        )
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: {
            access_group_id: string
            name: string
        }) => void
        createAccessGroupMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useCreateAccessGroup("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("Lore Circle", "For lore fans")
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(createAccessGroupMock).toHaveBeenCalledWith(
            "campaign-a",
            "Lore Circle",
            "For lore fans",
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
        createAccessGroupMock.mockReturnValue(new Promise(() => {}))

        const { result } = renderHook(() =>
            useCreateAccessGroup("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("Lore Circle", null)
        })
        act(() => {
            result.current.submit("Second Group", null)
        })

        expect(createAccessGroupMock).toHaveBeenCalledTimes(1)
    })

    it("goes denied on a 403/404 response", async () => {
        createAccessGroupMock.mockRejectedValue(
            new CreateAccessGroupRequestError(403),
        )

        const { result } = renderHook(() =>
            useCreateAccessGroup("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("Lore Circle", null)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })

    it("goes conflict on a 409/400 response", async () => {
        createAccessGroupMock.mockRejectedValue(
            new CreateAccessGroupRequestError(409),
        )

        const { result } = renderHook(() =>
            useCreateAccessGroup("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("Lore Circle", null)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })

    it("goes error on any other failure", async () => {
        createAccessGroupMock.mockRejectedValue(
            new CreateAccessGroupRequestError(500),
        )

        const { result } = renderHook(() =>
            useCreateAccessGroup("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("Lore Circle", null)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })
    })

    it("resets to idle", async () => {
        createAccessGroupMock.mockRejectedValue(
            new CreateAccessGroupRequestError(500),
        )

        const { result } = renderHook(() =>
            useCreateAccessGroup("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("Lore Circle", null)
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.reset()
        })
        expect(result.current.status).toEqual({ kind: "idle" })
    })
})
