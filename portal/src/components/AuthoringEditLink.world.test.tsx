import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { AuthoringEditLink } from "./AuthoringEditLink"

const base = sessionBootstrapFixture.campaigns[0]!

function renderLink(worldCapabilities: readonly string[] | undefined) {
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
        campaigns: [
            {
                ...base,
                capabilities: ["campaign.view", "canon.edit"],
                world_capabilities: worldCapabilities,
            },
        ],
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
                    detail={{}}
                />
            </MemoryRouter>
        </SessionContext.Provider>,
    )
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("AuthoringEditLink and the world boundary", () => {
    it("offers the edit link to a world Editor who also holds campaign canon.edit", async () => {
        renderLink(["world.view", "world.canon.edit"])
        expect(await screen.findByRole("link", { name: "Edit location" })).toBeInTheDocument()
    })

    it("explains, and sends no request, when the campaign GM has no world Editor role", () => {
        renderLink(["world.view"])
        expect(
            screen.getByText(/Editing shared world content requires the world Editor role/),
        ).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "Edit location" })).not.toBeInTheDocument()
        expect(fetch).not.toHaveBeenCalled()
    })

    it("does not hide the link from a bootstrap that carries no world capabilities", async () => {
        renderLink(undefined)
        expect(await screen.findByRole("link", { name: "Edit location" })).toBeInTheDocument()
    })
})
