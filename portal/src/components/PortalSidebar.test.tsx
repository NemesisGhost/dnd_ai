import {
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from "@testing-library/react"
import { MemoryRouter, Route, Routes, useLocation } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { CharacterPerspectiveContext } from "../context/CharacterPerspectiveContext"
import { SessionContext } from "../context/SessionContext"
import { WorkspaceHierarchyProvider } from "../context/WorkspaceHierarchyProvider"
import { installMockServer } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { SIDEBAR_COLLAPSED_STORAGE_KEY } from "../hooks/useSidebarCollapsed"
import { useNavigationDrawer } from "../hooks/useNavigationDrawer"
import type { SessionBootstrapState } from "../hooks/useSessionBootstrap"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"
import { PortalSidebar } from "./PortalSidebar"

const first: CampaignContext = {
    ...sessionBootstrapFixture.campaigns[0]!,
    campaign_id: "campaign-a",
    campaign_name: "Alpha Campaign",
    capabilities: [],
}
const second: CampaignContext = {
    ...first,
    campaign_id: "campaign-b",
    campaign_name: "Beta Campaign",
    capabilities: ["access.manage"],
}

function makeBootstrap(overrides: Partial<SessionBootstrap> = {}): SessionBootstrap {
    return {
        ...sessionBootstrapFixture,
        startup_campaign_id: null,
        campaign_preferences: {
            startup_mode: "resume_last_visited",
            preferred_campaign_id: null,
            last_visited_campaign_id: null,
        },
        campaigns: [first, second],
        ...overrides,
    }
}

const selectCharacter = vi.fn()

function LocationProbe() {
    const location = useLocation()
    return <p data-testid="location">{location.pathname}</p>
}

function Harness() {
    const { control: drawer, toggleRef } = useNavigationDrawer()
    return (
        <>
            <button
                ref={toggleRef}
                type="button"
                onClick={drawer.toggle}
                aria-expanded={drawer.open}
            >
                Header toggle
            </button>
            <PortalSidebar drawer={drawer} />
            <a href="/outside">Outside link</a>
        </>
    )
}

function renderSidebar(
    path: string,
    state: SessionBootstrapState = {
        status: "authenticated",
        bootstrap: makeBootstrap(),
    },
) {
    return render(
        <SessionContext.Provider value={{ state, reload: vi.fn(), refresh: vi.fn() }}>
            <CharacterPerspectiveContext.Provider
                value={{
                    getSelectedCharacterId: () => null,
                    selectCharacter,
                }}
            >
                <MemoryRouter initialEntries={[path]}>
                    <WorkspaceHierarchyProvider>
                        <Routes>
                            <Route path="*" element={<Harness />} />
                        </Routes>
                        <LocationProbe />
                    </WorkspaceHierarchyProvider>
                </MemoryRouter>
            </CharacterPerspectiveContext.Provider>
        </SessionContext.Provider>,
    )
}

function openWorlds() {
    fireEvent.click(within(nav()).getByRole("button", { name: "Worlds" }))
}

function authenticated(bootstrap: SessionBootstrap): SessionBootstrapState {
    return { status: "authenticated", bootstrap }
}

function nav() {
    return screen.getByRole("navigation", { name: "Main" })
}

const worldDetail = {
    world_id: "world-a",
    name: "World A",
    timelines: [
        { timeline_id: "timeline-a", name: "Timeline A" },
        { timeline_id: "timeline-b", name: "Timeline B" },
    ],
}

let server: MockServer

beforeEach(() => {
    selectCharacter.mockReset()
    window.localStorage.clear()
    // Only world-a is authorized; any other world ID is an unmocked request,
    // which the stub fails — the same observable outcome as a 404.
    server = installMockServer()
    server.on("GET", "/worlds/world-a", { body: worldDetail })
})

afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
})

describe("PortalSidebar destinations", () => {
    it("targets the route campaign for every campaign-specific link", () => {
        renderSidebar("/app/campaign-a/home")

        const expected: Array<[string, string]> = [
            ["Campaign Home", "/app/campaign-a/home"],
            ["Characters", "/app/campaign-a/characters"],
            ["Quests", "/app/campaign-a/quests"],
            ["Sessions", "/app/campaign-a/sessions"],
            ["Knowledge", "/app/campaign-a/knowledge"],
        ]
        for (const [name, href] of expected) {
            expect(within(nav()).getByRole("link", { name })).toHaveAttribute(
                "href",
                href,
            )
        }
    })

    it("nests the campaign world page under Worlds, not as its own item", () => {
        renderSidebar("/app/campaign-a/home")
        openWorlds()

        expect(
            within(nav()).getByRole("link", { name: "Campaign world" }),
        ).toHaveAttribute("href", "/app/campaign-a/world")
        expect(within(nav()).queryByRole("link", { name: "World" })).toBeNull()
    })

    it("marks the active route with aria-current", () => {
        renderSidebar("/app/campaign-a/quests")

        expect(within(nav()).getByRole("link", { name: "Quests" })).toHaveAttribute(
            "aria-current",
            "page",
        )
        expect(
            within(nav()).getByRole("link", { name: "Characters" }),
        ).not.toHaveAttribute("aria-current")
    })

    it("keeps Ask visibly disabled without making it a link", () => {
        renderSidebar("/app/campaign-a/home")

        expect(
            within(nav()).queryByRole("link", { name: "Ask" }),
        ).not.toBeInTheDocument()
        const label = within(nav()).getByText("Ask")
        expect(label.closest("[aria-disabled='true']")).toHaveAttribute(
            "title",
            "Unavailable until Phase 12 is verified",
        )
    })

    it("links Ask only when the feature manifest enables it", () => {
        renderSidebar(
            "/app/campaign-a/home",
            authenticated(
                makeBootstrap({
                    features: { ...sessionBootstrapFixture.features, ask: true },
                }),
            ),
        )

        expect(within(nav()).getByRole("link", { name: "Ask" })).toHaveAttribute(
            "href",
            "/app/campaign-a/ask",
        )
    })
})

describe("PortalSidebar campaign resolution", () => {
    it("shows on global routes and targets last visited", () => {
        renderSidebar(
            "/settings",
            authenticated(
                makeBootstrap({
                    campaign_preferences: {
                        startup_mode: "resume_last_visited",
                        preferred_campaign_id: null,
                        last_visited_campaign_id: "campaign-b",
                    },
                }),
            ),
        )

        expect(within(nav()).getByRole("link", { name: "Quests" })).toHaveAttribute(
            "href",
            "/app/campaign-b/quests",
        )
        expect(
            within(nav()).getByRole("link", { name: "Quests" }),
        ).not.toHaveAttribute("aria-current")
    })

    it("falls back to the startup campaign", () => {
        renderSidebar(
            "/account",
            authenticated(makeBootstrap({ startup_campaign_id: "campaign-a" })),
        )

        openWorlds()
        expect(
            within(nav()).getByRole("link", { name: "Campaign world" }),
        ).toHaveAttribute("href", "/app/campaign-a/world")
    })

    it("never builds a link from an unauthorized route campaign", () => {
        renderSidebar(
            "/app/ghost-campaign/home",
            authenticated(makeBootstrap({ startup_campaign_id: "campaign-a" })),
        )

        expect(nav().innerHTML).not.toContain("ghost-campaign")
        openWorlds()
        expect(
            within(nav()).getByRole("link", { name: "Campaign world" }),
        ).toHaveAttribute("href", "/app/campaign-a/world")
    })

    it("keeps campaign destinations as disabled slots with no resolvable campaign", () => {
        renderSidebar("/campaigns")

        for (const name of ["Campaign world", "Characters", "Ask"]) {
            expect(
                within(nav()).queryByRole("link", { name }),
            ).not.toBeInTheDocument()
        }
        expect(disabledEntry("Ask")).toBeInTheDocument()
        expect(disabledEntry("Characters")).toBeInTheDocument()
    })

    it("handles an account with no campaigns", () => {
        renderSidebar(
            "/campaigns",
            authenticated(makeBootstrap({ campaigns: [] })),
        )

        const group = within(nav()).getByRole("button", {
            name: "Choose campaign",
        })
        expect(group).toBeInTheDocument()
        expect(disabledEntry("Campaign Home")).toBeInTheDocument()
        expect(
            within(nav()).getByRole("link", { name: "View all campaigns" }),
        ).toHaveAttribute("href", "/campaigns")
    })
})

describe("PortalSidebar campaign submenu", () => {
    it("lists only bootstrap-authorized campaigns plus View all campaigns", () => {
        renderSidebar("/campaigns")

        const list = document.getElementById(
            within(nav())
                .getByRole("button", { name: "Choose campaign" })
                .getAttribute("aria-controls")!,
        )!
        const links = within(list).getAllByRole("link")

        expect(links.map((link) => link.textContent)).toEqual([
            "Alpha Campaign",
            "Beta Campaign",
            "View all campaigns",
        ])
        expect(links.map((link) => link.getAttribute("href"))).toEqual([
            "/app/campaign-a/home",
            "/app/campaign-b/home",
            "/campaigns",
        ])
    })

    it("is open on /campaigns and closed elsewhere", () => {
        const { unmount } = renderSidebar("/campaigns")
        expect(
            within(nav()).getByRole("button", { name: "Choose campaign" }),
        ).toHaveAttribute("aria-expanded", "true")
        unmount()

        renderSidebar("/app/campaign-a/home")
        const button = within(nav()).getByRole("button", { name: "Choose campaign" })
        expect(button).toHaveAttribute("aria-expanded", "false")
        expect(
            within(nav()).queryByRole("link", { name: "Beta Campaign" }),
        ).not.toBeInTheDocument()
    })

    it("uses separate controls for navigation and disclosure", () => {
        renderSidebar("/app/campaign-a/home")

        expect(
            within(nav()).getByRole("link", { name: "Campaign Home" }),
        ).toHaveAttribute("href", "/app/campaign-a/home")
        const button = within(nav()).getByRole("button", { name: "Choose campaign" })

        fireEvent.click(button)

        expect(button).toHaveAttribute("aria-expanded", "true")
        expect(screen.getByTestId("location")).toHaveTextContent(
            "/app/campaign-a/home",
        )
    })

    it("marks only the authorized route campaign with aria-current", () => {
        renderSidebar(
            "/app/campaign-b/quests",
            authenticated(makeBootstrap({ startup_campaign_id: "campaign-a" })),
        )
        fireEvent.click(within(nav()).getByRole("button", { name: "Choose campaign" }))

        expect(
            within(nav()).getByRole("link", { name: "Beta Campaign" }),
        ).toHaveAttribute("aria-current", "true")
        expect(
            within(nav()).getByRole("link", { name: "Alpha Campaign" }),
        ).not.toHaveAttribute("aria-current")
    })

    it("does not mark a fallback-resolved campaign current on a global route", () => {
        renderSidebar(
            "/settings",
            authenticated(makeBootstrap({ startup_campaign_id: "campaign-a" })),
        )
        fireEvent.click(within(nav()).getByRole("button", { name: "Choose campaign" }))

        expect(
            within(nav()).getByRole("link", { name: "Alpha Campaign" }),
        ).not.toHaveAttribute("aria-current")
    })

    it("navigates to the chosen campaign Home and clears that campaign perspective", () => {
        renderSidebar("/app/campaign-a/quests/quest-7")
        fireEvent.click(within(nav()).getByRole("button", { name: "Choose campaign" }))

        fireEvent.click(within(nav()).getByRole("link", { name: "Beta Campaign" }))

        expect(selectCharacter).toHaveBeenCalledWith("campaign-b", null)
        expect(screen.getByTestId("location")).toHaveTextContent(
            "/app/campaign-b/home",
        )
    })

    it("does not clear the perspective when the active campaign is re-selected", () => {
        renderSidebar("/app/campaign-a/quests")
        fireEvent.click(within(nav()).getByRole("button", { name: "Choose campaign" }))

        fireEvent.click(within(nav()).getByRole("link", { name: "Alpha Campaign" }))

        expect(selectCharacter).not.toHaveBeenCalled()
    })

    it("goes to the complete list through View all campaigns", () => {
        renderSidebar("/app/campaign-a/home")
        fireEvent.click(within(nav()).getByRole("button", { name: "Choose campaign" }))

        fireEvent.click(
            within(nav()).getByRole("link", { name: "View all campaigns" }),
        )

        expect(screen.getByTestId("location")).toHaveTextContent("/campaigns")
    })

    it("closes on Escape and returns focus to the disclosure button", () => {
        renderSidebar("/app/campaign-a/home")
        const button = within(nav()).getByRole("button", { name: "Choose campaign" })
        fireEvent.click(button)

        fireEvent.keyDown(
            within(nav()).getByRole("link", { name: "Beta Campaign" }),
            { key: "Escape" },
        )

        expect(button).toHaveAttribute("aria-expanded", "false")
        expect(button).toHaveFocus()
    })

    it("closes on an outside pointer press", () => {
        renderSidebar("/app/campaign-a/home")
        const button = within(nav()).getByRole("button", { name: "Choose campaign" })
        fireEvent.click(button)

        fireEvent.pointerDown(screen.getByText("Outside link"))

        expect(button).toHaveAttribute("aria-expanded", "false")
    })
})

describe("PortalSidebar Access group", () => {
    it("is hidden without access.manage", () => {
        renderSidebar("/app/campaign-a/home")

        expect(
            screen.queryByRole("button", { name: "Access" }),
        ).not.toBeInTheDocument()
    })

    it("offers Access Management, Invitations, and Audit History when authorized", () => {
        renderSidebar("/app/campaign-b/home")
        const button = screen.getByRole("button", { name: "Access" })
        expect(button).toHaveAttribute("aria-expanded", "false")

        fireEvent.click(button)

        expect(
            screen.getByRole("link", { name: "Access Management" }),
        ).toHaveAttribute("href", "/app/campaign-b/access")
        expect(screen.getByRole("link", { name: "Invitations" })).toHaveAttribute(
            "href",
            "/app/campaign-b/access/invitations",
        )
        expect(
            screen.getByRole("link", { name: "Audit History" }),
        ).toHaveAttribute("href", "/app/campaign-b/access/audit")
    })

    it("targets the resolved campaign on a global route", () => {
        renderSidebar(
            "/settings",
            authenticated(makeBootstrap({ startup_campaign_id: "campaign-b" })),
        )
        fireEvent.click(screen.getByRole("button", { name: "Access" }))

        expect(
            screen.getByRole("link", { name: "Access Management" }),
        ).toHaveAttribute("href", "/app/campaign-b/access")
    })

    it("marks the parent active and opens for an active child route", () => {
        renderSidebar("/app/campaign-b/access/audit")

        const button = screen.getByRole("button", { name: "Access" })
        expect(button).toHaveClass("portal-sidebar__link--active")
        expect(button).toHaveAttribute("aria-expanded", "true")
        expect(
            screen.getByRole("link", { name: "Audit History" }),
        ).toHaveAttribute("aria-current", "page")
        // Starting open for the active route must not steal focus.
        expect(button).not.toHaveFocus()
        expect(
            screen.getByRole("link", { name: "Audit History" }),
        ).not.toHaveFocus()
    })

    it("moves focus to the first child when the user opens it, and Escape returns it", async () => {
        renderSidebar("/app/campaign-b/home")
        const button = screen.getByRole("button", { name: "Access" })
        fireEvent.click(button)

        await waitFor(() => {
            expect(
                screen.getByRole("link", { name: "Access Management" }),
            ).toHaveFocus()
        })

        fireEvent.keyDown(
            screen.getByRole("link", { name: "Access Management" }),
            { key: "Escape" },
        )

        expect(button).toHaveAttribute("aria-expanded", "false")
        expect(button).toHaveFocus()
    })

    it("closes on an outside click and after choosing a child", () => {
        renderSidebar("/app/campaign-b/home")
        const button = screen.getByRole("button", { name: "Access" })

        fireEvent.click(button)
        fireEvent.pointerDown(screen.getByText("Outside link"))
        expect(button).toHaveAttribute("aria-expanded", "false")

        fireEvent.click(button)
        fireEvent.click(screen.getByRole("link", { name: "Invitations" }))
        expect(button).toHaveAttribute("aria-expanded", "false")
    })
})

describe("PortalSidebar session states", () => {
    it("renders a busy frame without campaign data while loading", () => {
        renderSidebar("/app/campaign-a/home", {
            status: "loading",
        })

        const list = within(nav()).getByRole("list")
        expect(list).toHaveAttribute("aria-busy", "true")
        expect(within(nav()).getByText("Loading navigation…")).toBeInTheDocument()
        expect(
            within(nav()).getByRole("link", { name: "View all campaigns" }),
        ).toHaveAttribute("href", "/campaigns")
        expect(
            within(nav()).getByRole("button", { name: "Collapse navigation" }),
        ).toBeInTheDocument()
        expect(within(nav()).queryByRole("link", { name: "Campaign world" })).toBeNull()
        expect(nav().innerHTML).not.toContain("Alpha Campaign")
        expect(nav().innerHTML).not.toContain("campaign-a")
    })

    it("keeps the frame with a recovery link when the session check fails", () => {
        renderSidebar("/campaigns", { status: "error", error: new Error("boom") })

        expect(within(nav()).getByRole("list")).not.toHaveAttribute("aria-busy")
        expect(
            within(nav()).getByRole("link", { name: "View all campaigns" }),
        ).toBeInTheDocument()
        expect(within(nav()).queryByRole("link", { name: "World" })).toBeNull()
    })

    it("renders nothing when unauthenticated", () => {
        renderSidebar("/campaigns", { status: "unauthenticated" })

        expect(
            screen.queryByRole("navigation", { name: "Main" }),
        ).not.toBeInTheDocument()
    })
})

describe("PortalSidebar collapse", () => {
    it("collapses into an icon rail that keeps accessible names", () => {
        renderSidebar("/app/campaign-a/home")
        const toggle = within(nav()).getByRole("button", {
            name: "Collapse navigation",
        })
        expect(toggle).toHaveAttribute("aria-expanded", "true")
        expect(toggle).toHaveAttribute("aria-controls", "main-navigation-list")

        fireEvent.click(toggle)

        expect(nav()).toHaveClass("portal-sidebar--collapsed")
        const expand = within(nav()).getByRole("button", {
            name: "Expand navigation",
        })
        expect(expand).toHaveAttribute("aria-expanded", "false")
        expect(within(nav()).getByRole("link", { name: "Knowledge" })).toBeVisible()
        expect(
            within(nav()).getByRole("link", { name: "Campaign Home" }),
        ).toHaveAttribute("href", "/app/campaign-a/home")
        expect(
            within(nav()).getByRole("link", { name: "All campaigns" }),
        ).toHaveAttribute("href", "/campaigns")
        // The disclosure needs visible labels, so the rail omits it.
        expect(
            within(nav()).queryByRole("button", { name: "Choose campaign" }),
        ).not.toBeInTheDocument()
    })

    it("persists the collapsed choice across mounts", () => {
        const { unmount } = renderSidebar("/app/campaign-a/home")
        fireEvent.click(
            within(nav()).getByRole("button", { name: "Collapse navigation" }),
        )
        expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)).toBe("true")
        unmount()

        renderSidebar("/app/campaign-b/home")
        expect(nav()).toHaveClass("portal-sidebar--collapsed")

        fireEvent.click(
            within(nav()).getByRole("button", { name: "Expand navigation" }),
        )
        expect(nav()).not.toHaveClass("portal-sidebar--collapsed")
        expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)).toBe("false")
    })

    it("tolerates unavailable storage", () => {
        vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
            throw new Error("blocked")
        })
        vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
            throw new Error("blocked")
        })

        renderSidebar("/app/campaign-a/home")
        expect(nav()).not.toHaveClass("portal-sidebar--collapsed")

        fireEvent.click(
            within(nav()).getByRole("button", { name: "Collapse navigation" }),
        )
        expect(nav()).toHaveClass("portal-sidebar--collapsed")
    })

    it("stores nothing but the collapsed flag", () => {
        renderSidebar("/app/campaign-a/home")
        fireEvent.click(
            within(nav()).getByRole("button", { name: "Collapse navigation" }),
        )

        const keys = Object.keys(window.localStorage)
        expect(keys).toEqual([SIDEBAR_COLLAPSED_STORAGE_KEY])
        expect(Object.keys(window.sessionStorage)).toEqual([])
    })
})

describe("PortalSidebar drawer", () => {
    function openDrawer() {
        const toggle = screen.getByRole("button", { name: "Header toggle" })
        fireEvent.click(toggle)
        return toggle
    }

    it("opens from the header toggle and moves focus into the sidebar", async () => {
        renderSidebar("/app/campaign-a/home")
        const toggle = openDrawer()

        expect(toggle).toHaveAttribute("aria-expanded", "true")
        expect(nav()).toHaveClass("portal-sidebar--mobile-open")
        await waitFor(() => {
            expect(
                within(nav()).getByRole("link", { name: "Campaign Home" }),
            ).toHaveFocus()
        })
    })

    it("closes on Escape and returns focus to the toggle", () => {
        renderSidebar("/app/campaign-a/home")
        const toggle = openDrawer()

        fireEvent.keyDown(document, { key: "Escape" })

        expect(nav()).not.toHaveClass("portal-sidebar--mobile-open")
        expect(toggle).toHaveAttribute("aria-expanded", "false")
        expect(toggle).toHaveFocus()
    })

    it("closes through the backdrop", () => {
        renderSidebar("/app/campaign-a/home")
        const toggle = openDrawer()

        fireEvent.click(screen.getByRole("button", { name: "Dismiss navigation" }))

        expect(nav()).not.toHaveClass("portal-sidebar--mobile-open")
        expect(toggle).toHaveFocus()
        expect(
            screen.queryByRole("button", { name: "Dismiss navigation" }),
        ).not.toBeInTheDocument()
    })

    it("closes after choosing a destination", () => {
        renderSidebar("/app/campaign-a/home")
        openDrawer()

        fireEvent.click(within(nav()).getByRole("link", { name: "Characters" }))

        expect(nav()).not.toHaveClass("portal-sidebar--mobile-open")
    })

    it("lets an open disclosure take Escape before the drawer", () => {
        renderSidebar("/app/campaign-a/home")
        openDrawer()
        const button = within(nav()).getByRole("button", { name: "Choose campaign" })
        fireEvent.click(button)

        fireEvent.keyDown(
            within(nav()).getByRole("link", { name: "Beta Campaign" }),
            { key: "Escape" },
        )

        expect(button).toHaveAttribute("aria-expanded", "false")
        expect(nav()).toHaveClass("portal-sidebar--mobile-open")
    })

    it("wraps Tab at both ends while open", async () => {
        renderSidebar("/app/campaign-a/home")
        openDrawer()
        const first = within(nav()).getByRole("link", { name: "Campaign Home" })
        const last = within(nav()).getByRole("button", {
            name: "Collapse navigation",
        })

        last.focus()
        fireEvent.keyDown(last, { key: "Tab" })
        expect(first).toHaveFocus()

        fireEvent.keyDown(first, { key: "Tab", shiftKey: true })
        expect(last).toHaveFocus()
    })
})

describe("PortalSidebar Worlds group (Phase 14)", () => {
    const world = { world_id: "world-a", timeline_id: "timeline-a" }
    const withWorld = (overrides: Partial<SessionBootstrap> = {}) =>
        authenticated(
            makeBootstrap({
                campaigns: [{ ...first, ...world }, second],
                ...overrides,
            }),
        )

    it("renders exactly one top-level Worlds group and no singular World item", () => {
        renderSidebar("/app/campaign-a/home")

        expect(within(nav()).getAllByRole("button", { name: "Worlds" })).toHaveLength(1)
        expect(within(nav()).queryByRole("link", { name: "Worlds" })).toBeNull()
        expect(within(nav()).queryByRole("link", { name: "World" })).toBeNull()
        expect(within(nav()).queryByRole("button", { name: "World" })).toBeNull()
    })

    it("communicates expanded state and keeps the collection reachable", () => {
        renderSidebar("/campaigns")
        const button = within(nav()).getByRole("button", { name: "Worlds" })
        expect(button).toHaveAttribute("aria-expanded", "false")

        fireEvent.click(button)

        expect(button).toHaveAttribute("aria-expanded", "true")
        expect(
            within(nav()).getByRole("link", { name: "All worlds" }),
        ).toHaveAttribute("href", "/worlds")
    })

    it("shows the group with the collection even for a user with no worlds or campaigns", () => {
        renderSidebar("/campaigns", authenticated(makeBootstrap({ campaigns: [] })))
        openWorlds()

        expect(within(nav()).getByRole("link", { name: "All worlds" })).toBeInTheDocument()
        expect(within(nav()).queryByRole("link", { name: "World overview" })).toBeNull()
        expect(within(nav()).queryByRole("link", { name: "Campaign world" })).toBeNull()
    })

    it("shows creation only when the server-computed capability allows it", () => {
        const { unmount } = renderSidebar(
            "/campaigns",
            authenticated(makeBootstrap({ global_capabilities: ["world.create"] })),
        )
        openWorlds()
        expect(
            within(nav()).getByRole("link", { name: "New world" }),
        ).toHaveAttribute("href", "/worlds/new")
        unmount()

        renderSidebar(
            "/campaigns",
            authenticated(makeBootstrap({ global_capabilities: [] })),
        )
        openWorlds()
        expect(within(nav()).queryByRole("link", { name: "New world" })).toBeNull()
    })

    it("does not infer creation when the bootstrap carries no global capabilities", () => {
        const bootstrap = makeBootstrap()
        delete bootstrap.global_capabilities
        renderSidebar("/campaigns", authenticated(bootstrap))
        openWorlds()
        expect(within(nav()).queryByRole("link", { name: "New world" })).toBeNull()
    })

    it("nests the active world's overview and timeline routes on a campaign route once the world read succeeds", async () => {
        renderSidebar("/app/campaign-a/home", withWorld())
        openWorlds()

        expect(
            await within(nav()).findByRole("link", { name: "World overview" }),
        ).toHaveAttribute("href", "/worlds/world-a")
        expect(within(nav()).getByRole("link", { name: "Timelines" })).toHaveAttribute(
            "href",
            "/worlds/world-a/timelines",
        )
        expect(
            within(nav()).getByRole("link", { name: "Timeline overview" }),
        ).toHaveAttribute("href", "/worlds/world-a/timelines/timeline-a")
    })

    it("starts open and marks only Timeline overview active on a timeline route", async () => {
        renderSidebar("/worlds/world-a/timelines/timeline-a", withWorld())

        expect(within(nav()).getByRole("button", { name: "Worlds" })).toHaveAttribute(
            "aria-expanded",
            "true",
        )
        const overview = await within(nav()).findByRole("link", {
            name: "Timeline overview",
        })
        expect(overview).toHaveAttribute("aria-current", "page")
        expect(within(nav()).getByRole("link", { name: "Timelines" })).not.toHaveAttribute(
            "aria-current",
        )
        expect(
            within(nav()).getByRole("link", { name: "World overview" }),
        ).not.toHaveAttribute("aria-current")
    })

    it("marks Timelines active on the collection route and disables Timeline overview", async () => {
        renderSidebar("/worlds/world-a/timelines", withWorld())

        expect(
            await within(nav()).findByRole("link", { name: "Timelines" }),
        ).toHaveAttribute("aria-current", "page")
        expect(disabledEntry("Timeline overview")).toHaveAccessibleDescription(
            "Select a timeline first",
        )
    })

    it("enables World overview for an authorized world that has no campaign of the caller", async () => {
        renderSidebar("/worlds/world-a", authenticated(makeBootstrap()))

        expect(
            await within(nav()).findByRole("link", { name: "World overview" }),
        ).toHaveAttribute("href", "/worlds/world-a")
    })

    it("marks the overview active on the world route", async () => {
        renderSidebar("/worlds/world-a", withWorld())

        expect(
            await within(nav()).findByRole("link", { name: "World overview" }),
        ).toHaveAttribute("aria-current", "page")
    })

    it("keeps Timeline overview disabled for a timeline the world does not authorize", async () => {
        renderSidebar("/worlds/world-a/timelines/ghost-timeline", withWorld())

        await within(nav()).findByRole("link", { name: "World overview" })
        expect(disabledEntry("Timeline overview")).toBeInTheDocument()
        expect(nav().innerHTML).not.toContain("ghost-timeline")
    })

    it("does not request a world on routes that name none", () => {
        renderSidebar("/campaigns", withWorld())
        renderSidebar("/worlds/new", withWorld())

        expect(server.calls).toEqual([])
    })

    it("never exposes navigation for an unknown or unauthorized world ID", () => {
        renderSidebar("/worlds/ghost-world/timelines/ghost-timeline", withWorld())

        expect(nav().innerHTML).not.toContain("ghost-world")
        expect(nav().innerHTML).not.toContain("ghost-timeline")
        expect(within(nav()).queryByRole("link", { name: "World overview" })).toBeNull()
        expect(within(nav()).queryByRole("link", { name: "Timelines" })).toBeNull()
    })

    it("keeps an accessible name and tooltip on the collapsed icon", () => {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, "true")
        renderSidebar("/campaigns")

        const button = within(nav()).getByRole("button", { name: "Worlds" })
        expect(button).toHaveAttribute("title", "Worlds")
    })

    it("closes with Escape and returns focus to the Worlds button", () => {
        renderSidebar("/campaigns")
        const button = within(nav()).getByRole("button", { name: "Worlds" })
        fireEvent.click(button)

        fireEvent.keyDown(within(nav()).getByRole("link", { name: "All worlds" }), {
            key: "Escape",
        })

        expect(button).toHaveAttribute("aria-expanded", "false")
        expect(button).toHaveFocus()
    })

    it("leaves the Campaign group unchanged", () => {
        renderSidebar("/app/campaign-a/home", withWorld())

        expect(
            within(nav()).getByRole("link", { name: "Campaign Home" }),
        ).toHaveAttribute("href", "/app/campaign-a/home")
        expect(
            within(nav()).getByRole("button", { name: "Choose campaign" }),
        ).toBeInTheDocument()
    })
})

function disabledEntry(label: string): HTMLElement {
    return within(nav())
        .getByText(label, {
            selector: "[aria-disabled='true'] .portal-sidebar__label",
        })
        .closest("[aria-disabled='true']") as HTMLElement
}

// Every entry label in document order, enabled or disabled, hidden submenus
// included: the structure a route change must not alter.
function slotOrder(): string[] {
    return Array.from(
        nav().querySelectorAll(".portal-sidebar__label"),
        (element) => element.textContent ?? "",
    )
}

describe("PortalSidebar stable navigation structure (Phase 14)", () => {
    const world = { world_id: "world-a", timeline_id: "timeline-a" }
    const withWorld = () =>
        authenticated(
            makeBootstrap({ campaigns: [{ ...first, ...world }, second] }),
        )

    const routes = [
        "/worlds",
        "/worlds/world-a",
        "/worlds/world-a/timelines/timeline-a",
        "/campaigns",
        "/app/campaign-a/home",
        "/app/campaign-a/quests",
        "/worlds/ghost-world",
        "/app/ghost-campaign/home",
    ]

    function orderFor(route: string): string[] {
        const { unmount } = renderSidebar(route, withWorld())
        const order = slotOrder()
        unmount()
        return order
    }

    it("keeps the same ordered slots across every context transition", () => {
        const baseline = orderFor(routes[0]!)
        expect(baseline).toContain("Timelines")
        expect(baseline).toContain("Characters")
        for (const route of routes.slice(1)) {
            expect(orderFor(route), route).toEqual(baseline)
        }
    })

    it("keeps the same ordered slots when collapsed", () => {
        const expanded = orderFor("/worlds")
        window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, "true")
        // Collapsed swaps the campaign disclosure for plain links, so compare
        // only collapsed against collapsed.
        const baseline = orderFor("/worlds")
        expect(baseline).toContain("Campaign Home")
        for (const route of routes.slice(1)) {
            expect(orderFor(route), route).toEqual(baseline)
        }
        expect(expanded).toContain("Timelines")
    })

    it("keeps the same ordered slots in the open drawer", () => {
        const baseline = orderFor("/worlds")
        const { unmount } = renderSidebar("/app/campaign-a/home", withWorld())
        fireEvent.click(screen.getByRole("button", { name: "Header toggle" }))
        expect(nav()).toHaveClass("portal-sidebar--mobile-open")
        expect(slotOrder()).toEqual(baseline)
        unmount()
    })

    it("shows World overview and Timelines as disabled on All worlds, leaking nothing", () => {
        renderSidebar("/worlds", withWorld())

        for (const label of ["World overview", "Timelines", "Timeline overview"]) {
            const entry = disabledEntry(label)
            expect(entry.tagName).not.toBe("A")
            expect(entry).toHaveAttribute("aria-disabled", "true")
            expect(entry).not.toHaveAttribute("aria-current")
            expect(entry).not.toHaveAttribute("href")
            expect(entry).toHaveAccessibleDescription(
                label === "Timeline overview"
                    ? "Select a timeline first"
                    : "Select a world first",
            )
            expect(within(nav()).queryByRole("link", { name: label })).toBeNull()
        }
        expect(within(nav()).getByRole("link", { name: "All worlds" })).toBeEnabled()
        for (const secret of ["world-a", "timeline-a", "Mundivita", "Primary Timeline"]) {
            expect(nav().innerHTML).not.toContain(secret)
        }
    })

    it("enables World overview and Timelines for an authorized world", async () => {
        renderSidebar("/worlds/world-a", withWorld())

        expect(
            await within(nav()).findByRole("link", { name: "World overview" }),
        ).toHaveAttribute("href", "/worlds/world-a")
        expect(
            within(nav()).getByRole("link", { name: "Timelines" }),
        ).toHaveAttribute("href", "/worlds/world-a/timelines")
    })

    it("keeps New world disabled without the server capability, never overriding it", () => {
        renderSidebar(
            "/worlds/world-a",
            authenticated(
                makeBootstrap({
                    campaigns: [{ ...first, ...world }, second],
                    global_capabilities: [],
                }),
            ),
        )

        expect(within(nav()).queryByRole("link", { name: "New world" })).toBeNull()
        expect(disabledEntry("New world")).toHaveAttribute("aria-disabled", "true")
    })

    it("shows campaign destinations as disabled without an active campaign", () => {
        renderSidebar("/campaigns", withWorld())

        for (const label of [
            "Campaign Home",
            "Characters",
            "Quests",
            "Sessions",
            "Knowledge",
            "Ask",
            "Access",
            "Campaign world",
        ]) {
            if (label === "Campaign world") {
                openWorlds()
            }
            const entry = disabledEntry(label)
            expect(entry, label).toHaveAttribute("aria-disabled", "true")
            expect(entry, label).not.toHaveAttribute("aria-current")
            expect(entry, label).toHaveAccessibleDescription("Select a campaign first")
            expect(within(nav()).queryByRole("link", { name: label }), label).toBeNull()
        }
        expect(nav().querySelector('a[href*="/quests"]')).toBeNull()
    })

    it("enables campaign destinations once an authorized campaign resolves", () => {
        renderSidebar("/app/campaign-a/home", withWorld())

        for (const [label, path] of [
            ["Characters", "characters"],
            ["Quests", "quests"],
            ["Sessions", "sessions"],
            ["Knowledge", "knowledge"],
        ]) {
            expect(within(nav()).getByRole("link", { name: label })).toHaveAttribute(
                "href",
                `/app/campaign-a/${path}`,
            )
        }
    })

    it("does not navigate when a disabled entry is activated", () => {
        renderSidebar("/campaigns", withWorld())

        fireEvent.click(disabledEntry("Characters"))
        fireEvent.click(disabledEntry("Campaign Home"))

        expect(screen.getByTestId("location")).toHaveTextContent("/campaigns")
    })

    it("does not enable or label contextual navigation from unknown route IDs", () => {
        renderSidebar("/worlds/ghost-world/timelines/ghost-timeline", withWorld())
        openWorlds()
        expect(disabledEntry("World overview")).toBeInTheDocument()
        expect(disabledEntry("Timelines")).toBeInTheDocument()
        expect(disabledEntry("Characters")).toBeInTheDocument()
        expect(nav().innerHTML).not.toContain("ghost")
    })

    it("does not enable campaign navigation from an unauthorized campaign route", () => {
        renderSidebar("/app/ghost-campaign/quests", withWorld())

        expect(disabledEntry("Quests")).toBeInTheDocument()
        expect(disabledEntry("Campaign Home")).toBeInTheDocument()
        expect(nav().innerHTML).not.toContain("ghost")
    })

    it("keeps accessible names and tooltips on collapsed disabled entries", () => {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, "true")
        renderSidebar("/campaigns", withWorld())

        const entry = disabledEntry("Characters")
        expect(entry).toHaveAttribute("title", "Characters: Select a campaign first")
        expect(entry).toHaveTextContent("Characters")
        expect(entry).toHaveAccessibleDescription("Select a campaign first")
    })

    it("keeps feature-disabled Ask on its own server-provided reason", () => {
        renderSidebar("/app/campaign-a/home", withWorld())

        expect(disabledEntry("Ask")).toHaveAttribute(
            "title",
            "Unavailable until Phase 12 is verified",
        )
    })
})

describe("PortalSidebar World authoring navigation on a campaign route", () => {
    const worldIds = ["world-a", "timeline-a", "World A", "Timeline A"]
    const authoringLabels = ["World overview", "Timelines", "Timeline overview"]
    const campaignState = () =>
        authenticated(
            makeBootstrap({
                campaigns: [
                    {
                        ...first,
                        world_id: "world-a",
                        world_name: "World A",
                        timeline_id: "timeline-a",
                        timeline_name: "Timeline A",
                    },
                    second,
                ],
            }),
        )

    function expectDisabledAuthoring() {
        for (const label of authoringLabels) {
            const entry = disabledEntry(label)
            expect(entry.tagName).not.toBe("A")
            expect(entry).toHaveAttribute("aria-disabled", "true")
            expect(entry).not.toHaveAttribute("href")
            expect(entry).not.toHaveAttribute("aria-current")
            expect(entry).not.toHaveClass("portal-sidebar__sublink--active")
            expect(within(nav()).queryByRole("link", { name: label })).toBeNull()
        }
        for (const id of worldIds) {
            expect(nav().innerHTML).not.toContain(id)
        }
    }

    it.each([403, 404])(
        "keeps World overview, Timelines and Timeline overview disabled when the world read returns %i",
        async (status) => {
            server.on("GET", "/worlds/world-a", { status, body: { detail: "no" } })
            renderSidebar("/app/campaign-a/home", campaignState())
            openWorlds()

            await waitFor(() =>
                expect(server.callsTo("GET", "/worlds/world-a")).not.toHaveLength(0),
            )
            await waitFor(() => expectDisabledAuthoring())
            // Ordinary campaign navigation and Campaign world still work.
            expect(
                within(nav()).getByRole("link", { name: "Campaign world" }),
            ).toHaveAttribute("href", "/app/campaign-a/world")
            expect(within(nav()).getByRole("link", { name: "Characters" })).toHaveAttribute(
                "href",
                "/app/campaign-a/characters",
            )
        },
    )

    it("stays disabled while the world read is loading and when it errors", async () => {
        server.on("GET", "/worlds/world-a", () => new Promise(() => {}))
        const { unmount } = renderSidebar("/app/campaign-a/home", campaignState())
        openWorlds()
        expectDisabledAuthoring()
        unmount()

        server.on("GET", "/worlds/world-a", { status: 500, body: {} })
        renderSidebar("/app/campaign-a/home", campaignState())
        openWorlds()
        await waitFor(() =>
            expect(server.callsTo("GET", "/worlds/world-a")).toHaveLength(2),
        )
        expectDisabledAuthoring()
    })

    const worldsGroupSlots = () =>
        slotOrder().filter((label) =>
            [
                "All worlds",
                "New world",
                "World overview",
                "Timelines",
                "Timeline overview",
                "Campaign world",
            ].includes(label),
        )

    it("keeps the same Worlds slots in the same order when collapsed and in the open drawer", async () => {
        server.on("GET", "/worlds/world-a", { status: 404 })
        const expanded = renderSidebar("/app/campaign-a/home", campaignState())
        openWorlds()
        await waitFor(() =>
            expect(server.callsTo("GET", "/worlds/world-a")).not.toHaveLength(0),
        )
        const baseline = worldsGroupSlots()
        expanded.unmount()

        window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, "true")
        const collapsed = renderSidebar("/app/campaign-a/home", campaignState())
        openWorlds()
        await waitFor(() => expectDisabledAuthoring())
        expect(worldsGroupSlots()).toEqual(baseline)
        collapsed.unmount()

        window.localStorage.clear()
        renderSidebar("/app/campaign-a/home", campaignState())
        fireEvent.click(screen.getByRole("button", { name: "Header toggle" }))
        openWorlds()
        await waitFor(() => expectDisabledAuthoring())
        expect(nav()).toHaveClass("portal-sidebar--mobile-open")
        expect(worldsGroupSlots()).toEqual(baseline)
    })

    it("enables World overview and Timelines, and Timeline overview only for a listed timeline", async () => {
        renderSidebar("/app/campaign-a/home", campaignState())
        openWorlds()

        expect(
            await within(nav()).findByRole("link", { name: "World overview" }),
        ).toHaveAttribute("href", "/worlds/world-a")
        expect(within(nav()).getByRole("link", { name: "Timelines" })).toHaveAttribute(
            "href",
            "/worlds/world-a/timelines",
        )
        expect(
            within(nav()).getByRole("link", { name: "Timeline overview" }),
        ).toHaveAttribute("href", "/worlds/world-a/timelines/timeline-a")
        expect(within(nav()).getByRole("link", { name: "Campaign world" })).toHaveAttribute(
            "href",
            "/app/campaign-a/world",
        )
    })

    it("keeps Timeline overview disabled when the world response does not list the campaign's timeline", async () => {
        server.on("GET", "/worlds/world-a", {
            body: {
                ...worldDetail,
                timelines: [{ timeline_id: "timeline-b", name: "Timeline B" }],
            },
        })
        renderSidebar("/app/campaign-a/home", campaignState())
        openWorlds()

        await within(nav()).findByRole("link", { name: "World overview" })
        expect(within(nav()).getByRole("link", { name: "Timelines" })).toBeInTheDocument()
        expect(disabledEntry("Timeline overview")).toHaveAttribute("aria-disabled", "true")
        expect(nav().innerHTML).not.toContain("timeline-a")
    })
})
