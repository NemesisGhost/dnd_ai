import { act, fireEvent, render, screen, within } from "@testing-library/react"
import { useState } from "react"
import { MemoryRouter } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { ThemeProvider } from "../themes/ThemeProvider"
import { SettingsPage } from "./SettingsPage"
import type { SessionBootstrap } from "../types/bootstrap"

const { setPreferenceMock } = vi.hoisted(() => ({ setPreferenceMock: vi.fn() }))

vi.mock("../api/userPreferences", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/userPreferences")>()
    return { ...actual, setCampaignStartupPreference: setPreferenceMock }
})

function renderPage() {
    return render(
        <SessionContext.Provider
            value={{
                state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
                reload: vi.fn(), refresh: vi.fn(),
            }}
        >
            <ThemeProvider>
                <MemoryRouter>
                    <SettingsPage bootstrap={sessionBootstrapFixture} reload={vi.fn()} />
                </MemoryRouter>
            </ThemeProvider>
        </SessionContext.Provider>,
    )
}

beforeEach(() => {
    setPreferenceMock.mockReset()
    window.localStorage.clear()
    delete document.documentElement.dataset.theme
})

describe("SettingsPage", () => {
    it("has one h1 and Appearance and Campaign startup sections", () => {
        renderPage()

        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        expect(
            screen.getByRole("heading", { level: 1, name: "Settings" }),
        ).toBeInTheDocument()
        expect(screen.getByRole("region", { name: "Appearance" })).toBeInTheDocument()
        expect(screen.getByRole("region", { name: "Campaign startup" })).toBeInTheDocument()
        expect(screen.getAllByRole("main")).toHaveLength(1)
    })

    it("hosts the theme selector, which applies and persists the theme locally", () => {
        renderPage()
        const appearance = screen.getByRole("region", { name: "Appearance" })

        const select = within(appearance).getByRole("combobox", { name: "Appearance" })
        expect(select).toHaveValue("system")

        fireEvent.change(select, { target: { value: "royal-plum" } })

        expect(document.documentElement.dataset.theme).toBe("royal-plum")
        expect(window.localStorage.getItem("dnd-ai-theme")).toBe("royal-plum")
    })

    it("stores no secret or session data with the theme preference", () => {
        renderPage()
        fireEvent.change(screen.getByRole("combobox", { name: "Appearance" }), {
            target: { value: "royal-plum" },
        })

        expect(Object.keys(window.localStorage)).toEqual(["dnd-ai-theme"])
        expect(window.localStorage.getItem("dnd-ai-theme")).not.toContain(
            sessionBootstrapFixture.csrf_token,
        )
    })

    it("hosts the campaign startup form", () => {
        renderPage()
        const startup = screen.getByRole("region", { name: "Campaign startup" })

        expect(
            within(startup).getByRole("radio", {
                name: "Resume my last visited campaign",
            }),
        ).toBeChecked()
        expect(
            within(startup).getByRole("radio", { name: "Always open this campaign" }),
        ).toBeInTheDocument()
    })
})

// A8a: nothing from one account's save or draft is shown to another account.
describe("SettingsPage account isolation", () => {
    const alpha = { ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "campaign-a", campaign_name: "Alpha Campaign" }
    const beta = { ...alpha, campaign_id: "campaign-b", campaign_name: "Beta Campaign" }
    const userBootstrap = (userId: string, preferred: string | null): SessionBootstrap => ({
        ...sessionBootstrapFixture,
        user: { ...sessionBootstrapFixture.user, user_id: userId },
        campaigns: [alpha, beta],
        campaign_preferences: {
            startup_mode: preferred === null ? "resume_last_visited" : "preferred_campaign",
            preferred_campaign_id: preferred,
            last_visited_campaign_id: null,
        },
    })
    let publish: (next: SessionBootstrap) => void = () => undefined

    function Shared() {
        const [bootstrap, setBootstrap] = useState(() => userBootstrap("user-one", null))
        publish = setBootstrap
        return (
            <SessionContext.Provider
                value={{
                    state: { status: "authenticated", bootstrap },
                    reload: vi.fn(),
                    // The read-back is never applied, so the first user's save stays an unconfirmed episode.
                    refresh: async () => false,
                }}
            >
                <ThemeProvider>
                    <MemoryRouter>
                        <SettingsPage bootstrap={bootstrap} reload={vi.fn()} />
                    </MemoryRouter>
                </ThemeProvider>
            </SessionContext.Provider>
        )
    }

    it("drops the previous account's notice, draft and status when another account's bootstrap is published", async () => {
        setPreferenceMock.mockResolvedValue(undefined)
        render(<Shared />)
        fireEvent.click(screen.getByRole("radio", { name: "Always open this campaign" }))
        fireEvent.change(screen.getByRole("combobox", { name: "Campaign" }), { target: { value: "campaign-b" } })
        fireEvent.click(screen.getByRole("button", { name: /save startup preference/i }))
        expect(await screen.findByRole("alert")).toHaveTextContent("could not be confirmed")
        // A newer draft of the first user, then the second user's own bootstrap.
        fireEvent.change(screen.getByRole("combobox", { name: "Campaign" }), { target: { value: "campaign-a" } })
        act(() => publish(userBootstrap("user-two", null)))
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
        expect(screen.getByRole("status")).toBeEmptyDOMElement()
        expect(screen.getByRole("radio", { name: "Resume my last visited campaign" })).toBeChecked()
        expect(screen.getByRole("combobox", { name: "Campaign" })).toHaveValue("")
        expect(setPreferenceMock).toHaveBeenCalledTimes(1)
    })
})
