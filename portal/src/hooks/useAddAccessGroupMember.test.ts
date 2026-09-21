import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AddAccessGroupMemberRequestError } from "../api/addAccessGroupMember"
import { useAddAccessGroupMember } from "./useAddAccessGroupMember"

const { addAccessGroupMemberMock, reloadMock, sessionStateRef } = vi.hoisted(
    () => ({
        addAccessGroupMemberMock: vi.fn(),
        reloadMock: vi.fn(),
        sessionStateRef: {
            current: {
                status: "authenticated" as const,
                bootstrap: { csrf_token: "fixture-csrf-token" },
            },
        },
    }),
)

vi.mock("../api/addAccessGroupMember", async (importOriginal) => {
    const actual =
        await importOriginal<typeof import("../api/addAccessGroupMember")>()
    return { ...actual, addAccessGroupMember: addAccessGroupMemberMock }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

beforeEach(() => {
    addAccessGroupMemberMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useAddAccessGroupMember", () => {
    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: {
            access_group_membership_id: string
        }) => void
        addAccessGroupMemberMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useAddAccessGroupMember("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("group-1", ["membership-1"])
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(addAccessGroupMemberMock).toHaveBeenCalledWith(
            "campaign-a",
            "group-1",
            ["membership-1"],
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
        addAccessGroupMemberMock.mockRejectedValue(
            new AddAccessGroupMemberRequestError(404),
        )

        const { result } = renderHook(() =>
            useAddAccessGroupMember("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("group-1", ["membership-1"])
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })

    it("goes conflict on a 409 (duplicate/ineligible) response", async () => {
        addAccessGroupMemberMock.mockRejectedValue(
            new AddAccessGroupMemberRequestError(409),
        )

        const { result } = renderHook(() =>
            useAddAccessGroupMember("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("group-1", ["membership-1"])
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })
})
