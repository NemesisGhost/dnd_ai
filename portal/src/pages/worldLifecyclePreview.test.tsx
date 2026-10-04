import { fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fetchWorldEntities } from "../api/world"
import { WorldCard } from "../components/WorldCard"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { useWorldEntities } from "../hooks/useWorldEntities"
import type { WorldEntityCard, WorldEntityPage } from "../types/world"
import { CampaignWorldPage } from "./CampaignWorldPage"

vi.mock("../hooks/useWorldEntities", () => ({ useWorldEntities: vi.fn() }))
const useWorldEntitiesMock = vi.mocked(useWorldEntities)

const card = (over: Partial<WorldEntityCard> = {}): WorldEntityCard => ({
    entity_id: "l1",
    category: "location",
    entity_type_code: "city",
    name: "Glass Harbor",
    summary: null,
    canon_status: "canon",
    lifecycle_status: "active",
    ...over,
})

describe("World list lifecycle badges", () => {
    function renderCard(entity: WorldEntityCard) {
        return render(
            <MemoryRouter>
                <ul>
                    <WorldCard campaignId="c" entity={entity} />
                </ul>
            </MemoryRouter>,
        )
    }

    it("shows no badge for an active canon record", () => {
        renderCard(card())
        expect(screen.queryByText("Draft")).not.toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Glass Harbor, Location - City" })).toBeInTheDocument()
    })

    it("labels a draft in text and in the link name", () => {
        renderCard(card({ canon_status: "draft" }))
        expect(screen.getByText("Draft")).toBeInTheDocument()
        expect(screen.getByRole("link", { name: /Glass Harbor, .*, draft/ })).toBeInTheDocument()
    })

    it("labels an archived record as archived even when its canon status is canon", () => {
        renderCard(card({ lifecycle_status: "archived" }))
        expect(screen.getByText("Archived")).toBeInTheDocument()
    })

    it("tolerates a card without status fields (older payload)", () => {
        renderCard(card({ canon_status: undefined, lifecycle_status: undefined }))
        expect(screen.queryByText("Draft")).not.toBeInTheDocument()
        expect(screen.queryByText("Archived")).not.toBeInTheDocument()
    })
})

describe("fetchWorldEntities includeHidden", () => {
    afterEach(() => vi.unstubAllGlobals())

    async function urlFor(includeHidden: boolean | undefined): Promise<string> {
        const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [], next_cursor: null }) })
        vi.stubGlobal("fetch", fetchMock)
        await fetchWorldEntities("c", { category: null, query: "", includeHidden })
        return String(fetchMock.mock.calls[0]![0])
    }

    it("adds both preview flags only when asked", async () => {
        expect(await urlFor(true)).toBe("/api/campaigns/c/world/search?include_noncanon=true&include_archived=true")
        expect(await urlFor(false)).toBe("/api/campaigns/c/world/search")
        expect(await urlFor(undefined)).toBe("/api/campaigns/c/world/search")
    })
})

describe("World page drafts and archived toggle", () => {
    const page: WorldEntityPage = { items: [card()], next_cursor: null }

    beforeEach(() => {
        useWorldEntitiesMock.mockReset()
        useWorldEntitiesMock.mockReturnValue({ state: { status: "success", page }, retry: vi.fn() })
    })

    function renderPage(capabilities: string[] | null) {
        const bootstrap = {
            ...sessionBootstrapFixture,
            campaigns: [
                { ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c", capabilities: capabilities ?? [] },
            ],
        }
        const tree = (
            <MemoryRouter initialEntries={["/app/c/world"]}>
                <Routes>
                    <Route path="/app/:campaignId/world" element={<CampaignWorldPage />} />
                </Routes>
            </MemoryRouter>
        )
        return render(
            capabilities === null ? (
                tree
            ) : (
                <SessionContext.Provider
                    value={{
                        state: { status: "authenticated", bootstrap },
                        reload: vi.fn(),
                        refresh: vi.fn(),
                    }}
                >
                    {tree}
                </SessionContext.Provider>
            ),
        )
    }

    it("is not offered to a player", () => {
        renderPage(["campaign.view"])
        expect(screen.queryByRole("checkbox", { name: "Show drafts and archived" })).not.toBeInTheDocument()
        expect(useWorldEntitiesMock).toHaveBeenLastCalledWith("c", null, "", null, false)
    })

    it("is not offered without a session at all", () => {
        renderPage(null)
        expect(screen.queryByRole("checkbox", { name: "Show drafts and archived" })).not.toBeInTheDocument()
    })

    it("is offered with canon.edit and requests the hidden records when checked", () => {
        renderPage(["campaign.view", "canon.edit"])
        const toggle = screen.getByRole("checkbox", { name: "Show drafts and archived" })
        expect(toggle).not.toBeChecked()
        expect(useWorldEntitiesMock).toHaveBeenLastCalledWith("c", null, "", null, false)
        fireEvent.click(toggle)
        expect(screen.getByRole("checkbox", { name: "Show drafts and archived" })).toBeChecked()
        expect(useWorldEntitiesMock).toHaveBeenLastCalledWith("c", null, "", null, true)
        fireEvent.click(screen.getByRole("checkbox", { name: "Show drafts and archived" }))
        expect(useWorldEntitiesMock).toHaveBeenLastCalledWith("c", null, "", null, false)
    })
})
