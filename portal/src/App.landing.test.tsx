import { fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter, useLocation, useNavigate } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import App from "./App"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import { sessionBootstrapFixture } from "./fixtures/sessionBootstrap"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import { ThemeProvider } from "./themes/ThemeProvider"
import type { CampaignContext, SessionBootstrap } from "./types/bootstrap"

vi.mock("./hooks/useSessionBootstrap", () => ({
    useSessionBootstrap: vi.fn(),
}))
vi.mock("./hooks/useInvitationOnboardingStatus", () => ({
    useInvitationOnboardingStatus: () => ({
        state: { status: "unavailable" },
        retry: vi.fn(),
    }),
}))
// The campaign pages are not under test: a stub keeps this focused on where
// the landing resolver sends the user.
vi.mock("./pages/CampaignHomePage", () => ({
    CampaignHomePage: () => <h1>Campaign Home stub</h1>,
}))

const useSessionBootstrapMock = vi.mocked(useSessionBootstrap)

const base = sessionBootstrapFixture.campaigns[0]!
const alpha: CampaignContext = { ...base, campaign_id: "alpha", campaign_name: "Alpha", capabilities: [] }
const beta: CampaignContext = { ...base, campaign_id: "beta", campaign_name: "Beta", capabilities: [] }
const gamma: CampaignContext = { ...base, campaign_id: "gamma", campaign_name: "Gamma", capabilities: [] }

function bootstrapWith(overrides: Partial<SessionBootstrap>): SessionBootstrap {
    return {
        ...sessionBootstrapFixture,
        startup_campaign_id: null,
        campaign_preferences: {
            startup_mode: "resume_last_visited",
            preferred_campaign_id: null,
            last_visited_campaign_id: null,
        },
        ...overrides,
    }
}

function LocationProbe() {
    const location = useLocation()
    const navigate = useNavigate()
    return (
        <>
            <p data-testid="location">{location.pathname}</p>
            <button type="button" onClick={() => navigate(-1)}>
                Browser back
            </button>
        </>
    )
}

function renderAt(entries: string[], bootstrap: SessionBootstrap) {
    useSessionBootstrapMock.mockReturnValue({
        state: { status: "authenticated", bootstrap },
        reload: vi.fn(),
    })
    return render(
        <ThemeProvider>
            <MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
                <RouteSessionProvider>
                    <App />
                    <LocationProbe />
                </RouteSessionProvider>
            </MemoryRouter>
        </ThemeProvider>,
    )
}

const location = () => screen.getByTestId("location")

beforeEach(() => {
    useSessionBootstrapMock.mockReset()
})

describe("/home landing resolver", () => {
    it("lands on the campaign list with no campaigns", () => {
        renderAt(["/home"], bootstrapWith({ campaigns: [] }))

        expect(location()).toHaveTextContent("/campaigns")
        expect(screen.getByRole("heading", { level: 1, name: "Campaigns" })).toBeInTheDocument()
        expect(
            screen.getByRole("link", { name: "Accept a campaign invitation" }),
        ).toBeInTheDocument()
    })

    it("opens the only campaign", () => {
        renderAt(
            ["/home"],
            bootstrapWith({ campaigns: [alpha], startup_campaign_id: "alpha" }),
        )

        expect(location()).toHaveTextContent("/app/alpha/home")
        expect(screen.getByRole("heading", { name: "Campaign Home stub" })).toBeInTheDocument()
    })

    it("opens a valid fixed preferred campaign", () => {
        renderAt(
            ["/home"],
            bootstrapWith({
                campaigns: [alpha, beta, gamma],
                startup_campaign_id: "beta",
                campaign_preferences: {
                    startup_mode: "preferred_campaign",
                    preferred_campaign_id: "beta",
                    last_visited_campaign_id: "gamma",
                },
            }),
        )

        expect(location()).toHaveTextContent("/app/beta/home")
    })

    it("resumes the last visited campaign", () => {
        renderAt(
            ["/home"],
            bootstrapWith({
                campaigns: [alpha, beta, gamma],
                startup_campaign_id: "gamma",
                campaign_preferences: {
                    startup_mode: "resume_last_visited",
                    preferred_campaign_id: null,
                    last_visited_campaign_id: "gamma",
                },
            }),
        )

        expect(location()).toHaveTextContent("/app/gamma/home")
    })

    it("lands on the campaign list, not the first campaign, without a valid preference", () => {
        renderAt(["/home"], bootstrapWith({ campaigns: [alpha, beta, gamma] }))

        expect(location()).toHaveTextContent("/campaigns")
        expect(screen.getByRole("heading", { level: 1, name: "Campaigns" })).toBeInTheDocument()
    })

    it("ignores a startup campaign that is not in the authorized list", () => {
        const { container } = renderAt(
            ["/home"],
            bootstrapWith({
                campaigns: [alpha, beta],
                startup_campaign_id: "ghost",
                campaign_preferences: {
                    startup_mode: "preferred_campaign",
                    preferred_campaign_id: "ghost",
                    last_visited_campaign_id: "ghost",
                },
            }),
        )

        expect(location()).toHaveTextContent("/campaigns")
        expect(container.innerHTML).not.toContain("ghost")
    })

    it("replaces /home in history so Back never returns to it, and does not loop", () => {
        renderAt(
            ["/settings", "/home"],
            bootstrapWith({ campaigns: [alpha], startup_campaign_id: "alpha" }),
        )
        expect(location()).toHaveTextContent("/app/alpha/home")

        fireEvent.click(screen.getByRole("button", { name: "Browser back" }))

        expect(location()).toHaveTextContent("/settings")
        expect(location()).not.toHaveTextContent("/home")
    })

    it("keeps /home/extra a not-found page rather than a resolver alias", () => {
        renderAt(["/home/extra"], bootstrapWith({ campaigns: [alpha], startup_campaign_id: "alpha" }))

        expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument()
        expect(location()).toHaveTextContent("/home/extra")
    })
})

describe("persistent sidebar through the real route tree", () => {
    const admin = bootstrapWith({
        campaigns: [alpha, beta],
        startup_campaign_id: "alpha",
        is_platform_administrator: true,
    })

    it.each([
        ["Campaign Home", "/app/alpha/home"],
        ["/campaigns", "/campaigns"],
        ["/settings", "/settings"],
        ["/account", "/account"],
        ["/platform/accounts", "/platform/accounts"],
    ])("is present on %s", (_label, path) => {
        renderAt([path], admin)

        expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument()
    })

    it.each(["/login", "/activate", "/reset-password", "/campaign-invitations/accept", "/nope"])(
        "is absent from the public route %s",
        (path) => {
            useSessionBootstrapMock.mockReturnValue({
                state: { status: "unauthenticated" },
                reload: vi.fn(),
            })
            render(
                <ThemeProvider>
                    <MemoryRouter initialEntries={[path]}>
                        <RouteSessionProvider>
                            <App />
                        </RouteSessionProvider>
                    </MemoryRouter>
                </ThemeProvider>,
            )

            expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument()
        },
    )

    it("is removed when the session is unauthenticated on an authenticated route", () => {
        useSessionBootstrapMock.mockReturnValue({
            state: { status: "unauthenticated" },
            reload: vi.fn(),
        })
        render(
            <ThemeProvider>
                <MemoryRouter initialEntries={["/settings"]}>
                    <RouteSessionProvider>
                        <App />
                        <LocationProbe />
                    </RouteSessionProvider>
                </MemoryRouter>
            </ThemeProvider>,
        )

        expect(location()).toHaveTextContent("/login")
        expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument()
    })

    it("keeps campaign links on the resolved campaign across global routes", () => {
        renderAt(["/settings"], admin)

        expect(screen.getByRole("link", { name: "Quests" })).toHaveAttribute(
            "href",
            "/app/alpha/quests",
        )
    })

    it("hides Access without access.manage and Platform Accounts without admin", () => {
        renderAt(["/app/alpha/home"], bootstrapWith({ campaigns: [alpha], startup_campaign_id: "alpha" }))

        expect(screen.queryByRole("button", { name: "Access" })).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: /account menu/i }))
        expect(screen.queryByRole("link", { name: "Platform Accounts" })).not.toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument()
    })
})
