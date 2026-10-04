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
                    <Routes>
                        <Route path="*" element={<Harness />} />
                    </Routes>
                    <LocationProbe />
                </MemoryRouter>
            </CharacterPerspectiveContext.Provider>
        </SessionContext.Provider>,
    )
}

function authenticated(bootstrap: SessionBootstrap): SessionBootstrapState {
    return { status: "authenticated", bootstrap }
}

function nav() {
    return screen.getByRole("navigation", { name: "Main" })
}

beforeEach(() => {
    selectCharacter.mockReset()
    window.localStorage.clear()
})

afterEach(() => {
    vi.restoreAllMocks()
})

describe("PortalSidebar destinations", () => {
    it("targets the route campaign for every campaign-specific link", () => {
        renderSidebar("/app/campaign-a/home")

        const expected: Array<[string, string]> = [
            ["Campaign Home", "/app/campaign-a/home"],
            ["World", "/app/campaign-a/world"],
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

    it("marks the active route with aria-current", () => {
        renderSidebar("/app/campaign-a/quests")

        expect(within(nav()).getByRole("link", { name: "Quests" })).toHaveAttribute(
            "aria-current",
            "page",
        )
        expect(
            within(nav()).getByRole("link", { name: "World" }),
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

        expect(within(nav()).getByRole("link", { name: "World" })).toHaveAttribute(
            "href",
            "/app/campaign-a/world",
        )
    })

    it("never builds a link from an unauthorized route campaign", () => {
        renderSidebar(
            "/app/ghost-campaign/home",
            authenticated(makeBootstrap({ startup_campaign_id: "campaign-a" })),
        )

        expect(nav().innerHTML).not.toContain("ghost-campaign")
        expect(within(nav()).getByRole("link", { name: "World" })).toHaveAttribute(
            "href",
            "/app/campaign-a/world",
        )
    })

    it("omits campaign-specific links and explains why with no resolvable campaign", () => {
        renderSidebar("/campaigns")

        expect(
            within(nav()).queryByRole("link", { name: "World" }),
        ).not.toBeInTheDocument()
        expect(within(nav()).queryByText("Ask")).not.toBeInTheDocument()
        expect(
            within(nav()).getByText("Choose a campaign to see its pages."),
        ).toBeInTheDocument()
    })

    it("handles an account with no campaigns", () => {
        renderSidebar(
            "/campaigns",
            authenticated(makeBootstrap({ campaigns: [] })),
        )

        const group = within(nav()).getByRole("button", {
            name: "Choose a campaign",
        })
        expect(group).toBeInTheDocument()
        expect(
            within(nav()).getByRole("link", { name: "View all campaigns" }),
        ).toHaveAttribute("href", "/campaigns")
        expect(
            within(nav()).getByText("Choose a campaign to see its pages."),
        ).toBeInTheDocument()
    })
})

describe("PortalSidebar campaign submenu", () => {
    it("lists only bootstrap-authorized campaigns plus View all campaigns", () => {
        renderSidebar("/campaigns")

        const list = document.getElementById(
            within(nav())
                .getByRole("button", { name: "Choose a campaign" })
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
            within(nav()).getByRole("button", { name: "Choose a campaign" }),
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
        expect(within(nav()).queryByRole("link", { name: "World" })).toBeNull()
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

        fireEvent.click(within(nav()).getByRole("link", { name: "World" }))

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

describe("PortalSidebar Worlds link (Phase 14)", () => {
    it("shows Worlds only when the server-computed global capability includes world.create", () => {
        renderSidebar("/app/campaign-a/home", {
            status: "authenticated",
            bootstrap: makeBootstrap({ global_capabilities: ["world.create"] }),
        })
        expect(within(nav()).getByRole("link", { name: "Worlds" })).toHaveAttribute(
            "href",
            "/worlds",
        )
    })

    it("does not show Worlds without the capability, and never infers it", () => {
        renderSidebar("/app/campaign-a/home", {
            status: "authenticated",
            bootstrap: makeBootstrap({ global_capabilities: [] }),
        })
        expect(within(nav()).queryByRole("link", { name: "Worlds" })).not.toBeInTheDocument()
    })

    it("does not show Worlds when the bootstrap carries no global capabilities", () => {
        const bootstrap = makeBootstrap()
        delete bootstrap.global_capabilities
        renderSidebar("/home", { status: "authenticated", bootstrap })
        expect(within(nav()).queryByRole("link", { name: "Worlds" })).not.toBeInTheDocument()
    })
})
