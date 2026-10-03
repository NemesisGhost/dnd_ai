import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { UserPreferenceRequestError } from "../api/userPreferences"
import { useSaveCampaignStartupPreference } from "./useSaveCampaignStartupPreference"

const { setPreferenceMock, sessionStateRef } = vi.hoisted(() => ({
    setPreferenceMock: vi.fn(),
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
    useSession: () => ({ state: sessionStateRef.current, reload: vi.fn() }),
}))

beforeEach(() => {
    setPreferenceMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useSaveCampaignStartupPreference", () => {
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
