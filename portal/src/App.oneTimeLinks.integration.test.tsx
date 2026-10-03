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
let linkValid: boolean

function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    const path = String(input)
    const method = init?.method ?? "GET"
    const body = typeof init?.body === "string" ? init.body : null
    calls.push({ method, path, body })
    if (method === "POST" && path === "/api/auth/activation-status") {
        return Promise.resolve(new Response(JSON.stringify({ valid: linkValid }), { status: 200 }))
    }
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
    linkValid = true
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

    it("activation link checks first, sanitizes the URL, then activates with one POST", async () => {
        mountAtLink(buildFragmentLink("/activate", RAW_TOKEN), true)

        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        expect(window.location.hash).toBe("")
        expect(window.location.href).not.toContain(RAW_TOKEN)
        expect(screen.getByText("Checking activation link…")).toBeInTheDocument()
        expect(screen.queryByLabelText("Choose a passphrase")).not.toBeInTheDocument()

        fireEvent.change(await screen.findByLabelText("Choose a passphrase"), { target: { value: PASSWORD } })
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

    it("an unusable link never shows password fields and never posts an activation", async () => {
        linkValid = false
        mountAtLink(buildFragmentLink("/activate", RAW_TOKEN))
        expect(
            await screen.findByText("This activation link is invalid, expired, or has already been used."),
        ).toBeInTheDocument()
        expect(screen.queryByLabelText("Choose a passphrase")).not.toBeInTheDocument()
        expect(posts("/api/auth/activate")).toHaveLength(0)
        expect(posts("/api/auth/activation-status")).toHaveLength(1)
    })

    it("a token that goes bad after a valid check ends generically at final activation", async () => {
        activateStatus = 404
        mountAtLink(buildFragmentLink("/activate", RAW_TOKEN))
        fireEvent.change(await screen.findByLabelText("Choose a passphrase"), { target: { value: PASSWORD } })
        const confirm = screen.queryByLabelText(/confirm/i)
        if (confirm !== null) fireEvent.change(confirm, { target: { value: PASSWORD } })
        fireEvent.click(screen.getByRole("button", { name: "Activate account" }))
        await waitFor(() => expect(posts("/api/auth/activate")).toHaveLength(1))
        expect(
            await screen.findByText("This activation link is invalid, expired, or has already been used."),
        ).toBeInTheDocument()
        expect(screen.queryByLabelText("Choose a passphrase")).not.toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: "Account activated" })).not.toBeInTheDocument()
    })

    it("leaves the reset and login routes unaffected by the activation check", async () => {
        mountAtLink(buildFragmentLink("/reset-password", RAW_TOKEN))
        expect(posts("/api/auth/activation-status")).toHaveLength(0)
        cleanup()
        mountAtLink(`${window.location.origin}/login`)
        expect(posts("/api/auth/activation-status")).toHaveLength(0)
    })

    it.each(["/activate", "/reset-password"])("%s with a malformed fragment is generic and silent", (path) => {
        mountAtLink(`${window.location.origin}${path}#token=%`)
        expect(window.location.hash).toBe("")
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        expect(screen.getByRole("heading", { name: /link is not valid/ })).toBeInTheDocument()
        expect(calls.filter((c) => c.method === "POST")).toHaveLength(0)
    })

    it("password-reset link renders the React page and sanitizes the URL", () => {
        mountAtLink(buildFragmentLink("/reset-password", RAW_TOKEN))
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        expect(window.location.hash).toBe("")
        expect(window.location.pathname).toBe("/reset-password")
    })
})
