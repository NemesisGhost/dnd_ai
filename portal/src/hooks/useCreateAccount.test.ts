import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { useCreateAccount } from "./useCreateAccount"

const { createAccountMock, reloadMock, sessionStateRef } = vi.hoisted(() => ({
    createAccountMock: vi.fn(),
    reloadMock: vi.fn(),
    sessionStateRef: {
        current: {
            status: "authenticated" as const,
            bootstrap: { csrf_token: "fixture-csrf-token" },
        },
    },
}))

vi.mock("../api/createAccount", () => ({ createAccount: createAccountMock }))
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

beforeEach(() => {
    createAccountMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useCreateAccount", () => {
    it("creates successfully with the session csrf token", async () => {
        const onSuccess = vi.fn()
        createAccountMock.mockResolvedValue({
            user_id: "user-1",
            login_name: "new.gm",
            raw_activation_token: "raw-token",
            expires_at: "2026-10-01T00:00:00Z",
        })

        const { result } = renderHook(() => useCreateAccount(onSuccess))
        act(() => {
            result.current.submit("new.gm", "New GM", null, ["player"])
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(createAccountMock).toHaveBeenCalledWith(
            "new.gm",
            "New GM",
            null,
            ["player"],
            "fixture-csrf-token",
            expect.anything(),
        )
        expect(onSuccess).toHaveBeenCalled()
    })

    it("maps a 404 to denied", async () => {
        createAccountMock.mockRejectedValue(new PlatformAccountsRequestError(404, "denied"))
        const { result } = renderHook(() => useCreateAccount(vi.fn()))

        act(() => {
            result.current.submit("new.gm", "New GM", null, ["player"])
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })

    it("maps a refusal other than a denial to error", async () => {
        createAccountMock.mockRejectedValue(new PlatformAccountsRequestError(422, "invalid"))
        const { result } = renderHook(() => useCreateAccount(vi.fn()))

        act(() => {
            result.current.submit("new.gm", "New GM", null, ["player"])
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })
    })

    it.each([500, 502, 503, 599])(
        "maps a %i answer to unknown: the portal cannot tell whether the account was created",
        async (status) => {
            createAccountMock.mockRejectedValue(new PlatformAccountsRequestError(status, "boom"))
            const { result } = renderHook(() => useCreateAccount(vi.fn()))

            act(() => {
                result.current.submit("new.gm", "New GM", null, ["player"])
            })

            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "unknown" })
            })
        },
    )

    it("maps a transport failure to unknown", async () => {
        createAccountMock.mockRejectedValue(new TypeError("Failed to fetch"))
        const { result } = renderHook(() => useCreateAccount(vi.fn()))

        act(() => {
            result.current.submit("new.gm", "New GM", null, ["player"])
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "unknown" })
        })
    })

    it("sends one more request per submission after an unknown outcome, never on its own", async () => {
        createAccountMock.mockRejectedValue(new TypeError("Failed to fetch"))
        const { result } = renderHook(() => useCreateAccount(vi.fn()))

        act(() => {
            result.current.submit("new.gm", "New GM", null, ["player"])
        })
        await waitFor(() => expect(result.current.status).toEqual({ kind: "unknown" }))
        await new Promise((resolve) => setTimeout(resolve, 20))
        expect(createAccountMock).toHaveBeenCalledTimes(1)

        act(() => {
            result.current.submit("new.gm", "New GM", null, ["player"])
        })
        await waitFor(() => expect(createAccountMock).toHaveBeenCalledTimes(2))
        await waitFor(() => expect(result.current.status).toEqual({ kind: "unknown" }))
        expect(createAccountMock).toHaveBeenCalledTimes(2)
    })

    it("ignores an answer that arrives after unmount", async () => {
        let resolve: (value: unknown) => void = () => {}
        createAccountMock.mockImplementation(() => new Promise((r) => (resolve = r)))
        const onSuccess = vi.fn()
        const { result, unmount } = renderHook(() => useCreateAccount(onSuccess))

        act(() => {
            result.current.submit("new.gm", "New GM", null, ["player"])
        })
        unmount()
        await act(async () => {
            resolve({ user_id: "u", login_name: "new.gm", raw_activation_token: "t", expires_at: "x" })
        })

        expect(onSuccess).not.toHaveBeenCalled()
    })

    it("does nothing when not authenticated", () => {
        sessionStateRef.current = { status: "unauthenticated" } as never
        const { result } = renderHook(() => useCreateAccount(vi.fn()))

        act(() => {
            result.current.submit("new.gm", "New GM", null, ["player"])
        })

        expect(createAccountMock).not.toHaveBeenCalled()
    })
})
