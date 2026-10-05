import { render } from "@testing-library/react"
import { RouterProvider, createMemoryRouter } from "react-router"
import { vi } from "vitest"
import App from "../App"
import { RouteSessionProvider } from "../context/RouteSessionProvider"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { useSessionBootstrap } from "../hooks/useSessionBootstrap"
import { ThemeProvider } from "../themes/ThemeProvider"
import type { SessionBootstrap } from "../types/bootstrap"
import { installMockServer } from "./authoringHarness"
import type { MockServer } from "./authoringHarness"

// Full-application route tests for the campaign shell. The caller must have
// `vi.mock("../hooks/useSessionBootstrap")` and `vi.mock("../api/userPreferences")`
// at the top of its own file (vi.mock is hoisted per file).

export const WORLD_BODY = {
    world_id: "world-mundivita",
    name: "Mundivita",
    description: null,
    lifecycle_status: "active",
    row_version: 1,
    primary_timeline_id: "timeline-primary",
    allowed_rulesets: [],
    timelines: [
        {
            timeline_id: "timeline-primary",
            name: "Primary Timeline",
            description: null,
            is_primary: true,
            parent_timeline_id: null,
            branch_point: null,
            lifecycle_status: "active",
            row_version: 1,
        },
    ],
    managed_campaigns: [],
    available_actions: [],
    blocked_actions: [],
}

export function bootstrapFor(capabilities: string[]): SessionBootstrap {
    return {
        ...sessionBootstrapFixture,
        csrf_token: "csrf-from-session",
        campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, capabilities }],
    }
}

// The shell-level requests every campaign page makes, answered with empty data.
export function installCampaignShellMocks(): MockServer {
    const server = installMockServer()
    server.on("GET", /^\/campaigns\/mundivita\/world\/search/, {
        body: { items: [], next_cursor: null },
    })
    server.on("GET", /^\/campaigns\/mundivita\/summary/, { body: {} })
    server.on("GET", /^\/worlds\?/, { body: { items: [], next_cursor: null } })
    server.on("GET", "/worlds/world-mundivita", { body: WORLD_BODY })
    return server
}

export function openApp(entry: string, capabilities: string[] = ["access.manage", "canon.edit"]) {
    vi.mocked(useSessionBootstrap).mockReturnValue({
        state: { status: "authenticated", bootstrap: bootstrapFor(capabilities) },
        reload: vi.fn(),
        refresh: vi.fn(),
    })
    const router = createMemoryRouter(
        [
            {
                path: "*",
                element: (
                    <ThemeProvider>
                        <RouteSessionProvider>
                            <App />
                        </RouteSessionProvider>
                    </ThemeProvider>
                ),
            },
        ],
        { initialEntries: [entry] },
    )
    return { router, ...render(<RouterProvider router={router} />) }
}
