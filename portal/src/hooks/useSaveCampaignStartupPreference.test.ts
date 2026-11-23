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
            bootstrap: {
                csrf_token: "fixture-csrf-token",
                user: { user_id: "user-1" },
                campaign_preferences: { preferred_campaign_id: null as string | null },
            },
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
    sessionStateRef.current = sessionWith("user-1", null)
})

// The shared session as the hook reads it: who is signed in and what the server says is preferred.
function sessionWith(
    userId: string,
    preferred: string | null,
    status: "authenticated" | "unauthenticated" = "authenticated",
) {
    return {
        status,
        bootstrap: {
            csrf_token: "fixture-csrf-token",
            user: { user_id: userId },
            campaign_preferences: { preferred_campaign_id: preferred },
        },
    }
}

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

    it("keeps a confirmed save as unconfirmed, never denied, when the refresh was not applied (superseded or the session ended)", async () => {
        setPreferenceMock.mockResolvedValue(undefined)
        refreshMock.mockResolvedValue(false)
        const { result } = renderHook(() => useSaveCampaignStartupPreference())

        act(() => {
            result.current.save(null)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "unconfirmed" })
        })
        expect(setPreferenceMock).toHaveBeenCalledTimes(1)
        expect(refreshMock).toHaveBeenCalledTimes(1)
    })

    it("sends the PUT once when the refresh after it fails or is not applied", async () => {
        for (const outcome of [() => Promise.reject(new Error("offline")), () => Promise.resolve(false)]) {
            setPreferenceMock.mockReset()
            refreshMock.mockReset()
            setPreferenceMock.mockResolvedValue(undefined)
            refreshMock.mockImplementation(outcome)
            const { result, unmount } = renderHook(() => useSaveCampaignStartupPreference())
            act(() => {
                result.current.save("campaign-a")
            })
            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "unconfirmed" })
            })
            expect(setPreferenceMock).toHaveBeenCalledTimes(1)
            unmount()
        }
    })

    it("a deferred refresh that resolves not applied after a confirmed PUT leaves the save unconfirmed", async () => {
        setPreferenceMock.mockResolvedValue(undefined)
        let finish!: (applied: boolean) => void
        refreshMock.mockReturnValue(
            new Promise<boolean>((resolve) => {
                finish = resolve
            }),
        )
        const { result } = renderHook(() => useSaveCampaignStartupPreference())
        act(() => {
            result.current.save("campaign-a")
        })
        await waitFor(() => expect(refreshMock).toHaveBeenCalledTimes(1))
        expect(result.current.status).toEqual({ kind: "pending" })
        await act(async () => {
            finish(false)
        })
        expect(result.current.status).toEqual({ kind: "unconfirmed" })
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
        sessionStateRef.current = sessionWith("user-1", null, "unauthenticated")
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


describe("an outstanding episode: a confirmed PUT whose read-back was not applied", () => {
    async function unconfirmedSave(
        submitted: string | null,
        readBack: () => Promise<boolean> = () => Promise.reject(new Error("offline")),
    ) {
        setPreferenceMock.mockResolvedValue(undefined)
        refreshMock.mockImplementation(readBack)
        const rendered = renderHook(() => useSaveCampaignStartupPreference())
        act(() => {
            rendered.result.current.save(submitted)
        })
        await waitFor(() => expect(rendered.result.current.status).toEqual({ kind: "unconfirmed" }))
        return rendered
    }

    it("A1: a later bootstrap of the same user with the submitted value confirms it, with one PUT", async () => {
        const { result, rerender } = await unconfirmedSave("campaign-a")
        expect(result.current.outstanding).toBe(true)
        sessionStateRef.current = sessionWith("user-1", "campaign-a")
        rerender()
        expect(result.current.status).toEqual({ kind: "success" })
        expect(result.current.outstanding).toBe(false)
        expect(setPreferenceMock).toHaveBeenCalledTimes(1)
    })

    it("A2: the same for null (resume my last visited campaign)", async () => {
        sessionStateRef.current = sessionWith("user-1", "campaign-a")
        const { result, rerender } = await unconfirmedSave(null)
        expect(result.current.outstanding).toBe(true)
        sessionStateRef.current = sessionWith("user-1", null)
        rerender()
        expect(result.current.status).toEqual({ kind: "success" })
        expect(setPreferenceMock).toHaveBeenCalledTimes(1)
    })

    it("A3: evidence that is not for this save and user never confirms it", async () => {
        const { result, rerender } = await unconfirmedSave("campaign-a")
        for (const other of [
            sessionWith("user-1", "campaign-b"),
            sessionWith("user-1", null),
            sessionWith("user-1", "campaign-a", "unauthenticated"),
        ]) {
            sessionStateRef.current = other
            rerender()
            expect(result.current.status).toEqual({ kind: "unconfirmed" })
            expect(result.current.outstanding).toBe(true)
        }
        // Another account that happens to show the value does not confirm it; the episode ends with the account.
        sessionStateRef.current = sessionWith("user-2", "campaign-a")
        rerender()
        expect(result.current.status).not.toEqual({ kind: "success" })
        expect(result.current.outstanding).toBe(false)
        expect(setPreferenceMock).toHaveBeenCalledTimes(1)
    })

    it("A3: a read-back that resolves false with no published change leaves it outstanding", async () => {
        const { result } = await unconfirmedSave("campaign-a", () => Promise.resolve(false))
        expect(result.current.outstanding).toBe(true)
        expect(result.current.status).toEqual({ kind: "unconfirmed" })
    })

    it("A4: a late check for an ended episode changes nothing, and its value cannot confirm a newer save", async () => {
        let lateCheck!: { reject: (cause: Error) => void }
        const { result, rerender } = await unconfirmedSave("campaign-a")
        refreshMock.mockImplementation(
            () =>
                new Promise<boolean>((_resolve, reject) => {
                    lateCheck = { reject }
                }),
        )
        act(() => result.current.check())
        await waitFor(() => expect(result.current.checking).toBe(true))
        // A newer save Y is confirmed; its read-back fails, so Y is the episode now.
        refreshMock.mockRejectedValue(new Error("offline"))
        act(() => {
            result.current.save("campaign-b")
        })
        await waitFor(() => expect(result.current.status).toEqual({ kind: "unconfirmed" }))
        await act(async () => {
            lateCheck.reject(new Error("late"))
        })
        expect(result.current.status).toEqual({ kind: "unconfirmed" })
        expect(result.current.checkFailed).toBe(false)
        // The old value, published after Y was confirmed, does not report success for Y.
        sessionStateRef.current = sessionWith("user-1", "campaign-a")
        rerender()
        expect(result.current.status).toEqual({ kind: "unconfirmed" })
        sessionStateRef.current = sessionWith("user-1", "campaign-b")
        rerender()
        expect(result.current.status).toEqual({ kind: "success" })
        expect(setPreferenceMock).toHaveBeenCalledTimes(2)
    })

    it.each([
        ["a 404", () => new UserPreferenceRequestError(404, "gone")],
        ["a 403", () => new UserPreferenceRequestError(403, "no")],
        ["a network failure", () => new TypeError("offline")],
    ])("A5: %s on a newer save keeps the episode outstanding, and a matching bootstrap still confirms it", async (_name, failure) => {
        const { result, rerender } = await unconfirmedSave("campaign-a")
        setPreferenceMock.mockRejectedValue(failure())
        act(() => {
            result.current.save("campaign-b")
        })
        await waitFor(() => expect(result.current.status.kind).not.toBe("pending"))
        expect(result.current.status.kind).not.toBe("unconfirmed")
        expect(result.current.outstanding).toBe(true)
        sessionStateRef.current = sessionWith("user-1", "campaign-a")
        rerender()
        expect(result.current.outstanding).toBe(false)
        // The refusal of the newer save stays visible; the confirmation of the earlier one is reported alongside it.
        expect(result.current.status.kind).not.toBe("success")
        expect(result.current.confirmed).toBe(true)
    })

    it("A6: check() reads in place once with a signal, never reloads, and keeps the episode on a failure", async () => {
        const { result } = await unconfirmedSave("campaign-a")
        let rejectCheck!: (cause: Error) => void
        refreshMock.mockReset()
        refreshMock.mockImplementation(
            () =>
                new Promise<boolean>((_resolve, reject) => {
                    rejectCheck = reject
                }),
        )
        act(() => result.current.check())
        act(() => result.current.check())
        expect(refreshMock).toHaveBeenCalledTimes(1)
        expect(refreshMock.mock.calls[0]![0]).toBeInstanceOf(AbortSignal)
        expect(result.current.checking).toBe(true)
        await act(async () => {
            rejectCheck(new Error("offline"))
        })
        expect(result.current.checking).toBe(false)
        expect(result.current.checkFailed).toBe(true)
        expect(result.current.outstanding).toBe(true)
        expect(result.current.status).toEqual({ kind: "unconfirmed" })
        expect(setPreferenceMock).toHaveBeenCalledTimes(1)
    })

    it("A6: a check that is not applied waits silently, and unmount aborts a check", async () => {
        const { result, unmount } = await unconfirmedSave("campaign-a")
        refreshMock.mockReset()
        refreshMock.mockResolvedValue(false)
        act(() => result.current.check())
        await waitFor(() => expect(result.current.checking).toBe(false))
        expect(result.current.checkFailed).toBe(false)
        expect(result.current.outstanding).toBe(true)
        refreshMock.mockReset()
        refreshMock.mockReturnValue(new Promise<boolean>(() => {}))
        act(() => result.current.check())
        const signal = refreshMock.mock.calls[0]![0] as AbortSignal
        unmount()
        expect(signal.aborted).toBe(true)
    })

    it("reset() clears the last request's status but does not end the episode", async () => {
        const { result } = await unconfirmedSave("campaign-a")
        act(() => result.current.reset())
        expect(result.current.status).toEqual({ kind: "idle" })
        expect(result.current.outstanding).toBe(true)
    })
})


describe("S02-R1: A is confirmed while a newer save B is pending", () => {
    async function aOutstandingBPending() {
        setPreferenceMock.mockResolvedValueOnce(undefined)
        refreshMock.mockRejectedValue(new Error("offline"))
        const rendered = renderHook(() => useSaveCampaignStartupPreference())
        act(() => {
            rendered.result.current.save("campaign-a")
        })
        await waitFor(() => expect(rendered.result.current.status).toEqual({ kind: "unconfirmed" }))
        let settle!: { ok: () => void; fail: (cause: unknown) => void }
        setPreferenceMock.mockImplementationOnce(
            () =>
                new Promise<void>((resolve, reject) => {
                    settle = { ok: resolve, fail: reject }
                }),
        )
        act(() => {
            rendered.result.current.save("campaign-b")
        })
        expect(rendered.result.current.status).toEqual({ kind: "pending" })
        sessionStateRef.current = sessionWith("user-1", "campaign-a")
        rendered.rerender()
        return { ...rendered, settle }
    }

    it("keeps A's confirmation while B is pending, and the episode is over", async () => {
        const { result } = await aOutstandingBPending()
        expect(result.current.outstanding).toBe(false)
        expect(result.current.confirmed).toBe(true)
        expect(result.current.status).toEqual({ kind: "pending" })
    })

    it.each([
        ["a 404", () => new UserPreferenceRequestError(404, "gone"), "unavailable"],
        ["a 403", () => new UserPreferenceRequestError(403, "no"), "denied"],
        ["a 500", () => new UserPreferenceRequestError(500, "boom"), "error"],
        ["a network failure", () => new TypeError("offline"), "error"],
    ])("B rejected (%s): B's status stays, A's confirmation stays", async (_name, failure, kind) => {
        const { result, settle } = await aOutstandingBPending()
        await act(async () => settle.fail(failure()))
        expect(result.current.status).toEqual({ kind })
        expect(result.current.confirmed).toBe(true)
        expect(result.current.outstanding).toBe(false)
    })

    it("B succeeds and is read back: B is success and A's confirmation is not reported beside it", async () => {
        refreshMock.mockReset()
        const { result, settle } = await aOutstandingBPending()
        refreshMock.mockResolvedValue(true)
        await act(async () => settle.ok())
        expect(result.current.status).toEqual({ kind: "success" })
        expect(result.current.confirmed).toBe(false)
    })

    it("B succeeds with its read-back outstanding: B is unconfirmed, A is confirmed, and A's value does not confirm B", async () => {
        const { result, settle, rerender } = await aOutstandingBPending()
        await act(async () => settle.ok())
        expect(result.current.status).toEqual({ kind: "unconfirmed" })
        expect(result.current.outstanding).toBe(true)
        expect(result.current.confirmed).toBe(true)
        sessionStateRef.current = sessionWith("user-1", "campaign-a")
        rerender()
        expect(result.current.status).toEqual({ kind: "unconfirmed" })
        sessionStateRef.current = sessionWith("user-1", "campaign-b")
        rerender()
        expect(result.current.status).toEqual({ kind: "success" })
        expect(result.current.confirmed).toBe(false)
    })
})
