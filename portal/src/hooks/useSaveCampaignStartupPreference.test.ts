import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { UserPreferenceRequestError } from "../api/userPreferences"
import { useSaveCampaignStartupPreference } from "./useSaveCampaignStartupPreference"

const { setPreferenceMock, refreshMock, sessionStateRef } = vi.hoisted(() => ({
    setPreferenceMock: vi.fn(),
    refreshMock: vi.fn(),
    sessionStateRef: {
        current: {
            status: "authenticated" as "authenticated" | "unauthenticated",
            bootstrap: { csrf_token: "fixture-csrf-token" },
        },
    },
}))

vi.mock("../api/userPreferences", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/userPreferences")>()
    return { ...actual, setCampaignStartupPreference: setPreferenceMock }
})
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: vi.fn(),
        refresh: refreshMock,
    }),
}))

beforeEach(() => {
    setPreferenceMock.mockReset()
    refreshMock.mockReset()
    refreshMock.mockResolvedValue(true)
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useSaveCampaignStartupPreference", () => {
    it("stays pending until the authoritative bootstrap is refreshed, then succeeds", async () => {
        setPreferenceMock.mockResolvedValue(undefined)
        let finishRefresh: (applied: boolean) => void = () => {}
        refreshMock.mockReturnValue(
            new Promise<boolean>((r) => {
                finishRefresh = r
            }),
        )
        const { result } = renderHook(() => useSaveCampaignStartupPreference())

        act(() => {
            result.current.save("campaign-a")
        })
        await waitFor(() => {
            expect(refreshMock).toHaveBeenCalledTimes(1)
        })
        expect(result.current.status).toEqual({ kind: "pending" })

        await act(async () => {
            finishRefresh(true)
        })
        expect(result.current.status).toEqual({ kind: "success" })
    })

    it("reports an unconfirmed save, never success, when the refresh fails", async () => {
        setPreferenceMock.mockResolvedValue(undefined)
        refreshMock.mockRejectedValue(new Error("offline"))
        const { result } = renderHook(() => useSaveCampaignStartupPreference())

        act(() => {
            result.current.save("campaign-a")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "unconfirmed" })
        })
    })

    it("reports denied when the refresh finds the session unauthenticated", async () => {
        setPreferenceMock.mockResolvedValue(undefined)
        refreshMock.mockResolvedValue(false)
        const { result } = renderHook(() => useSaveCampaignStartupPreference())

        act(() => {
            result.current.save(null)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })

    it("does not refresh after a rejected save", async () => {
        setPreferenceMock.mockRejectedValue(new UserPreferenceRequestError(404, "gone"))
        const { result } = renderHook(() => useSaveCampaignStartupPreference())

        act(() => {
            result.current.save("campaign-a")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "unavailable" })
        })
        expect(refreshMock).not.toHaveBeenCalled()
    })

    it("aborts an in-flight save and ignores its refresh on unmount", async () => {
        let finishRefresh: (applied: boolean) => void = () => {}
        setPreferenceMock.mockResolvedValue(undefined)
        refreshMock.mockReturnValue(
            new Promise<boolean>((r) => {
                finishRefresh = r
            }),
        )
        const { result, unmount } = renderHook(() => useSaveCampaignStartupPreference())
        act(() => {
            result.current.save("campaign-a")
        })
        await waitFor(() => {
            expect(refreshMock).toHaveBeenCalledTimes(1)
        })
        const signal = refreshMock.mock.calls[0]![0] as AbortSignal

        unmount()
        finishRefresh(true)

        expect(signal.aborted).toBe(true)
    })

    it("saves with the session csrf token and reports success", async () => {
        setPreferenceMock.mockResolvedValue(undefined)
        const { result } = renderHook(() => useSaveCampaignStartupPreference())

        act(() => {
            result.current.save("campaign-a")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(setPreferenceMock).toHaveBeenCalledWith(
            "campaign-a",
            "fixture-csrf-token",
            expect.anything(),
        )
    })

    it("reports pending while the request is in flight and ignores a second save", async () => {
        let resolve: () => void = () => {}
        setPreferenceMock.mockReturnValue(
            new Promise<void>((r) => {
                resolve = r
            }),
        )
        const { result } = renderHook(() => useSaveCampaignStartupPreference())

        act(() => {
            result.current.save(null)
        })
        expect(result.current.status).toEqual({ kind: "pending" })

        act(() => {
            result.current.save("campaign-b")
        })
        expect(setPreferenceMock).toHaveBeenCalledTimes(1)

        await act(async () => {
            resolve()
        })
        expect(result.current.status).toEqual({ kind: "success" })
    })

    it.each([
        [404, "unavailable"],
        [401, "denied"],
        [403, "denied"],
        [500, "error"],
    ])("maps a %i response to %s", async (status, kind) => {
        setPreferenceMock.mockRejectedValue(new UserPreferenceRequestError(status, "x"))
        const { result } = renderHook(() => useSaveCampaignStartupPreference())

        act(() => {
            result.current.save("campaign-a")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind })
        })
    })

    it("maps a network failure to a recoverable error", async () => {
        setPreferenceMock.mockRejectedValue(new TypeError("offline"))
        const { result } = renderHook(() => useSaveCampaignStartupPreference())

        act(() => {
            result.current.save("campaign-a")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })
    })

    it("does nothing without an authenticated session", () => {
        sessionStateRef.current = {
            status: "unauthenticated",
            bootstrap: { csrf_token: "" },
        }
        const { result } = renderHook(() => useSaveCampaignStartupPreference())

        act(() => {
            result.current.save("campaign-a")
        })

        expect(setPreferenceMock).not.toHaveBeenCalled()
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("resets to idle", async () => {
        setPreferenceMock.mockResolvedValue(undefined)
        const { result } = renderHook(() => useSaveCampaignStartupPreference())
        act(() => {
            result.current.save("campaign-a")
        })
        await waitFor(() => {
            expect(result.current.status.kind).toBe("success")
        })

        act(() => {
            result.current.reset()
        })

        expect(result.current.status).toEqual({ kind: "idle" })
    })
})
