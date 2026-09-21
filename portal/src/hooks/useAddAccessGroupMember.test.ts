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
import { AddAccessGroupMemberRequestError } from "../api/addAccessGroupMember"
import type { AddAccessGroupMembersResponse } from "../types/accessGroup"
import { useAddAccessGroupMember } from "./useAddAccessGroupMember"

const {
    addAccessGroupMemberMock,
    reloadMock,
    sessionStateRef,
} = vi.hoisted(() => ({
    addAccessGroupMemberMock: vi.fn(),
    reloadMock: vi.fn(),
    sessionStateRef: {
        current: {
            status: "authenticated" as const,
            bootstrap: {
                csrf_token:
                    "fixture-csrf-token",
            },
        },
    },
}))

vi.mock(
    "../api/addAccessGroupMember",
    async (importOriginal) => {
        const actual =
            await importOriginal<
                typeof import("../api/addAccessGroupMember")
            >()

        return {
            ...actual,
            addAccessGroupMember:
                addAccessGroupMemberMock,
        }
    },
)

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    addAccessGroupMemberMock.mockReset()
    reloadMock.mockReset()

    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: {
            csrf_token:
                "fixture-csrf-token",
        },
    }
})

describe("useAddAccessGroupMember", () => {
    it("canonicalizes the selection, reports the added count, and reloads", async () => {
        const onSuccess = vi.fn()

        let resolveRequest!: (
            value: AddAccessGroupMembersResponse,
        ) => void

        addAccessGroupMemberMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useAddAccessGroupMember(
                "campaign-a",
                onSuccess,
            ),
        )

        act(() => {
            result.current.submit("group-1", [
                "membership-2",
                "membership-1",
                "membership-2",
            ])
        })

        expect(result.current.status).toEqual({
            kind: "pending",
        })

        expect(
            addAccessGroupMemberMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "group-1",
            [
                "membership-1",
                "membership-2",
            ],
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )

        await act(async () => {
            resolveRequest({
                access_group_membership_id: null,
                access_group_membership_ids: [
                    "link-1",
                    "link-2",
                ],
                added_count: 2,
            })
        })

        await waitFor(() => {
            expect(
                result.current.status,
            ).toEqual({
                kind: "success",
            })
        })

        expect(onSuccess).toHaveBeenCalledWith(2)
        expect(reloadMock).toHaveBeenCalledOnce()
    })

    it("goes denied on a 403 or 404 response", async () => {
        addAccessGroupMemberMock.mockRejectedValue(
            new AddAccessGroupMemberRequestError(
                404,
            ),
        )

        const { result } = renderHook(() =>
            useAddAccessGroupMember(
                "campaign-a",
                vi.fn(),
            ),
        )

        act(() => {
            result.current.submit("group-1", [
                "membership-1",
            ])
        })

        await waitFor(() => {
            expect(
                result.current.status,
            ).toEqual({
                kind: "denied",
            })
        })
    })

    it("goes conflict on a 409 response", async () => {
        addAccessGroupMemberMock.mockRejectedValue(
            new AddAccessGroupMemberRequestError(
                409,
            ),
        )

        const { result } = renderHook(() =>
            useAddAccessGroupMember(
                "campaign-a",
                vi.fn(),
            ),
        )

        act(() => {
            result.current.submit("group-1", [
                "membership-1",
            ])
        })

        await waitFor(() => {
            expect(
                result.current.status,
            ).toEqual({
                kind: "conflict",
            })
        })
    })

    it("reuses the idempotency key for the same logical set", async () => {
        addAccessGroupMemberMock.mockRejectedValue(
            new Error("network failure"),
        )

        const { result } = renderHook(() =>
            useAddAccessGroupMember(
                "campaign-a",
                vi.fn(),
            ),
        )

        act(() => {
            result.current.submit("group-1", [
                "membership-2",
                "membership-1",
                "membership-2",
            ])
        })

        await waitFor(() => {
            expect(
                result.current.status,
            ).toEqual({
                kind: "error",
            })
        })

        const firstKey =
            addAccessGroupMemberMock.mock
                .calls[0][4]

        act(() => {
            result.current.submit("group-1", [
                "membership-1",
                "membership-2",
            ])
        })

        await waitFor(() => {
            expect(
                addAccessGroupMemberMock,
            ).toHaveBeenCalledTimes(2)
        })

        const secondKey =
            addAccessGroupMemberMock.mock
                .calls[1][4]

        expect(secondKey).toBe(firstKey)

        expect(
            addAccessGroupMemberMock.mock
                .calls[0][2],
        ).toEqual([
            "membership-1",
            "membership-2",
        ])

        expect(
            addAccessGroupMemberMock.mock
                .calls[1][2],
        ).toEqual([
            "membership-1",
            "membership-2",
        ])
    })

    it("does not request an empty selection", () => {
        const { result } = renderHook(() =>
            useAddAccessGroupMember(
                "campaign-a",
                vi.fn(),
            ),
        )

        act(() => {
            result.current.submit(
                "group-1",
                [],
            )
        })

        expect(
            addAccessGroupMemberMock,
        ).not.toHaveBeenCalled()

        expect(result.current.status).toEqual({
            kind: "idle",
        })
    })
})