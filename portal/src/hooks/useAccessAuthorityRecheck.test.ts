import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AddGroupResourceGrantRequestError } from "../api/addGroupResourceGrant"
import { AddResourceGrantRequestError } from "../api/addResourceGrant"
import { RevokeResourceGrantRequestError } from "../api/revokeResourceGrant"
import { useAddGroupResourceGrant } from "./useAddGroupResourceGrant"
import { useAddResourceGrant } from "./useAddResourceGrant"
import { useRevokeResourceGrant } from "./useRevokeResourceGrant"

// P15-C02-S04 (D-4): a 403 from any resource-grant write reads the session again IN PLACE, so a lost
// `access.manage` can unmount the page; a 404 or anything else does not, and the status the hook reports is
// unchanged. The read falls back to the full reload when it was not applied.

const { addMock, addGroupMock, revokeMock, reloadMock, refreshMock } = vi.hoisted(() => ({
    addMock: vi.fn(),
    addGroupMock: vi.fn(),
    revokeMock: vi.fn(),
    reloadMock: vi.fn(),
    refreshMock: vi.fn(),
}))

vi.mock("../api/addResourceGrant", async (importOriginal) => ({
    ...(await importOriginal<typeof import("../api/addResourceGrant")>()),
    addResourceGrant: addMock,
}))
vi.mock("../api/addGroupResourceGrant", async (importOriginal) => ({
    ...(await importOriginal<typeof import("../api/addGroupResourceGrant")>()),
    addGroupResourceGrant: addGroupMock,
}))
vi.mock("../api/revokeResourceGrant", async (importOriginal) => ({
    ...(await importOriginal<typeof import("../api/revokeResourceGrant")>()),
    revokeResourceGrant: revokeMock,
}))
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: { status: "authenticated", bootstrap: { csrf_token: "fixture-csrf-token" } },
        reload: reloadMock,
        refresh: refreshMock,
    }),
}))

beforeEach(() => {
    for (const mock of [addMock, addGroupMock, revokeMock, reloadMock, refreshMock]) mock.mockReset()
    refreshMock.mockResolvedValue(true)
})

const target = { field: "entity_id" as const, id: "character-a" }

interface Case {
    name: string
    reject: (status: number) => void
    run: () => { result: { current: { status: { kind: string }; submit: (...args: never[]) => void } } }
    submit: (hook: { submit: (...args: never[]) => void }) => void
}

const cases: Case[] = [
    {
        name: "useAddResourceGrant",
        reject: (status) => addMock.mockRejectedValue(new AddResourceGrantRequestError(status)),
        run: () => renderHook(() => useAddResourceGrant("campaign-a", vi.fn())) as never,
        submit: (hook) =>
            (hook.submit as unknown as (...a: unknown[]) => void)("membership-a", target, "canon.edit", "deny"),
    },
    {
        name: "useAddGroupResourceGrant",
        reject: (status) => addGroupMock.mockRejectedValue(new AddGroupResourceGrantRequestError(status)),
        run: () => renderHook(() => useAddGroupResourceGrant("campaign-a", vi.fn())) as never,
        submit: (hook) =>
            (hook.submit as unknown as (...a: unknown[]) => void)("group-a", target, "canon.edit", "deny"),
    },
    {
        name: "useRevokeResourceGrant",
        reject: (status) => revokeMock.mockRejectedValue(new RevokeResourceGrantRequestError(status)),
        run: () => renderHook(() => useRevokeResourceGrant("campaign-a", vi.fn())) as never,
        submit: (hook) => (hook.submit as unknown as (...a: unknown[]) => void)("grant-a"),
    },
]

describe.each(cases)("$name: a refused write and the session", (c) => {
    it("reads the session once in place on a 403, without reloading, and still reports denied", async () => {
        c.reject(403)
        const { result } = c.run()
        act(() => c.submit(result.current))
        await waitFor(() => expect(result.current.status).toEqual({ kind: "denied" }))
        await waitFor(() => expect(refreshMock).toHaveBeenCalledTimes(1))
        expect(refreshMock.mock.calls[0]![0]).toBeInstanceOf(AbortSignal)
        expect(reloadMock).not.toHaveBeenCalled()
    })

    it("falls back to the full reload when the in-place read was not applied", async () => {
        refreshMock.mockResolvedValue(false)
        c.reject(403)
        const { result } = c.run()
        act(() => c.submit(result.current))
        await waitFor(() => expect(reloadMock).toHaveBeenCalledTimes(1))
    })

    it("does not read the session for a 404 or an unknown failure", async () => {
        c.reject(404)
        const first = c.run()
        act(() => c.submit(first.result.current))
        await waitFor(() => expect(first.result.current.status).toEqual({ kind: "denied" }))
        c.reject(500)
        const second = c.run()
        act(() => c.submit(second.result.current))
        await waitFor(() => expect(second.result.current.status).toEqual({ kind: "error" }))
        expect(refreshMock).not.toHaveBeenCalled()
        expect(reloadMock).not.toHaveBeenCalled()
    })
})
