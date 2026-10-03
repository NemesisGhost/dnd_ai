import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { StrictMode } from "react"
import { MemoryRouter, Route, Routes } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ResetPasswordPage } from "./ResetPasswordPage"

const PASSWORD = "correct-password-15-chars"
const ROUTE = "/reset-password"
const ENDPOINT = "/api/auth/password-reset"
const STATUS_ENDPOINT = "/api/auth/password-reset-status"
const CHECKING = "Checking the password-reset link…"
const CHECK_FAILED = "The password-reset link could not be checked."
const LABEL = "New passphrase"
const BUTTON = "Reset password"
const INVALID_HEADING = "This password-reset link is not valid"

let fetchMock: ReturnType<typeof vi.fn>
let statusHandler: (init: RequestInit) => Promise<Response>

function statusResponse(valid: boolean) {
    return Promise.resolve(new Response(JSON.stringify({ valid }), { status: 200 }))
}

function statusCalls() {
    return fetchMock.mock.calls.filter(([url]) => url === STATUS_ENDPOINT)
}

function resetCalls() {
    return fetchMock.mock.calls.filter(([url]) => url === ENDPOINT)
}

// Opens a valid link and waits for the form to replace the checking state.
async function renderReady(strict = false) {
    open("#token=raw-token")
    const view = renderPage(strict)
    await screen.findByLabelText(LABEL)
    return view
}

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
    statusHandler = () => statusResponse(true)
    fetchMock = vi.fn((url: string, init: RequestInit) => (url === STATUS_ENDPOINT ? statusHandler(init) : ok()))
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
        expect(statusCalls()).toHaveLength(0)
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

    it("removes a valid fragment immediately and labels both password fields", async () => {
        open("#token=raw-token")
        renderPage()
        expect(window.location.hash).toBe("")
        expect(window.location.href).not.toContain("raw-token")
        await screen.findByLabelText(LABEL)
        expect(screen.getByLabelText(LABEL)).toHaveAttribute("autocomplete", "new-password")
        expect(screen.getByLabelText("Confirm passphrase")).toHaveAttribute("autocomplete", "new-password")
    })

    it("blocks submission and announces a mismatch", async () => {
        await renderReady()
        fill(PASSWORD, PASSWORD + "x")
        const alert = screen.getByRole("alert")
        expect(alert).toHaveTextContent("The passphrases do not match.")
        expect(screen.getByLabelText("Confirm passphrase")).toHaveAttribute("aria-describedby", alert.id)
        expect(screen.getByLabelText("Confirm passphrase")).toHaveAttribute("aria-invalid", "true")
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        expect(resetCalls()).toHaveLength(0)
    })

    it("sends exactly one POST with secrets only in the JSON body, even on double submit", async () => {
        open("#token=raw%20token%2F1")
        renderPage(true)
        await screen.findByLabelText(LABEL)
        fill(PASSWORD, PASSWORD)
        const button = screen.getByRole("button", { name: BUTTON })
        fireEvent.click(button)
        fireEvent.click(button)

        await screen.findByRole("link", { name: "Go to sign in" })
        expect(resetCalls()).toHaveLength(1)
        const [url, init] = resetCalls()[0] as [string, RequestInit]
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
        await renderReady()
        fetchMock.mockImplementation(() => new Promise<Response>((resolve) => { release = resolve }))
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
        const { container } = await renderReady()
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await screen.findByRole("link", { name: "Go to sign in" })
        expect(container.innerHTML).not.toContain("raw-token")
        expect(container.querySelector("input")).toBeNull()
        expect(screen.queryByText("Login page")).not.toBeInTheDocument()
    })

    it("keeps the token in memory so a recoverable error can be retried", async () => {
        await renderReady()
        fetchMock.mockImplementationOnce(() => Promise.resolve(new Response("{}", { status: 500 })))
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await screen.findByText(/Try again/)
        expect(screen.getByLabelText(LABEL)).toHaveValue(PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await screen.findByRole("link", { name: "Go to sign in" })
        expect(resetCalls()).toHaveLength(2)
        const second = JSON.parse((resetCalls()[1][1] as RequestInit).body as string) as { token: string }
        expect(second.token).toBe("raw-token")
    })

    it("aborts the in-flight request on unmount", async () => {
        let signal: AbortSignal | undefined
        const view = await renderReady()
        fetchMock.mockImplementation((_url: string, init: RequestInit) => {
            signal = init.signal as AbortSignal
            return new Promise<Response>(() => {})
        })
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await waitFor(() => expect(signal).toBeDefined())
        view.unmount()
        expect(signal?.aborted).toBe(true)
    })

    describe("link validity preflight", () => {
        it("sanitizes the URL and shows the checking state with no password fields while pending", async () => {
            let release: (r: Response) => void = () => {}
            statusHandler = () => new Promise<Response>((resolve) => { release = resolve })
            open("#token=raw-token")
            const { container } = renderPage()

            expect(window.location.hash).toBe("")
            expect(window.location.href).not.toContain("raw-token")
            expect(screen.getByText(CHECKING)).toBeInTheDocument()
            expect(screen.queryByLabelText(LABEL)).not.toBeInTheDocument()
            expect(screen.queryByLabelText("Confirm passphrase")).not.toBeInTheDocument()
            expect(container.textContent).not.toContain("raw-token")

            await act(async () => {
                release(new Response(JSON.stringify({ valid: true }), { status: 200 }))
            })
            expect(await screen.findByLabelText(LABEL)).toBeInTheDocument()
            expect(screen.getByLabelText("Confirm passphrase")).toBeInTheDocument()
            expect(screen.queryByText(CHECKING)).not.toBeInTheDocument()
        })

        it("sends the token only in the status request body", async () => {
            await renderReady()
            expect(statusCalls()).toHaveLength(1)
            const [url, init] = statusCalls()[0] as [string, RequestInit]
            expect(url).toBe(STATUS_ENDPOINT)
            expect(init.method).toBe("POST")
            expect(JSON.parse(init.body as string)).toEqual({ token: "raw-token" })
            expect(url).not.toContain("raw-token")
        })

        it("shows the generic unavailable state, without password fields, for valid:false", async () => {
            statusHandler = () => statusResponse(false)
            open("#token=raw-token")
            const { container } = renderPage()
            expect(await screen.findByRole("heading", { name: INVALID_HEADING })).toBeInTheDocument()
            expect(screen.getByText(/no longer available/)).toBeInTheDocument()
            expect(screen.queryByLabelText(LABEL)).not.toBeInTheDocument()
            expect(screen.queryByLabelText("Confirm passphrase")).not.toBeInTheDocument()
            expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument()
            expect(container.textContent).not.toContain("raw-token")
            expect(resetCalls()).toHaveLength(0)
        })

        it("treats a definitive 4xx status response like valid:false", async () => {
            statusHandler = () => Promise.resolve(new Response("{}", { status: 403 }))
            open("#token=raw-token")
            renderPage()
            expect(await screen.findByRole("heading", { name: INVALID_HEADING })).toBeInTheDocument()
            expect(screen.queryByLabelText(LABEL)).not.toBeInTheDocument()
        })

        it("does not call the status endpoint without a token", () => {
            renderPage()
            expect(statusCalls()).toHaveLength(0)
        })

        it.each([
            ["a server error", () => Promise.resolve(new Response("{}", { status: 503 }))],
            ["a network failure", () => Promise.reject(new TypeError("offline"))],
        ])("offers Try again after %s without calling the link invalid", async (_name, failure) => {
            statusHandler = failure
            open("#token=raw-token")
            const { container } = renderPage()
            expect(await screen.findByText(CHECK_FAILED)).toBeInTheDocument()
            expect(screen.queryByRole("heading", { name: INVALID_HEADING })).not.toBeInTheDocument()
            expect(screen.queryByLabelText(LABEL)).not.toBeInTheDocument()
            expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument()
            expect(container.textContent).not.toContain("raw-token")
        })

        it("retry reuses the in-memory token and reaches the valid form", async () => {
            statusHandler = () => Promise.resolve(new Response("{}", { status: 503 }))
            open("#token=raw-token")
            renderPage()
            const retry = await screen.findByRole("button", { name: "Try again" })
            statusHandler = () => statusResponse(true)
            fireEvent.click(retry)
            expect(await screen.findByLabelText(LABEL)).toBeInTheDocument()
            expect(statusCalls()).toHaveLength(2)
            expect(JSON.parse((statusCalls()[1][1] as RequestInit).body as string)).toEqual({ token: "raw-token" })
            expect(window.location.hash).toBe("")
        })

        it("retry can end in the generic unavailable state", async () => {
            statusHandler = () => Promise.resolve(new Response("{}", { status: 500 }))
            open("#token=raw-token")
            renderPage()
            const retry = await screen.findByRole("button", { name: "Try again" })
            statusHandler = () => statusResponse(false)
            fireEvent.click(retry)
            expect(await screen.findByRole("heading", { name: INVALID_HEADING })).toBeInTheDocument()
        })

        it("handles rate limiting deliberately: wait message, Try again, never invalid", async () => {
            statusHandler = () => Promise.resolve(new Response("{}", { status: 429 }))
            open("#token=raw-token")
            renderPage()
            expect(await screen.findByText("Too many checks. Wait a moment, then try again.")).toBeInTheDocument()
            expect(screen.queryByRole("heading", { name: INVALID_HEADING })).not.toBeInTheDocument()
            expect(screen.queryByLabelText(LABEL)).not.toBeInTheDocument()
            statusHandler = () => statusResponse(true)
            fireEvent.click(screen.getByRole("button", { name: "Try again" }))
            expect(await screen.findByLabelText(LABEL)).toBeInTheDocument()
        })

        it("ignores a stale response from an aborted earlier request (StrictMode double effect)", async () => {
            const pending: ((r: Response) => void)[] = []
            statusHandler = () => {
                if (pending.length === 0) {
                    // First (StrictMode-discarded) request: stays open, ignores abort, answers late.
                    return new Promise<Response>((resolve) => {
                        pending.push(resolve)
                    })
                }
                return statusResponse(true)
            }
            open("#token=raw-token")
            renderPage(true)
            expect(await screen.findByLabelText(LABEL)).toBeInTheDocument()
            await act(async () => {
                pending[0](new Response(JSON.stringify({ valid: false }), { status: 200 }))
            })
            expect(screen.getByLabelText(LABEL)).toBeInTheDocument()
            expect(screen.queryByRole("heading", { name: INVALID_HEADING })).not.toBeInTheDocument()
        })

        it("aborts the status request on unmount and ignores its late answer", async () => {
            let signal: AbortSignal | undefined
            let release: (r: Response) => void = () => {}
            statusHandler = (init) => {
                signal = init.signal as AbortSignal
                return new Promise<Response>((resolve) => { release = resolve })
            }
            const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})
            open("#token=raw-token")
            const view = renderPage()
            await waitFor(() => expect(signal).toBeDefined())
            view.unmount()
            expect(signal?.aborted).toBe(true)
            await act(async () => {
                release(new Response(JSON.stringify({ valid: true }), { status: 200 }))
            })
            expect(errorSpy).not.toHaveBeenCalled()
            errorSpy.mockRestore()
        })

        it("still submits through POST /api/auth/password-reset after a valid check", async () => {
            await renderReady()
            fill(PASSWORD, PASSWORD)
            fireEvent.click(screen.getByRole("button", { name: BUTTON }))
            await screen.findByRole("link", { name: "Go to sign in" })
            expect(resetCalls()).toHaveLength(1)
            expect(statusCalls()).toHaveLength(1)
        })

        it.each([404, 429])("keeps handling a final-submit %s after a successful preflight", async (status) => {
            await renderReady()
            fetchMock.mockImplementation((url: string, init: RequestInit) =>
                url === STATUS_ENDPOINT ? statusHandler(init) : Promise.resolve(new Response("{}", { status })),
            )
            fill(PASSWORD, PASSWORD)
            fireEvent.click(screen.getByRole("button", { name: BUTTON }))
            const alert = await screen.findByRole("alert")
            expect(alert).toHaveTextContent(status === 404 ? /no longer available/ : /Too many attempts/)
        })

        it("never renders the raw token in any state", async () => {
            const { container } = await renderReady()
            expect(container.textContent).not.toContain("raw-token")
            expect(window.location.href).not.toContain("raw-token")
            expect(JSON.stringify({ ...window.localStorage, ...window.sessionStorage })).not.toContain("raw-token")
        })
    })
})
