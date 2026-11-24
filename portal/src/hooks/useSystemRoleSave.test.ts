import { act, renderHook, waitFor } from "@testing-library/react"
import { createElement } from "react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { PlatformAccount } from "../types/platformAccounts"
import { useSystemRoleSave } from "./useSystemRoleSave"
import type { StagedChange } from "../utils/systemRoleStaging"

const { assignMock, revokeMock, fetchMock } = vi.hoisted(() => ({
    assignMock: vi.fn(),
    revokeMock: vi.fn(),
    fetchMock: vi.fn(),
}))

vi.mock("../api/systemRoles", () => ({ assignSystemRole: assignMock, revokeSystemRole: revokeMock }))
vi.mock("../api/platformAccounts", async (importOriginal) => ({
    ...(await importOriginal<typeof import("../api/platformAccounts")>()),
    fetchPlatformAccounts: fetchMock,
}))

const reload = vi.fn()
const refresh = vi.fn()
const onReconciled = vi.fn()

function account(roles: string[]): PlatformAccount {
    return {
        user_id: "user-1",
        display_name: "Alice",
        login_name: "alice",
        lifecycle_status_code: "active",
        is_platform_administrator: false,
        system_roles: roles,
        has_local_credential: true,
        has_outstanding_activation: false,
        last_login_at: null,
        active_session_count: 0,
    }
}

const CHANGES: StagedChange[] = [
    { code: "gm", action: "add" },
    { code: "player", action: "remove" },
]
const ok = (code: string, changed = true) => ({ user_id: "user-1", system_role_code: code, changed })

function setup(selfUserId = "someone-else") {
    const wrapper = ({ children }: { children: ReactNode }) =>
        createElement(
            SessionContext.Provider,
            { value: { state: { status: "authenticated", bootstrap: sessionBootstrapFixture }, reload, refresh } },
            children,
        )
    return renderHook(() => useSystemRoleSave({ csrfToken: "csrf", selfUserId, onReconciled }), { wrapper })
}

beforeEach(() => {
    for (const mock of [assignMock, revokeMock, fetchMock, reload, refresh, onReconciled]) mock.mockReset()
    refresh.mockResolvedValue(true)
})

describe("useSystemRoleSave", () => {
    it("sends the changes in order, reads the account once and reports what is still outstanding", async () => {
        assignMock.mockResolvedValue(ok("gm"))
        revokeMock.mockResolvedValue(ok("player"))
        fetchMock.mockResolvedValue({ items: [account(["gm"])], next_cursor: null })
        const { result } = setup()

        act(() => result.current.save(account(["player"]), CHANGES))
        await waitFor(() => expect(result.current.state.phase).toBe("done"))

        expect(assignMock).toHaveBeenCalledWith("user-1", "gm", "csrf", expect.anything())
        expect(revokeMock).toHaveBeenCalledWith("user-1", "player", "csrf", expect.anything())
        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(fetchMock.mock.calls[0]![0]).toEqual({ q: "alice", limit: 100 })
        expect(result.current.state.ledger.map((step) => step.result)).toEqual(["saved", "saved"])
        expect(onReconciled).toHaveBeenCalledWith(account(["gm"]), ["gm"])
    })

    it("stops at an unknown outcome, never sends the next step, and leaves the unconfirmed change staged", async () => {
        assignMock.mockRejectedValue(new TypeError("Failed to fetch"))
        fetchMock.mockResolvedValue({ items: [account(["player"])], next_cursor: null })
        const { result } = setup()

        act(() => result.current.save(account(["player"]), CHANGES))
        await waitFor(() => expect(result.current.state.phase).toBe("done"))

        expect(revokeMock).not.toHaveBeenCalled()
        expect(result.current.state.ledger.map((step) => step.result)).toEqual(["not_confirmed", "not_sent"])
        expect(onReconciled).toHaveBeenCalledWith(account(["player"]), ["gm"])
    })

    it("treats a 5xx as unknown, not as a refusal", async () => {
        assignMock.mockRejectedValue(new PlatformAccountsRequestError(503, "down"))
        fetchMock.mockResolvedValue({ items: [account(["player"])], next_cursor: null })
        const { result } = setup()
        act(() => result.current.save(account(["player"]), CHANGES))
        await waitFor(() => expect(result.current.state.phase).toBe("done"))
        expect(result.current.state.ledger[0]!.result).toBe("not_confirmed")
    })

    it("sends one batch for two quick presses and a second batch only on a later press", async () => {
        let release: (value: unknown) => void = () => {}
        assignMock.mockReturnValueOnce(new Promise((resolve) => (release = resolve)))
        revokeMock.mockResolvedValue(ok("player"))
        fetchMock.mockResolvedValue({ items: [account(["gm"])], next_cursor: null })
        const { result } = setup()

        act(() => {
            result.current.save(account(["player"]), CHANGES)
            result.current.save(account(["player"]), CHANGES)
        })
        expect(assignMock).toHaveBeenCalledTimes(1)
        await act(async () => release(ok("gm")))
        await waitFor(() => expect(result.current.state.phase).toBe("done"))
        expect(assignMock).toHaveBeenCalledTimes(1)
        expect(revokeMock).toHaveBeenCalledTimes(1)
    })

    it("keeps Save off after a failed read and repeats only the read", async () => {
        assignMock.mockRejectedValue(new TypeError("Failed to fetch"))
        fetchMock.mockRejectedValue(new TypeError("Failed to fetch"))
        const { result } = setup()
        act(() => result.current.save(account(["player"]), CHANGES))
        await waitFor(() => expect(result.current.state.phase).toBe("check_failed"))

        fetchMock.mockResolvedValue({ items: [account(["player", "gm"])], next_cursor: null })
        act(() => result.current.checkAgain())
        await waitFor(() => expect(result.current.state.phase).toBe("done"))
        expect(assignMock).toHaveBeenCalledTimes(1)
        expect(revokeMock).not.toHaveBeenCalled()
        expect(fetchMock).toHaveBeenCalledTimes(2)
        expect(result.current.state.ledger[0]!.result).toBe("confirmed")
    })

    it("ignores a late answer after clear and sends no later step", async () => {
        let release: (value: unknown) => void = () => {}
        assignMock.mockReturnValueOnce(new Promise((resolve) => (release = resolve)))
        const { result } = setup()
        act(() => result.current.save(account(["player"]), CHANGES))
        act(() => result.current.clear())
        await act(async () => release(ok("gm")))
        expect(revokeMock).not.toHaveBeenCalled()
        expect(fetchMock).not.toHaveBeenCalled()
        expect(result.current.state.phase).toBe("idle")
    })

    it("a 401 stops the batch, marks the rest not sent and reloads the session once", async () => {
        assignMock.mockRejectedValue(new PlatformAccountsRequestError(401, "expired"))
        const { result } = setup()
        act(() => result.current.save(account(["player"]), CHANGES))
        await waitFor(() => expect(result.current.state.phase).toBe("done"))
        expect(reload).toHaveBeenCalledTimes(1)
        expect(result.current.state.ledger.map((step) => step.result)).toEqual(["not_sent", "not_sent"])
        expect(fetchMock).not.toHaveBeenCalled()
    })

    it("skips the read and reports the removal when the signed-in account's own Administrator removal is saved", async () => {
        revokeMock.mockResolvedValue(ok("admin"))
        const { result } = setup("user-1")
        act(() => result.current.save(account(["admin"]), [{ code: "admin", action: "remove" }]))
        await waitFor(() => expect(result.current.state.phase).toBe("done"))
        expect(result.current.ownAdminRemoved).toBe(true)
        expect(fetchMock).not.toHaveBeenCalled()
        expect(refresh).not.toHaveBeenCalled()
    })
})
