import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { openApp } from "../test/campaignRoutes"
import { installMockServer } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import { focusLinkArrival, notePushedEntry } from "./selectionArrival"

// P02 browser acceptance B8 and B20: a destination reached by an ordinary link (a breadcrumb, a Leave that
// completes the held navigation) puts focus on its heading once. Before this, only a destination that owned
// `usePageArrival`, or one reached by an Infobox selection, did; Campaign Home and the Characters browser
// left focus on `body`. These run over a memory data router (jsdom): they prove which element holds focus
// in jsdom, not a real browser's native dialog or keyboard behavior.

vi.mock("../hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("../api/userPreferences", () => ({
    recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const base = "/app/mundivita"
const API = "/campaigns/mundivita"

let server: MockServer

beforeEach(() => {
    server = installMockServer()
    server.on("GET", /^\/campaigns\/mundivita\/world\/search/, { body: { items: [], next_cursor: null } })
    server.on("GET", /^\/campaigns\/mundivita\/summary/, {
        body: { current_session: null, previous_session_recap: null, recent_events: [] },
    })
    server.on("GET", /^\/worlds\?/, { body: { items: [], next_cursor: null } })
    server.on("GET", `${API}/settings`, {
        body: {
            campaign_id: "mundivita",
            name: "Mundivita",
            description: null,
            lifecycle_status: "active",
            row_version: 4,
            world: { world_id: "w1", name: "Eberron" },
            timeline: { timeline_id: "t1", name: "Main" },
            ruleset_version: { ruleset_version_id: "rv1", ruleset_display_name: "D&D 5e", version_label: "2024" },
            available_actions: ["update", "archive"],
            blocked_actions: [],
        },
    })
    server.on("GET", /\/campaigns\/mundivita\/characters/, { body: { items: [], next_cursor: null } })
    server.on("GET", /\/campaigns\/mundivita\/world-times/, { body: { items: [], next_cursor: null } })
})

afterEach(() => {
    vi.unstubAllGlobals()
})

const breadcrumb = () => within(screen.getByRole("navigation", { name: "Breadcrumb" }))
const heading = (name: string) => screen.getByRole("heading", { level: 1, name })

describe("heading focus after an ordinary link", () => {
    it("a clean breadcrumb to Campaign Home focuses its heading", async () => {
        const app = openApp(`${base}/settings`)
        await screen.findByRole("textbox", { name: /Campaign name/ })
        fireEvent.click(breadcrumb().getByRole("link", { name: "Campaign Home" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/home`))
        await screen.findByRole("heading", { level: 1, name: "Campaign Home" })
        await waitFor(() => expect(heading("Campaign Home")).toHaveFocus())
    })

    it("Leave from a dirty Campaign settings form lands on the Campaign Home heading; Stay returns to the opener", async () => {
        const app = openApp(`${base}/settings`)
        const name = await screen.findByRole("textbox", { name: /Campaign name/ })
        fireEvent.change(name, { target: { value: "Renamed" } })
        const opener = breadcrumb().getByRole("link", { name: "Campaign Home" })
        opener.focus()
        fireEvent.click(opener)
        fireEvent.click(await screen.findByRole("button", { name: "Keep editing" }))
        await waitFor(() => expect(opener).toHaveFocus())
        expect(app.router.state.location.pathname).toBe(`${base}/settings`)
        fireEvent.click(opener)
        fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/home`))
        await screen.findByRole("heading", { level: 1, name: "Campaign Home" })
        await waitFor(() => expect(heading("Campaign Home")).toHaveFocus())
        expect(server.calls.filter((call) => call.method !== "GET")).toEqual([])
    })

    it("the Characters breadcrumb from the chooser returns to the browser with its heading focused", async () => {
        const app = openApp(`${base}/characters/all?type=npc`)
        fireEvent.click(await screen.findByRole("link", { name: "New character" }))
        await screen.findByRole("heading", { level: 1, name: "New character" })
        const crumb = breadcrumb().getByRole("link", { name: "Characters" })
        crumb.focus()
        fireEvent.click(crumb)
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/characters/all`))
        await screen.findByRole("heading", { level: 1, name: "Characters" })
        await waitFor(() => expect(heading("Characters")).toHaveFocus())
    })
})

describe("focusLinkArrival", () => {
    afterEach(() => {
        document.body.innerHTML = ""
    })

    function page(): { link: HTMLAnchorElement; field: HTMLInputElement; h1: HTMLElement } {
        document.body.innerHTML =
            '<a href="#" id="nav">Navbar</a><div class="campaign-workspace__content"><h1>Page</h1><input id="field" /></div>'
        return {
            link: document.getElementById("nav") as HTMLAnchorElement,
            field: document.getElementById("field") as HTMLInputElement,
            h1: document.querySelector("h1") as HTMLElement,
        }
    }

    it("takes focus from a control outside the content, once per entry", () => {
        const { link, field, h1 } = page()
        notePushedEntry("k-1")
        link.focus()
        focusLinkArrival({ key: "k-1", state: null })
        expect(h1).toHaveFocus()
        field.focus()
        focusLinkArrival({ key: "k-1", state: null })
        expect(field).toHaveFocus()
    })

    it("leaves focus the person already placed inside the content", () => {
        const { field, h1 } = page()
        notePushedEntry("k-2")
        field.focus()
        focusLinkArrival({ key: "k-2", state: null })
        expect(field).toHaveFocus()
        expect(h1).not.toHaveFocus()
    })

    it("waits while the content is still loading and claims nothing", () => {
        const { h1 } = page()
        notePushedEntry("k-3")
        h1.setAttribute("data-page-loading", "")
        focusLinkArrival({ key: "k-3", state: null })
        expect(h1).not.toHaveFocus()
        h1.removeAttribute("data-page-loading")
        focusLinkArrival({ key: "k-3", state: null })
        expect(h1).toHaveFocus()
    })

    it("moves nothing for an entry that was not reached by a PUSH (reload, Back, Forward)", () => {
        const { link, h1 } = page()
        link.focus()
        focusLinkArrival({ key: "k-never-pushed", state: null })
        expect(h1).not.toHaveFocus()
        expect(link).toHaveFocus()
    })
})
