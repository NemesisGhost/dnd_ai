import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { StrictMode } from "react"
import { MemoryRouter, Route, Routes } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ActivateAccountPage } from "./ActivateAccountPage"

const PASSWORD = "correct-password-15-chars"
const ROUTE = "/activate"
const ENDPOINT = "/api/auth/activate"
const STATUS_ENDPOINT = "/api/auth/activation-status"
const LABEL = "Choose a passphrase"
const BUTTON = "Activate account"
const INVALID_HEADING = "This activation link is not valid"
const INVALID_MESSAGE = "This activation link is invalid, expired, or has already been used."
const CHECKING = "Checking activation link…"

let fetchMock: ReturnType<typeof vi.fn>
let statusImpl: (init: RequestInit) => Promise<Response>
let activateImpl: (init: RequestInit) => Promise<Response>

function json(body: unknown, status = 200) {
    return Promise.resolve(new Response(JSON.stringify(body), { status }))
}

function renderPage(strict = false) {
    const tree = (
        <MemoryRouter initialEntries={[ROUTE]}>
            <Routes>
                <Route path={ROUTE} element={<ActivateAccountPage />} />
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

function callsTo(url: string) {
    return fetchMock.mock.calls.filter((c) => c[0] === url) as [string, RequestInit][]
}

async function ready() {
    await screen.findByLabelText(LABEL)
}

beforeEach(() => {
    statusImpl = () => json({ valid: true })
    activateImpl = () => json({ user_id: "u1", login_name: "new.gm" })
    fetchMock = vi.fn((url: string, init: RequestInit) => (url === STATUS_ENDPOINT ? statusImpl(init) : activateImpl(init)))
    vi.stubGlobal("fetch", fetchMock)
    window.localStorage.clear()
    window.sessionStorage.clear()
    open("")
})

afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
})

describe("ActivateAccountPage missing or malformed link", () => {
    it("shows a truthful missing-link state with no fragment and sends nothing", () => {
        renderPage()
        expect(screen.getByRole("heading", { name: INVALID_HEADING })).toBeInTheDocument()
        expect(screen.getByText(/refreshing the page cannot recover it/)).toBeInTheDocument()
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
})

describe("ActivateAccountPage link check", () => {
    it("removes the fragment, shows Checking with no password fields, then the form", async () => {
        let release: (r: Response) => void = () => {}
        statusImpl = () => new Promise<Response>((resolve) => { release = resolve })
        open("#token=raw-token")
        renderPage()

        expect(window.location.hash).toBe("")
        expect(window.location.href).not.toContain("raw-token")
        expect(screen.getByRole("status")).toHaveTextContent(CHECKING)
        expect(screen.queryByLabelText(LABEL)).not.toBeInTheDocument()
        expect(document.querySelector("input")).toBeNull()
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        expect(screen.getAllByRole("main")).toHaveLength(1)

        await act(async () => {
            release(new Response(JSON.stringify({ valid: true }), { status: 200 }))
        })
        await ready()
        expect(screen.getByRole("heading", { level: 1, name: "Set passphrase" })).toHaveFocus()
        expect(screen.getByLabelText(LABEL)).toHaveAttribute("autocomplete", "new-password")
        expect(screen.getByLabelText("Confirm passphrase")).toHaveAttribute("autocomplete", "new-password")
        expect(callsTo(ENDPOINT)).toHaveLength(0)
    })

    it("sends the token only in the JSON body of a POST", async () => {
        open("#token=raw%20token%2F1")
        renderPage()
        await ready()
        const [url, init] = callsTo(STATUS_ENDPOINT)[0]
        expect(url).toBe(STATUS_ENDPOINT)
        expect(init.method).toBe("POST")
        expect(JSON.parse(init.body as string)).toEqual({ token: "raw token/1" })
        expect(url).not.toContain("raw")
    })

    it.each([
        ["valid:false", () => json({ valid: false })],
        ["a non-disclosing 4xx", () => json({ error: "x" }, 404)],
    ])("renders one generic terminal state without password fields for %s", async (_name, impl) => {
        statusImpl = impl
        open("#token=raw-token")
        const { container } = renderPage()
        expect(await screen.findByText(INVALID_MESSAGE)).toBeInTheDocument()
        expect(screen.getByRole("heading", { level: 1, name: INVALID_HEADING })).toHaveFocus()
        expect(container.querySelector("input")).toBeNull()
        expect(container.innerHTML).not.toContain("raw-token")
        expect(callsTo(ENDPOINT)).toHaveLength(0)
    })

    it("shows Retry (not invalid) on a network failure, and Retry rechecks current state", async () => {
        statusImpl = () => Promise.reject(new TypeError("offline"))
        open("#token=raw-token")
        renderPage()
        const retry = await screen.findByRole("button", { name: "Retry" })
        expect(screen.queryByText(INVALID_MESSAGE)).not.toBeInTheDocument()
        expect(document.querySelector("input")).toBeNull()

        statusImpl = () => json({ valid: true })
        fireEvent.click(retry)
        fireEvent.click(retry)
        await ready()
        expect(callsTo(STATUS_ENDPOINT)).toHaveLength(2)
    })

    it.each([500, 503, 429])("treats %s as recoverable", async (status) => {
        statusImpl = () => json({}, status)
        open("#token=raw-token")
        renderPage()
        expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument()
        expect(screen.queryByText(INVALID_MESSAGE)).not.toBeInTheDocument()
    })

    it("sends one request per attempt while a Retry check is in flight", async () => {
        statusImpl = () => Promise.reject(new TypeError("offline"))
        open("#token=raw-token")
        renderPage()
        const retry = await screen.findByRole("button", { name: "Retry" })
        statusImpl = () => new Promise<Response>(() => {})
        fireEvent.click(retry)
        expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument()
        expect(screen.getByRole("status")).toHaveTextContent(CHECKING)
        expect(callsTo(STATUS_ENDPOINT)).toHaveLength(2)
    })

    it("is safe under StrictMode: the superseded check is aborted and one result applies", async () => {
        open("#token=raw-token")
        renderPage(true)
        await ready()
        const calls = callsTo(STATUS_ENDPOINT)
        const live = calls.filter(([, init]) => !(init.signal as AbortSignal).aborted)
        expect(live).toHaveLength(1)
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
    })

    it("aborts the in-flight check on unmount", async () => {
        let signal: AbortSignal | undefined
        statusImpl = (init) => {
            signal = init.signal as AbortSignal
            return new Promise<Response>(() => {})
        }
        open("#token=raw-token")
        const view = renderPage()
        await waitFor(() => expect(signal).toBeDefined())
        view.unmount()
        expect(signal?.aborted).toBe(true)
    })

    it("lets an older slow response lose to a newer link", async () => {
        const releases: Record<string, (r: Response) => void> = {}
        statusImpl = (init) => {
            const { token } = JSON.parse(init.body as string) as { token: string }
            return new Promise<Response>((resolve) => { releases[token] = resolve })
        }
        open("#token=old-token")
        renderPage()
        await waitFor(() => expect(releases["old-token"]).toBeDefined())

        act(() => {
            window.history.replaceState(null, "", ROUTE + "#token=new-token")
            window.dispatchEvent(new HashChangeEvent("hashchange"))
        })
        await waitFor(() => expect(releases["new-token"]).toBeDefined())
        expect(window.location.hash).toBe("")

        await act(async () => {
            releases["old-token"](new Response(JSON.stringify({ valid: true }), { status: 200 }))
        })
        expect(screen.queryByLabelText(LABEL)).not.toBeInTheDocument()
        expect(screen.getByRole("status")).toHaveTextContent(CHECKING)

        await act(async () => {
            releases["new-token"](new Response(JSON.stringify({ valid: false }), { status: 200 }))
        })
        expect(await screen.findByText(INVALID_MESSAGE)).toBeInTheDocument()
    })
})

describe("ActivateAccountPage activation", () => {
    it("blocks submission and announces a mismatch", async () => {
        open("#token=raw-token")
        renderPage()
        await ready()
        fill(PASSWORD, PASSWORD + "x")
        const alert = screen.getByRole("alert")
        expect(alert).toHaveTextContent("The passphrases do not match.")
        expect(screen.getByLabelText("Confirm passphrase")).toHaveAttribute("aria-describedby", alert.id)
        expect(screen.getByLabelText("Confirm passphrase")).toHaveAttribute("aria-invalid", "true")
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        expect(callsTo(ENDPOINT)).toHaveLength(0)
    })

    it("sends exactly one activation POST with secrets only in the body, even on double submit", async () => {
        open("#token=raw%20token%2F1")
        renderPage(true)
        await ready()
        fill(PASSWORD, PASSWORD)
        const button = screen.getByRole("button", { name: BUTTON })
        fireEvent.click(button)
        fireEvent.click(button)

        await screen.findByRole("link", { name: "Go to sign in" })
        const sent = callsTo(ENDPOINT)
        expect(sent).toHaveLength(1)
        const [url, init] = sent[0]
        expect(url).toBe(ENDPOINT)
        expect(init.method).toBe("POST")
        const body = JSON.parse(init.body as string) as { token: string; password: string }
        expect(body).toEqual({ token: "raw token/1", password: PASSWORD })
        expect(url).not.toContain("raw")
        const stored = JSON.stringify({ ...window.localStorage, ...window.sessionStorage })
        expect(stored).not.toContain(PASSWORD)
        expect(stored).not.toContain("raw")
    })

    it("disables fields and submit while pending", async () => {
        let release: (r: Response) => void = () => {}
        activateImpl = () => new Promise<Response>((resolve) => { release = resolve })
        open("#token=raw-token")
        renderPage()
        await ready()
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await waitFor(() => expect(screen.getByLabelText(LABEL)).toBeDisabled())
        expect(screen.getByLabelText("Confirm passphrase")).toBeDisabled()
        expect(screen.getByRole("button")).toBeDisabled()
        await act(async () => {
            release(new Response("{}", { status: 500 }))
        })
    })

    it("clears secrets after success so nothing remains rendered", async () => {
        open("#token=raw-token")
        const { container } = renderPage()
        await ready()
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await screen.findByRole("link", { name: "Go to sign in" })
        expect(container.innerHTML).not.toContain("raw-token")
        expect(container.querySelector("input")).toBeNull()
    })

    it("a valid check does not bypass final activation: a token that went bad ends in the generic terminal state", async () => {
        activateImpl = () => json({ error: "unavailable" }, 404)
        open("#token=raw-token")
        const { container } = renderPage()
        await ready()
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))

        expect(await screen.findByText(INVALID_MESSAGE)).toBeInTheDocument()
        expect(container.querySelector("input")).toBeNull()
        expect(container.innerHTML).not.toContain(PASSWORD)
        expect(screen.queryByRole("button", { name: BUTTON })).not.toBeInTheDocument()
        expect(callsTo(ENDPOINT)).toHaveLength(1)
        // Terminal: nothing re-checks or re-submits on its own.
        await act(async () => {})
        expect(callsTo(ENDPOINT)).toHaveLength(1)
        expect(callsTo(STATUS_ENDPOINT)).toHaveLength(1)
    })

    it("treats a final 409 login-name conflict after a valid check as the same generic terminal state", async () => {
        activateImpl = () => json({ error: { code: "login_name_taken", message: "That login name was claimed" } }, 409)
        open("#token=raw-token")
        const { container } = renderPage()
        await ready()
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))

        expect(await screen.findByText(INVALID_MESSAGE)).toBeInTheDocument()
        expect(screen.getByRole("heading", { level: 1, name: INVALID_HEADING })).toBeInTheDocument()
        expect(container.querySelector("input")).toBeNull()
        expect(screen.queryByRole("button", { name: BUTTON })).not.toBeInTheDocument()
        expect(container.innerHTML).not.toContain(PASSWORD)
        expect(container.innerHTML).not.toContain("raw-token")
        expect(container.textContent).not.toContain("login name")
        await act(async () => {})
        expect(callsTo(ENDPOINT)).toHaveLength(1)
        expect(callsTo(STATUS_ENDPOINT)).toHaveLength(1)
    })

    it.each([500, 502, 429])("keeps a final %s retryable, not terminal", async (status) => {
        activateImpl = () => json({}, status)
        open("#token=raw-token")
        renderPage()
        await ready()
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await screen.findByRole("alert")
        expect(screen.queryByText(INVALID_MESSAGE)).not.toBeInTheDocument()
        expect(screen.getByLabelText(LABEL)).toHaveValue(PASSWORD)
    })

    it("keeps the token in memory so a recoverable final error can be retried", async () => {
        activateImpl = () => json({}, 500)
        open("#token=raw-token")
        renderPage()
        await ready()
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await screen.findByText(/Try again/)
        expect(screen.getByLabelText(LABEL)).toHaveValue(PASSWORD)

        activateImpl = () => json({ user_id: "u1", login_name: "new.gm" })
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await screen.findByRole("link", { name: "Go to sign in" })
        expect(callsTo(ENDPOINT)).toHaveLength(2)
        expect(JSON.parse(callsTo(ENDPOINT)[1][1].body as string).token).toBe("raw-token")
        expect(callsTo(STATUS_ENDPOINT)).toHaveLength(1)
    })

    it("aborts the in-flight activation request on unmount", async () => {
        let signal: AbortSignal | undefined
        activateImpl = (init) => {
            signal = init.signal as AbortSignal
            return new Promise<Response>(() => {})
        }
        open("#token=raw-token")
        const view = renderPage()
        await ready()
        fill(PASSWORD, PASSWORD)
        fireEvent.click(screen.getByRole("button", { name: BUTTON }))
        await waitFor(() => expect(signal).toBeDefined())
        view.unmount()
        expect(signal?.aborted).toBe(true)
    })
})
