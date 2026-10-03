import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, useLocation } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import App from "./App"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import { sessionBootstrapFixture } from "./fixtures/sessionBootstrap"
import { ThemeProvider } from "./themes/ThemeProvider"
import type { CampaignContext, SessionBootstrap } from "./types/bootstrap"

// Real session provider, real routes, stubbed network: proves a saved
// startup preference reaches the *shared* session bootstrap, not just the
// form's own state.

vi.mock("./hooks/useInvitationOnboardingStatus", () => ({
    useInvitationOnboardingStatus: () => ({
        state: { status: "unavailable" },
        retry: vi.fn(),
    }),
}))
vi.mock("./pages/CampaignHomePage", () => ({
    CampaignHomePage: () => <h1>Campaign Home stub</h1>,
}))
// Campaign pages make other requests; only the session and preference
// endpoints matter here.
vi.mock("./hooks/useRecordLastVisitedCampaign", () => ({
    useRecordLastVisitedCampaign: () => undefined,
}))

const base = sessionBootstrapFixture.campaigns[0]!
const campaign = (id: string, name: string): CampaignContext => ({
    ...base,
    campaign_id: id,
    campaign_name: name,
    capabilities: [],
})
const alpha = campaign("alpha", "Alpha")
const beta = campaign("beta", "Beta")
const gamma = campaign("gamma", "Gamma")

class FakeServer {
    campaigns = [alpha, beta, gamma]
    preferred: string | null = null
    lastVisited: string | null = "gamma"
    sessionStatus = 200
    putStatus = 204
    sessionGets = 0

    bootstrap(): SessionBootstrap {
        const ids = this.campaigns.map((c) => c.campaign_id)
        const preferred = this.preferred !== null && ids.includes(this.preferred) ? this.preferred : null
        const last = this.lastVisited !== null && ids.includes(this.lastVisited) ? this.lastVisited : null
        return {
            ...sessionBootstrapFixture,
            campaigns: this.campaigns,
            startup_campaign_id: preferred ?? last,
            campaign_preferences: {
                startup_mode: preferred === null ? "resume_last_visited" : "preferred_campaign",
                preferred_campaign_id: preferred,
                last_visited_campaign_id: last,
            },
        }
    }

    handle = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const path = String(input)
        const method = init?.method ?? "GET"
        if (method === "GET" && path === "/auth/session") {
            this.sessionGets += 1
            if (this.sessionStatus !== 200) {
                return new Response(null, { status: this.sessionStatus })
            }
            return new Response(JSON.stringify(this.bootstrap()), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            })
        }
        if (method === "PUT" && path === "/api/auth/preferences/campaign-startup") {
            if (this.putStatus === 204) {
                this.preferred = (JSON.parse(String(init?.body)) as { preferred_campaign_id: string | null })
                    .preferred_campaign_id
            }
            return new Response(null, { status: this.putStatus })
        }
        return new Response(null, { status: 404 })
    }
}

let server: FakeServer

function LocationProbe() {
    return <p data-testid="location">{useLocation().pathname}</p>
}

function renderAt(path: string) {
    return render(
        <ThemeProvider>
            <MemoryRouter initialEntries={[path]}>
                <RouteSessionProvider>
                    <App />
                    <LocationProbe />
                </RouteSessionProvider>
            </MemoryRouter>
        </ThemeProvider>,
    )
}

const location = () => screen.getByTestId("location")
const fixedRadio = () => screen.getByRole("radio", { name: "Always open this campaign" })
const resumeRadio = () => screen.getByRole("radio", { name: "Resume my last visited campaign" })
const select = () => screen.getByRole("combobox", { name: "Campaign" })
const save = () => screen.getByRole("button", { name: "Save startup preference" })

async function openSettings() {
    renderAt("/settings")
    await screen.findByRole("heading", { level: 1, name: "Settings" })
}

async function saveFixed(name: string) {
    fireEvent.click(fixedRadio())
    fireEvent.change(select(), { target: { value: name } })
    fireEvent.click(save())
    await waitFor(() => {
        expect(screen.getByRole("status")).toHaveTextContent("Startup preference saved.")
    })
}

beforeEach(() => {
    server = new FakeServer()
    vi.stubGlobal("fetch", vi.fn(server.handle))
})

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("saved startup preference reaches the shared session", () => {
    it("opens the saved fixed campaign from /home in the same session", async () => {
        await openSettings()
        const getsBefore = server.sessionGets

        await saveFixed("beta")

        // Success is only shown after the authoritative re-fetch.
        expect(server.sessionGets).toBe(getsBefore + 1)
        fireEvent.click(screen.getByRole("link", { name: "D&D AI Portal" }))

        await waitFor(() => {
            expect(location()).toHaveTextContent("/app/beta/home")
        })
    })

    it("uses the resume/last-visited behavior from /home after clearing the fixed campaign", async () => {
        server.preferred = "beta"
        await openSettings()
        expect(fixedRadio()).toBeChecked()

        fireEvent.click(resumeRadio())
        fireEvent.click(save())
        await waitFor(() => {
            expect(screen.getByRole("status")).toHaveTextContent("Startup preference saved.")
        })
        fireEvent.click(screen.getByRole("link", { name: "D&D AI Portal" }))

        await waitFor(() => {
            expect(location()).toHaveTextContent("/app/gamma/home")
        })
    })

    it("shows the saved authoritative value when Settings is remounted in the same session", async () => {
        await openSettings()
        await saveFixed("alpha")
        const getsAfterSave = server.sessionGets

        fireEvent.click(screen.getByRole("button", { name: "Choose campaign" }))
        fireEvent.click(screen.getByRole("link", { name: "View all campaigns" }))
        await screen.findByRole("heading", { level: 1, name: "Campaigns" })
        fireEvent.click(screen.getByRole("button", { name: /account menu/i }))
        fireEvent.click(screen.getByRole("link", { name: "Settings" }))
        await screen.findByRole("heading", { level: 1, name: "Settings" })

        expect(fixedRadio()).toBeChecked()
        expect(select()).toHaveValue("alpha")
        // No extra session load was needed: the shared state already held it.
        expect(server.sessionGets).toBe(getsAfterSave)
    })

    it("keeps the success indication visible after the refresh (no page unmount)", async () => {
        await openSettings()
        await saveFixed("beta")

        expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument()
        expect(save()).toBeDisabled()
        expect(fixedRadio()).toBeChecked()
        expect(select()).toHaveValue("beta")
    })

    it("respects a campaign list that changed around the save", async () => {
        await openSettings()
        // Access to Gamma is revoked after Settings loaded, then Alpha is saved.
        server.campaigns = [alpha, beta]
        server.lastVisited = "gamma"

        await saveFixed("alpha")

        const options = Array.from(select().querySelectorAll("option")).map((o) => o.textContent)
        expect(options).toEqual(["Choose a campaign", "Alpha", "Beta"])
        expect(select()).toHaveValue("alpha")
    })

    it("applies nothing and stays recoverable when the refresh after a save fails", async () => {
        await openSettings()
        fireEvent.click(fixedRadio())
        fireEvent.change(select(), { target: { value: "beta" } })
        server.sessionStatus = 500
        fireEvent.click(save())

        expect(await screen.findByRole("alert")).toHaveTextContent("could not be confirmed")
        expect(screen.getByRole("status")).toBeEmptyDOMElement()
        // The page stays mounted with the draft, ready to retry.
        expect(select()).toHaveValue("beta")

        server.sessionStatus = 200
        fireEvent.click(save())
        await waitFor(() => {
            expect(screen.getByRole("status")).toHaveTextContent("Startup preference saved.")
        })
    })

    it("sends an expired session to sign-in after a save whose refresh is unauthenticated", async () => {
        await openSettings()
        fireEvent.click(fixedRadio())
        fireEvent.change(select(), { target: { value: "beta" } })
        server.sessionStatus = 401
        fireEvent.click(save())

        await waitFor(() => {
            expect(location()).toHaveTextContent("/login")
        })
    })

    it("does not refresh or change shared state when the save is rejected", async () => {
        await openSettings()
        const getsBefore = server.sessionGets
        server.putStatus = 404
        fireEvent.click(fixedRadio())
        fireEvent.change(select(), { target: { value: "beta" } })
        fireEvent.click(save())

        expect(await screen.findByRole("alert")).toHaveTextContent("no longer available")
        expect(server.sessionGets).toBe(getsBefore)

        fireEvent.click(screen.getByRole("link", { name: "D&D AI Portal" }))
        await waitFor(() => {
            expect(location()).toHaveTextContent("/app/gamma/home")
        })
    })

    it.each([401, 403])("shows the session-check path for a %i save and applies nothing", async (status) => {
        await openSettings()
        server.putStatus = status
        fireEvent.click(fixedRadio())
        fireEvent.change(select(), { target: { value: "beta" } })
        fireEvent.click(save())

        expect(await screen.findByRole("alert")).toHaveTextContent("nothing was saved")
        expect(server.preferred).toBeNull()
        expect(screen.getByRole("button", { name: "Check my session" })).toBeInTheDocument()
    })
})
