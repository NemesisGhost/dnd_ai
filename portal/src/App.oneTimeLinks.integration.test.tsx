import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { StrictMode } from "react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import App from "./App"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import { ThemeProvider } from "./themes/ThemeProvider"
import { buildFragmentLink } from "./utils/oneTimeLink"

// Regression: the admin-generated activation/reset links must open a React
// page, not the POST-only backend `/auth/*` endpoints that the dev proxy
// (and a production reverse proxy) forwards to the API. Mounts the real
// <App /> at the path of a link produced by the real builder, fakes only fetch.

const RAW_TOKEN = "raw-activation-token-DO-NOT-LEAK"
const PASSWORD = "correct horse battery staple"

let calls: { method: string; path: string; body: string | null }[]
let activateStatus: number

function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    const path = String(input)
    const method = init?.method ?? "GET"
    const body = typeof init?.body === "string" ? init.body : null
    calls.push({ method, path, body })
    if (method === "POST" && (path === "/api/auth/activate" || path === "/api/auth/password-reset")) {
        return Promise.resolve(
            activateStatus === 200
                ? new Response(JSON.stringify({ user_id: "u1", login_name: "test1" }), { status: 200 })
                : new Response(JSON.stringify({ error: "unavailable" }), { status: activateStatus }),
        )
    }
    return Promise.resolve(new Response(JSON.stringify({ error: "unauthenticated" }), { status: 401 }))
}

function mountAtLink(link: string, strict = false) {
    const url = new URL(link)
    window.history.replaceState(null, "", url.pathname + url.search + url.hash)
    const tree = (
        <ThemeProvider>
            <MemoryRouter initialEntries={[url.pathname + url.search]}>
                <RouteSessionProvider>
                    <App />
                </RouteSessionProvider>
            </MemoryRouter>
        </ThemeProvider>
    )
    return render(strict ? <StrictMode>{tree}</StrictMode> : tree)
}

function posts(path: string) {
    return calls.filter((c) => c.method === "POST" && c.path === path)
}

beforeEach(() => {
    calls = []
    activateStatus = 200
    vi.stubGlobal("fetch", vi.fn(fakeFetch))
    window.localStorage.clear()
    window.sessionStorage.clear()
})

afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
})

describe("generated one-time links", () => {
    it("never target a backend-proxied /auth path", () => {
        for (const path of ["/activate", "/reset-password"]) {
            const url = new URL(buildFragmentLink(path, RAW_TOKEN))
            expect(url.pathname.startsWith("/auth")).toBe(false)
            expect(url.search).toBe("")
        }
    })

    it("activation link renders the React page, sanitizes the URL, and posts once", async () => {
        mountAtLink(buildFragmentLink("/activate", RAW_TOKEN), true)

        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        expect(window.location.hash).toBe("")
        expect(window.location.href).not.toContain(RAW_TOKEN)

        fireEvent.change(screen.getByLabelText("Choose a passphrase"), { target: { value: PASSWORD } })
        const confirm = screen.queryByLabelText(/confirm/i)
        if (confirm !== null) fireEvent.change(confirm, { target: { value: PASSWORD } })
        const button = screen.getByRole("button", { name: "Activate account" })
        fireEvent.click(button)
        fireEvent.click(button)

        await screen.findByRole("heading", { name: "Account activated" })
        const sent = posts("/api/auth/activate")
        expect(sent).toHaveLength(1)
        expect(JSON.parse(sent[0].body ?? "{}")).toEqual({ token: RAW_TOKEN, password: PASSWORD })
        expect(screen.getByRole("link", { name: "Go to sign in" })).toHaveAttribute("href", "/login")
        expect(calls.some((c) => c.method === "GET" && c.path.includes("activate"))).toBe(false)
        expect(JSON.stringify({ ...window.localStorage })).not.toContain(RAW_TOKEN)
        expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(PASSWORD)
    })

    it("shows the missing-link state after a refresh of the sanitized URL", () => {
        mountAtLink(buildFragmentLink("/activate", RAW_TOKEN))
        cleanup()
        mountAtLink(`${window.location.origin}${window.location.pathname}`)
        expect(
            screen.getByRole("heading", { name: "This activation link is not valid" }),
        ).toBeInTheDocument()
        expect(posts("/api/auth/activate")).toHaveLength(0)
    })

    it("surfaces a consumed/expired activation token without activating", async () => {
        activateStatus = 404
        mountAtLink(buildFragmentLink("/activate", RAW_TOKEN))
        fireEvent.change(screen.getByLabelText("Choose a passphrase"), { target: { value: PASSWORD } })
        const confirm = screen.queryByLabelText(/confirm/i)
        if (confirm !== null) fireEvent.change(confirm, { target: { value: PASSWORD } })
        fireEvent.click(screen.getByRole("button", { name: "Activate account" }))
        await waitFor(() => expect(posts("/api/auth/activate")).toHaveLength(1))
        expect(screen.queryByRole("heading", { name: "Account activated" })).not.toBeInTheDocument()
    })

    it("password-reset link renders the React page and sanitizes the URL", () => {
        mountAtLink(buildFragmentLink("/reset-password", RAW_TOKEN))
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        expect(window.location.hash).toBe("")
        expect(window.location.pathname).toBe("/reset-password")
    })
})
