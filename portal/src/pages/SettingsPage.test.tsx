import { fireEvent, render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { ThemeProvider } from "../themes/ThemeProvider"
import { SettingsPage } from "./SettingsPage"

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
