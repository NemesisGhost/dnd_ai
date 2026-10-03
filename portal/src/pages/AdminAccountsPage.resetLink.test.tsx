import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { AdminAccountsPage } from "./AdminAccountsPage"
import type { PlatformAccount } from "../types/platformAccounts"

// Real AdminAccountsPage + AccountLifecycleActions + usePlatformAccounts +
// useIssuePasswordReset; only the network functions and session are faked.
const { fetchMock, issueMock, reloadMock } = vi.hoisted(() => ({
    fetchMock: vi.fn(),
    issueMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock("../api/issuePasswordReset", () => ({ issuePasswordReset: issueMock }))
vi.mock("../api/platformAccounts", async (importOriginal) => ({
    ...(await importOriginal<typeof import("../api/platformAccounts")>()),
    fetchPlatformAccounts: fetchMock,
}))
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: { status: "authenticated", bootstrap: { csrf_token: "csrf" } },
        reload: reloadMock,
    }),
}))
vi.mock("../components/CreateAccountPanel", () => ({ CreateAccountPanel: () => null }))

function account(id: string, name: string): PlatformAccount {
    return {
        user_id: id,
        display_name: name,
        login_name: id,
        lifecycle_status_code: "active",
        is_platform_administrator: false,
        has_local_credential: true,
        has_outstanding_activation: false,
        last_login_at: null,
        active_session_count: 1,
    }
}

const page = {
    items: [account("user-1", "Alice Example"), account("user-2", "Bob Example")],
    next_cursor: null,
}
const bootstrap = { ...sessionBootstrapFixture, is_platform_administrator: true }

function issued(id: string, token: string) {
    return { user_id: id, raw_reset_token: token, expires_at: "2026-10-01T00:00:00Z" }
}

async function renderPage() {
    const view = render(<AdminAccountsPage bootstrap={bootstrap} />)
    await screen.findByText("Alice Example")
    return view
}

function clickIssue(index: number) {
    fireEvent.click(screen.getAllByRole("button", { name: "Issue password reset" })[index])
}

function linkValue(): string {
    return (screen.getByLabelText("Password-reset link") as HTMLInputElement).value
}

beforeEach(() => {
    fetchMock.mockReset()
    issueMock.mockReset()
    reloadMock.mockReset()
    fetchMock.mockResolvedValue(page)
})

describe("AdminAccountsPage password-reset link", () => {
    it("shows the fragment link for the named account and survives the refetch", async () => {
        issueMock.mockResolvedValue(issued("user-1", "tok 1/+"))
        await renderPage()

        let resolveRefetch: (v: unknown) => void = () => {}
        fetchMock.mockImplementationOnce(() => new Promise((r) => (resolveRefetch = r)))

        clickIssue(0)

        await screen.findByLabelText("Password-reset link")
        expect(issueMock).toHaveBeenCalledWith("user-1", true, "csrf", expect.anything())
        expect(linkValue()).toBe(
            `${window.location.origin}/reset-password#token=${encodeURIComponent("tok 1/+")}`,
        )
        expect(linkValue()).not.toContain("/auth/password-reset")
        expect(linkValue()).not.toContain("?")
        expect(screen.getByRole("heading", { name: /Alice Example/ })).toBeInTheDocument()

        // Refetch in flight: the table is replaced by the loading state.
        await screen.findByText("Loading accounts…")
        expect(screen.getByLabelText("Password-reset link")).toBeInTheDocument()

        await act(async () => resolveRefetch(page))
        await screen.findByText("Alice Example")
        expect(screen.getByLabelText("Password-reset link")).toBeInTheDocument()
    })

    it("survives changing the search query", async () => {
        issueMock.mockResolvedValue(issued("user-1", "tok"))
        await renderPage()
        clickIssue(0)
        await screen.findByLabelText("Password-reset link")

        fireEvent.change(screen.getByLabelText(/Search by display name/), {
            target: { value: "bob" },
        })
        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
        await screen.findByText("Alice Example")
        expect(screen.getByLabelText("Password-reset link")).toBeInTheDocument()
    })

    it("dismiss removes the link; remount does not restore it", async () => {
        issueMock.mockResolvedValue(issued("user-1", "tok"))
        const view = await renderPage()
        clickIssue(0)
        await screen.findByLabelText("Password-reset link")

        fireEvent.click(screen.getByRole("button", { name: "Dismiss" }))
        expect(screen.queryByLabelText("Password-reset link")).not.toBeInTheDocument()

        await screen.findByText("Alice Example")
        clickIssue(0)
        await screen.findByLabelText("Password-reset link")
        view.unmount()

        await renderPage()
        expect(screen.queryByLabelText("Password-reset link")).not.toBeInTheDocument()
    })

    it("clears the old link when a second issuance starts and replaces it on success", async () => {
        issueMock.mockResolvedValueOnce(issued("user-1", "first-token"))
        await renderPage()
        clickIssue(0)
        await screen.findByLabelText("Password-reset link")
        await screen.findByText("Alice Example")

        let resolveSecond: (v: unknown) => void = () => {}
        issueMock.mockImplementationOnce(() => new Promise((r) => (resolveSecond = r)))
        clickIssue(1)
        expect(screen.queryByLabelText("Password-reset link")).not.toBeInTheDocument()
        expect(screen.getByText("Issuing password-reset link…")).toHaveAttribute("role", "status")
        expect(screen.getAllByRole("button", { name: "Issue password reset" })[1]).toBeDisabled()
        expect(issueMock).toHaveBeenCalledTimes(2)

        await act(async () => resolveSecond(issued("user-2", "second-token")))
        await screen.findByLabelText("Password-reset link")
        expect(linkValue()).toContain("second-token")
        expect(linkValue()).not.toContain("first-token")
        expect(screen.getByRole("heading", { name: /Bob Example/ })).toBeInTheDocument()
    })

    it("a failed second issuance does not retain the first token, and can be retried", async () => {
        issueMock.mockResolvedValueOnce(issued("user-1", "first-token"))
        await renderPage()
        clickIssue(0)
        await screen.findByLabelText("Password-reset link")
        await screen.findByText("Alice Example")

        issueMock.mockRejectedValueOnce(new PlatformAccountsRequestError(500, "boom"))
        clickIssue(0)

        const status = await screen.findByText(
            "The password-reset link could not be issued. Try again.",
        )
        expect(status).toHaveAttribute("role", "status")
        expect(screen.queryByLabelText("Password-reset link")).not.toBeInTheDocument()
        expect(document.body.textContent).not.toContain("first-token")
        expect(document.body.textContent).not.toContain("boom")

        issueMock.mockResolvedValueOnce(issued("user-1", "retry-token"))
        clickIssue(0)
        await screen.findByLabelText("Password-reset link")
        expect(linkValue()).toContain("retry-token")
    })

    it.each([403, 404])("keeps a %i response non-disclosing", async (code) => {
        issueMock.mockRejectedValueOnce(new PlatformAccountsRequestError(code, "detail"))
        await renderPage()
        clickIssue(0)

        await screen.findByText("You do not have permission to make this change.")
        expect(screen.queryByLabelText("Password-reset link")).not.toBeInTheDocument()
        expect(document.body.textContent).not.toContain("detail")
    })

    it("401 requests an authoritative session reload", async () => {
        issueMock.mockRejectedValueOnce(new PlatformAccountsRequestError(401, "expired"))
        await renderPage()
        clickIssue(0)
        await waitFor(() => expect(reloadMock).toHaveBeenCalledTimes(1))
        expect(screen.queryByLabelText("Password-reset link")).not.toBeInTheDocument()
    })
})
