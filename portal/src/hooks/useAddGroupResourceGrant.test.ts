import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AddGroupResourceGrantRequestError } from "../api/addGroupResourceGrant"
import { useAddGroupResourceGrant } from "./useAddGroupResourceGrant"
import type { ResourceGrantTarget } from "../types/resourceGrantTarget"

const { addGroupResourceGrantMock, reloadMock, sessionStateRef } = vi.hoisted(() => ({
    addGroupResourceGrantMock: vi.fn(),
    reloadMock: vi.fn(),
    sessionStateRef: {
        current: {
            status: "authenticated" as const,
            bootstrap: { csrf_token: "fixture-csrf-token" },
        },
    },
}))

vi.mock("../api/addGroupResourceGrant", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/addGroupResourceGrant")>()
    return { ...actual, addGroupResourceGrant: addGroupResourceGrantMock }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

const characterTarget: ResourceGrantTarget = { field: "character_id", id: "character-1" }

beforeEach(() => {
    addGroupResourceGrantMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useAddGroupResourceGrant", () => {
    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: { resource_grant_id: string }) => void
        addGroupResourceGrantMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() => useAddGroupResourceGrant("campaign-a", onSuccess))

        act(() => {
            result.current.submit("group-1", characterTarget, "character.view_summary", "allow")
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(addGroupResourceGrantMock).toHaveBeenCalledWith(
            "campaign-a",
            "group-1",
            characterTarget,
            "character.view_summary",
            "allow",
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )

        await act(async () => {
            resolveRequest({ resource_grant_id: "new-grant" })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("goes denied on a 403/404 response", async () => {
        addGroupResourceGrantMock.mockRejectedValue(new AddGroupResourceGrantRequestError(404))

        const { result } = renderHook(() => useAddGroupResourceGrant("campaign-a", vi.fn()))

        act(() => {
            result.current.submit("group-1", characterTarget, "character.view_summary", "allow")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })

    it("goes conflict on a 409 (inactive group/duplicate grant) response", async () => {
        addGroupResourceGrantMock.mockRejectedValue(new AddGroupResourceGrantRequestError(409))

        const { result } = renderHook(() => useAddGroupResourceGrant("campaign-a", vi.fn()))

        act(() => {
            result.current.submit("group-1", characterTarget, "character.view_summary", "allow")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })

    it("sends the deny effect through", async () => {
        addGroupResourceGrantMock.mockResolvedValue({ resource_grant_id: "new-grant" })

        const { result } = renderHook(() => useAddGroupResourceGrant("campaign-a", vi.fn()))

        act(() => {
            result.current.submit("group-1", characterTarget, "character.view_summary", "deny")
        })

        expect(addGroupResourceGrantMock).toHaveBeenCalledWith(
            "campaign-a",
            "group-1",
            characterTarget,
            "character.view_summary",
            "deny",
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )
    })
})
