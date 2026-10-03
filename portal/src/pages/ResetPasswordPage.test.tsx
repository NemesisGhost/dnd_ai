import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { StrictMode } from "react"
import { MemoryRouter, Route, Routes } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ResetPasswordPage } from "./ResetPasswordPage"

const PASSWORD = "correct-password-15-chars"
const ROUTE = "/reset-password"
const ENDPOINT = "/api/auth/password-reset"
const LABEL = "New passphrase"
const BUTTON = "Reset password"
const INVALID_HEADING = "This password-reset link is not valid"

let fetchMock: ReturnType<typeof vi.fn>

function renderPage(strict = false) {
    const tree = (
        <MemoryRouter initialEntries={[ROUTE]}>
            <Routes>
                <Route path={ROUTE} element={<ResetPasswordPage />} />
                <Route path="/login" element={<p>Login page</p>} />
            </Routes>
        </MemoryRouter>
    )
    return render(strict ? <StrictMode>{tree}</StrictMode> : tree)
}

function open(hash: string) {
    window.history.replaceState(null, "", ROUTE + hash)
}

function fill(password: string, confirmation: string) {
    fireEvent.change(screen.getByLabelText(LABEL), { target: { value: password } })
    fireEvent.change(screen.getByLabelText("Confirm passphrase"), { target: { value: confirmation } })
}

function ok() {
    return Promise.resolve(new Response(JSON.stringify({ user_id: "u1", login_name: "new.gm", sessions_revoked: false }), { status: 200 }))
}

beforeEach(() => {
    fetchMock = vi.fn(ok)
    vi.stubGlobal("fetch", fetchMock)
    window.localStorage.clear()
    window.sessionStorage.clear()
    open("")
})

afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
})

describe("ResetPasswordPage", () => {
    it("shows the generic invalid-link state with no fragment", () => {
        renderPage()
        expect(screen.getByRole("heading", { name: INVALID_HEADING })).toBeInTheDocument()
        expect(fetchMock).not.toHaveBeenCalled()
    })

    it.each(["#token=%", "#token=%E0%A4%A", "#token=", "#other=abc", "#token"])(
        "treats %s as the same generic state, removes it, and sends nothing",
        (hash) => {
            open(hash)
            renderPage()
            expect(window.location.hash).toBe("")
            expect(screen.getByRole("heading", { name: INVALID_HEADING })).toBeInTheDocument()
            expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
            expect(fetchMock).not.toHaveBeenCalled()
        },
    )

    it("removes a valid fragment immediately and labels both password fields", () => {
        open("#token=raw-token")
        renderPage()
        expect(window.location.hash).toBe("")
        expect(window.location.href).not.toContain("raw-token")
        expect(screen.getByLabelText(LABEL)).toHaveAttribute("autocomplete", "new-password")
        expect(screen.getByLabelText("Confirm passphrase")).toHaveAttribute("autocomplete", "new-password")
    })

    it("blocks submission and announces a mismatch", () => {
        open("#token=raw-token")
        renderPage()
        fill(PASSWORD, PASSWORD + "x")
        const alert = screen.getByRole("alert")
        expect(alert).toHaveTextContent("The passphrases do not match.")
        expect(screen.getByLabelText("Confirm passphrase")).toHaveAttribute("aria-describedby", alert.id)
        expect(screen.getByLabelText("Confirm passphrase")).toHaveAttribute("aria-invalid", "true")
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        expect(fetchMock).not.toHaveBeenCalled()
    })

    it("sends exactly one POST with secrets only in the JSON body, even on double submit", async () => {
        open("#token=raw%20token%2F1")
        renderPage(true)
        fill(PASSWORD, PASSWORD)
        const button = screen.getByRole("button", { name: BUTTON })
        fireEvent.click(button)
        fireEvent.click(button)

        await screen.findByRole("link", { name: "Go to sign in" })
        expect(fetchMock).toHaveBeenCalledTimes(1)
        const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
        expect(url).toBe(ENDPOINT)
        expect(init.method).toBe("POST")
        const body = JSON.parse(init.body as string) as { token: string; password?: string; new_password?: string }
        expect(body.token).toBe("raw token/1")
        expect(body.password ?? body.new_password).toBe(PASSWORD)
        expect(url).not.toContain("raw")
        expect(JSON.stringify({ ...window.localStorage, ...window.sessionStorage })).not.toContain(PASSWORD)
    })

    it("disables fields and submit while pending", async () => {
        let release: (r: Response) => void = () => {}
        fetchMock.mockImplementation(() => new Promise<Response>((resolve) => { release = resolve }))
        open("#token=raw-token")
        renderPage()
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await waitFor(() => expect(screen.getByLabelText(LABEL)).toBeDisabled())
        expect(screen.getByLabelText("Confirm passphrase")).toBeDisabled()
        expect(screen.getByRole("button")).toBeDisabled()
        await act(async () => {
            release(new Response("{}", { status: 404 }))
        })
    })

    it("clears secrets after success so nothing remains rendered", async () => {
        open("#token=raw-token")
        const { container } = renderPage()
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await screen.findByRole("link", { name: "Go to sign in" })
        expect(container.innerHTML).not.toContain("raw-token")
        expect(container.querySelector("input")).toBeNull()
        expect(screen.queryByText("Login page")).not.toBeInTheDocument()
    })

    it("keeps the token in memory so a recoverable error can be retried", async () => {
        fetchMock.mockImplementationOnce(() => Promise.resolve(new Response("{}", { status: 500 })))
        open("#token=raw-token")
        renderPage()
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await screen.findByText(/Try again/)
        expect(screen.getByLabelText(LABEL)).toHaveValue(PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await screen.findByRole("link", { name: "Go to sign in" })
        expect(fetchMock).toHaveBeenCalledTimes(2)
        const second = JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string) as { token: string }
        expect(second.token).toBe("raw-token")
    })

    it("aborts the in-flight request on unmount", async () => {
        let signal: AbortSignal | undefined
        fetchMock.mockImplementation((_url: string, init: RequestInit) => {
            signal = init.signal as AbortSignal
            return new Promise<Response>(() => {})
        })
        open("#token=raw-token")
        const view = renderPage()
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await waitFor(() => expect(signal).toBeDefined())
        view.unmount()
        expect(signal?.aborted).toBe(true)
    })
})
