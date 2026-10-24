import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { useState } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import { CharacterParties } from "./CharacterParties"

afterEach(() => {
    vi.unstubAllGlobals()
})

const PATH = (character: string) => `/campaigns/c1/characters/${character}/parties`

const parties = (names: string[], canOpen = false) => ({
    character_id: "hero",
    can_open: canOpen,
    items: names.map((name, index) => ({ party_id: `p${index + 1}`, name })),
})

// Both characters selectable, as the Info Box's selector would offer.
function Harness() {
    const [character, setCharacter] = useState("hero")
    return (
        <>
            <button type="button" onClick={() => setCharacter("ally")}>
                Choose ally
            </button>
            <CharacterParties campaignId="c1" characterId={character} />
        </>
    )
}

function render(server: MockServer) {
    void server
    return renderAuthoringRoutes({
        initialEntry: "/app/c1/home",
        routes: [{ path: "/app/:campaignId/home", element: <Harness /> }],
    })
}

describe("CharacterParties", () => {
    it("is a collapsed disclosure counting the memberships it may show, listing them in server order", async () => {
        const server = installMockServer()
        server.on("GET", PATH("hero"), { body: parties(["Alpha Company", "Zeta Band"]) })
        const { container } = render(server)
        const summary = await screen.findByText("Parties (2)")
        const details = container.querySelector("details.campaign-context-panel__parties")!
        expect(details).not.toHaveAttribute("open")
        fireEvent.click(summary)
        expect(details).toHaveAttribute("open")
        expect(within(details as HTMLElement).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
            "Alpha Company",
            "Zeta Band",
        ])
        // Names are plain text unless the server says the caller may open a party.
        expect(screen.queryByRole("link", { name: "Alpha Company" })).toBeNull()
    })

    it("links each name to the existing party page only when the server says it may be opened", async () => {
        const server = installMockServer()
        server.on("GET", PATH("hero"), { body: parties(["Alpha Company"], true) })
        render(server)
        fireEvent.click(await screen.findByText("Parties (1)"))
        expect(screen.getByRole("link", { name: "Alpha Company" })).toHaveAttribute("href", "/app/c1/parties/p1")
    })

    it("says No party memberships. for a loaded empty list, with a zero count", async () => {
        const server = installMockServer()
        server.on("GET", PATH("hero"), { body: parties([]) })
        render(server)
        fireEvent.click(await screen.findByText("Parties (0)"))
        expect(screen.getByText("No party memberships.")).toBeInTheDocument()
        expect(screen.queryByText("Parties could not be loaded.")).toBeNull()
    })

    it("shows loading without a count, then a failure with a retry that recovers", async () => {
        const server = installMockServer()
        let attempts = 0
        server.on("GET", PATH("hero"), () => {
            attempts += 1
            return attempts === 1 ? { status: 500, body: { error: { code: "internal_error" } } } : { body: parties(["Alpha"]) }
        })
        render(server)
        expect(screen.getByText("Loading parties…")).toBeInTheDocument()
        expect(screen.queryByText(/Parties \(/)).toBeNull()
        expect(await screen.findByRole("status")).toHaveTextContent("Parties could not be loaded.")
        // A failure is not an empty list.
        expect(screen.queryByText("No party memberships.")).toBeNull()
        expect(screen.queryByText(/Parties \(/)).toBeNull()
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        expect(await screen.findByText("Parties (1)")).toBeInTheDocument()
    })

    it("reveals nothing, not even a count, when the list is unavailable or not permitted", async () => {
        const server = installMockServer()
        server.on("GET", PATH("hero"), { status: 404, body: { error: { code: "not_found" } } })
        render(server)
        expect(await screen.findByText("Parties unavailable.")).toBeInTheDocument()
        expect(screen.queryByText(/Parties \(/)).toBeNull()
        expect(screen.queryByText("No party memberships.")).toBeNull()
    })

    it("never shows one character's parties under another, and starts the next one collapsed", async () => {
        const server = installMockServer()
        let release: (() => void) | null = null
        server.on("GET", PATH("hero"), { body: parties(["Hero Company"]) })
        server.on("GET", PATH("ally"), async () => {
            await new Promise<void>((resolve) => {
                release = resolve
            })
            return { body: { ...parties(["Ally Circle"]), character_id: "ally" } }
        })
        const { container } = render(server)
        fireEvent.click(await screen.findByText("Parties (1)"))
        expect(screen.getByText("Hero Company")).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Choose ally" }))
        // While the ally's list loads, the hero's is gone.
        expect(await screen.findByText("Loading parties…")).toBeInTheDocument()
        expect(screen.queryByText("Hero Company")).toBeNull()
        expect(screen.queryByText("Parties (1)")).toBeNull()

        await waitFor(() => expect(release).not.toBeNull())
        release!()
        expect(await screen.findByText("Parties (1)")).toBeInTheDocument()
        const details = container.querySelector("details.campaign-context-panel__parties")!
        expect(details).not.toHaveAttribute("open")
        fireEvent.click(screen.getByText("Parties (1)"))
        expect(screen.getByText("Ally Circle")).toBeInTheDocument()
        expect(screen.queryByText("Hero Company")).toBeNull()
        expect(server.calls.map((call) => call.path)).toEqual([PATH("hero"), PATH("ally")])
    })

    it("is informational: reading and expanding it makes no request beyond the list itself", async () => {
        const server = installMockServer()
        server.on("GET", PATH("hero"), { body: parties(["Alpha Company"], true) })
        render(server)
        fireEvent.click(await screen.findByText("Parties (1)"))
        expect(server.calls).toHaveLength(1)
        expect(server.calls.every((call) => call.method === "GET" && !/knowledge/.test(call.path))).toBe(true)
    })
})
