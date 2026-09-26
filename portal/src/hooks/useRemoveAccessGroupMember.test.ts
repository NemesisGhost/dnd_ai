import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { RemoveAccessGroupMemberRequestError } from "../api/removeAccessGroupMember"
import { useRemoveAccessGroupMember } from "./useRemoveAccessGroupMember"

const { removeAccessGroupMemberMock, reloadMock, sessionStateRef } = vi.hoisted(
    () => ({
        removeAccessGroupMemberMock: vi.fn(),
        reloadMock: vi.fn(),
        sessionStateRef: {
            current: {
                status: "authenticated" as const,
                bootstrap: { csrf_token: "fixture-csrf-token" },
            },
        },
    }),
)

vi.mock("../api/removeAccessGroupMember", async (importOriginal) => {
    const actual =
        await importOriginal<typeof import("../api/removeAccessGroupMember")>()
    return { ...actual, removeAccessGroupMember: removeAccessGroupMemberMock }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

beforeEach(() => {
    removeAccessGroupMemberMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useRemoveAccessGroupMember", () => {
    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: {
            access_group_membership_id: string
        }) => void
        removeAccessGroupMemberMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useRemoveAccessGroupMember("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("link-1")
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(removeAccessGroupMemberMock).toHaveBeenCalledWith(
            "campaign-a",
            "link-1",
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )

        await act(async () => {
            resolveRequest({ access_group_membership_id: "link-1" })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("goes denied on a 403/404 response", async () => {
        removeAccessGroupMemberMock.mockRejectedValue(
            new RemoveAccessGroupMemberRequestError(404),
        )

        const { result } = renderHook(() =>
            useRemoveAccessGroupMember("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("link-1")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })
})
