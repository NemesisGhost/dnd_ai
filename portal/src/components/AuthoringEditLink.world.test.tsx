import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import {
    CAMPAIGN_ONLY_RECORD_AUTHORING,
    EDITOR_RECORD_AUTHORING,
    FULL_RECORD_AUTHORING,
    ORIGINATED_RECORD_AUTHORING,
    REVIEWER_RECORD_AUTHORING,
} from "../test/recordAuthoring"
import { AuthoringEditLink } from "./AuthoringEditLink"

const base = sessionBootstrapFixture.campaigns[0]!

function renderLink(detail: object, capabilities: readonly string[] = ["campaign.view", "canon.edit"]) {
    vi.stubGlobal(
        "fetch",
        vi.fn(
            async () =>
                new Response(
                    JSON.stringify({
                        row_version: 1,
                        canon_status: "draft",
                        available_actions: ["update"],
                        blocked_actions: [],
                    }),
                    { status: 200 },
                ),
        ),
    )
    const bootstrap = {
        ...sessionBootstrapFixture,
        campaigns: [{ ...base, capabilities: [...capabilities], world_capabilities: [] }],
    }
    render(
        <SessionContext.Provider
            value={{
                state: { status: "authenticated", bootstrap },
                reload: vi.fn(),
                refresh: vi.fn(),
            }}
        >
            <MemoryRouter>
                <AuthoringEditLink
                    campaignId={base.campaign_id}
                    viewPath="/view"
                    editPath="/edit"
                    noun="location"
                    detail={detail}
                />
            </MemoryRouter>
        </SessionContext.Provider>,
    )
}

afterEach(() => {
    vi.unstubAllGlobals()
})

// The link decides from the record's own server-computed `authoring` (the bootstrap's world
// snapshot is deliberately empty in every case here: it plays no part).
describe("AuthoringEditLink and the world boundary", () => {
    it("offers the edit link when the server says the definition is the caller's to edit", async () => {
        renderLink({ authoring: EDITOR_RECORD_AUTHORING })
        expect(await screen.findByRole("link", { name: "Edit location" })).toBeInTheDocument()
    })

    it("offers it to an owner who holds every flag", async () => {
        renderLink({ authoring: FULL_RECORD_AUTHORING })
        expect(await screen.findByRole("link", { name: "Edit location" })).toBeInTheDocument()
    })

    it("explains, and sends no request, when the campaign GM holds nothing of the shared definition", () => {
        renderLink({ authoring: CAMPAIGN_ONLY_RECORD_AUTHORING })
        expect(
            screen.getByText(/Editing shared world content requires the world Editor role/),
        ).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "Edit location" })).not.toBeInTheDocument()
        expect(fetch).not.toHaveBeenCalled()
    })

    it("does not turn a Reviewer into an editor", () => {
        renderLink({ authoring: REVIEWER_RECORD_AUTHORING })
        expect(screen.queryByRole("link", { name: "Edit location" })).not.toBeInTheDocument()
        expect(fetch).not.toHaveBeenCalled()
    })

    it("offers a campaign-originated record to a campaign-only GM", async () => {
        renderLink({ authoring: ORIGINATED_RECORD_AUTHORING })
        expect(await screen.findByRole("link", { name: "Edit location" })).toBeInTheDocument()
    })

    it("grants nothing to a detail that carries no eligibility", () => {
        renderLink({})
        expect(screen.queryByRole("link", { name: "Edit location" })).not.toBeInTheDocument()
        expect(fetch).not.toHaveBeenCalled()
    })

    it("mounts nothing for a player", () => {
        renderLink({ authoring: FULL_RECORD_AUTHORING }, ["campaign.view"])
        expect(screen.queryByRole("link", { name: "Edit location" })).not.toBeInTheDocument()
        expect(fetch).not.toHaveBeenCalled()
    })
})
