/* eslint-disable react-refresh/only-export-components -- test support module: Fast Refresh does not apply to it. */
import { render } from "@testing-library/react"
import type { ReactNode } from "react"
import { Outlet, RouterProvider, createMemoryRouter } from "react-router"
import type { RouteObject } from "react-router"
import { vi } from "vitest"
import { AnnouncerProvider } from "../components/authoring/AnnouncerProvider"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { AuthenticatedOutletContext } from "../layouts/useAuthenticatedSession"
import type { SessionBootstrap } from "../types/bootstrap"

// Test support for the Phase 14 authoring pages: a data router (so useBlocker
// works), the session context with a CSRF token, the shared announcer, and the
// outlet context the authenticated shell supplies.

export interface FetchCall {
    method: string
    path: string
    headers: Record<string, string>
    body: unknown
}

export interface MockResponse {
    status?: number
    body?: unknown
    // Reject the request as a network failure instead of responding.
    networkError?: boolean
}

export type FetchHandler = (call: FetchCall) => MockResponse | Promise<MockResponse>

interface Route {
    method: string
    // A path prefix or exact path (without the /api prefix), or a regex.
    match: string | RegExp
    handler: FetchHandler | MockResponse
}

export interface MockServer {
    calls: FetchCall[]
    on: (method: string, match: string | RegExp, handler: FetchHandler | MockResponse) => void
    callsTo: (method: string, match: string | RegExp) => FetchCall[]
}

function matches(route: Route, call: FetchCall): boolean {
    if (route.method !== call.method) {
        return false
    }
    return typeof route.match === "string"
        ? call.path === route.match
        : route.match.test(call.path)
}

// Installs a fetch stub backed by a route table. Later registrations win, so a
// test can override a default. An unmatched request fails the test loudly.
export function installMockServer(): MockServer {
    const routes: Route[] = []
    const calls: FetchCall[] = []

    const fetchStub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString()
        const path = url.replace(/^\/api/, "")
        const method = (init?.method ?? "GET").toUpperCase()
        const headers = (init?.headers ?? {}) as Record<string, string>
        const body = init?.body ? JSON.parse(String(init.body)) : undefined
        const call: FetchCall = { method, path, headers, body }
        calls.push(call)

        const route = [...routes].reverse().find((r) => matches(r, call))
        if (route === undefined) {
            throw new Error(`Unmocked request: ${method} ${path}`)
        }
        const result =
            typeof route.handler === "function" ? await route.handler(call) : route.handler
        if (result.networkError) {
            throw new TypeError("Failed to fetch")
        }
        const status = result.status ?? 200
        return new Response(
            status === 204 || result.body === undefined ? null : JSON.stringify(result.body),
            { status, headers: { "Content-Type": "application/json" } },
        )
    })
    vi.stubGlobal("fetch", fetchStub)

    return {
        calls,
        on: (method, match, handler) => {
            routes.push({ method: method.toUpperCase(), match, handler })
        },
        callsTo: (method, match) =>
            calls.filter((c) =>
                matches({ method: method.toUpperCase(), match, handler: {} }, c),
            ),
    }
}

export const TEST_CSRF = "test-csrf-token"

export function bootstrapWith(overrides: Partial<SessionBootstrap> = {}): SessionBootstrap {
    return {
        ...sessionBootstrapFixture,
        csrf_token: TEST_CSRF,
        global_capabilities: ["world.create"],
        ...overrides,
    }
}

function Shell({ bootstrap, reload }: { bootstrap: SessionBootstrap; reload: () => void }) {
    return (
        <SessionContext.Provider
            value={{
                state: { status: "authenticated", bootstrap },
                reload,
                refresh: vi.fn(async () => true),
            }}
        >
            <AnnouncerProvider>
                <Outlet
                    context={{ bootstrap, reload } satisfies AuthenticatedOutletContext}
                />
            </AnnouncerProvider>
        </SessionContext.Provider>
    )
}

export interface RenderOptions {
    initialEntry: string
    routes: { path: string; element: ReactNode }[]
    bootstrap?: SessionBootstrap
    reload?: () => void
}

export function renderAuthoringRoutes({
    initialEntry,
    routes,
    bootstrap = bootstrapWith(),
    reload = vi.fn(),
}: RenderOptions) {
    const objects: RouteObject[] = [
        {
            element: <Shell bootstrap={bootstrap} reload={reload} />,
            children: [
                ...routes,
                { path: "*", element: <p>Unmatched route</p> },
            ],
        },
    ]
    const router = createMemoryRouter(objects, { initialEntries: [initialEntry] })
    const view = render(<RouterProvider router={router} />)
    return { ...view, router, reload }
}
