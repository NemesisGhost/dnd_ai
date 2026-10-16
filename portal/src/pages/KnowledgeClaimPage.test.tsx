import { screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { KnowledgeDetail } from "../types/knowledge"
import { KnowledgeClaimPage } from "./KnowledgeClaimPage"

const item: KnowledgeDetail = {
    knowledge_item_id: "k1",
    knowledge_type_code: "secret",
    statement: "The duke is a vampire.",
    truth_status_code: null,
    sensitivity: null,
    awareness_level: null,
    confidence: null,
    willing_to_share: null,
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function render(
    characterId: string | null,
    capabilities: string[] = ["campaign.view"],
    shown: KnowledgeDetail = item,
) {
    const server = installMockServer()
    renderAuthoringRoutes({
        initialEntry: "/app/c1/knowledge/k1",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [
            {
                path: "/app/:campaignId/knowledge/:knowledgeItemId",
                element: (
                    <KnowledgeClaimPage
                        campaignId="c1"
                        knowledgeItemId="k1"
                        item={shown}
                        characterId={characterId}
                        partyId={null}
                        refreshDetail={vi.fn()}
                    />
                ),
            },
        ],
    })
    return server
}

describe("KnowledgeClaimPage character knowledge", () => {
    it("explains that a perspective is needed, in one message, when none is selected", async () => {
        render(null)
        expect(await screen.findByText(/Select a character perspective/)).toBeInTheDocument()
        expect(screen.queryByText("Not recorded")).toBeNull()
        expect(screen.queryByText("Awareness")).toBeNull()
        expect(screen.queryByText("Confidence")).toBeNull()
        expect(screen.queryByText("Willing to share")).toBeNull()
    })

    it("says nothing is recorded, rather than listing empty fields, when a perspective is selected", async () => {
        render("c9")
        expect(await screen.findByText(/no recorded knowledge of this claim/)).toBeInTheDocument()
        expect(screen.queryByText("Not recorded")).toBeNull()
    })

    it("makes no request for a reader beyond the page's own data", async () => {
        const server = render(null)
        await screen.findByText("The duke is a vampire.")
        expect(server.calls).toHaveLength(0)
    })

    it("names public lore as the path, with its awareness and no invented personal fields", async () => {
        render("c1", ["campaign.view"], {
            ...item,
            scope: "public",
            awareness_level: "aware",
            character_knowledge: { path: "public", awareness_level: "aware", confidence: null, willing_to_share: null },
        })
        expect(await screen.findByText(/Public knowledge\. The character has no personal record of it\./)).toBeInTheDocument()
        expect(screen.getByText("Aware")).toBeInTheDocument()
        expect(screen.queryByText("Confidence")).toBeNull()
        expect(screen.queryByText("Willing to share")).toBeNull()
        expect(screen.queryByText(/no recorded knowledge of this claim/)).toBeNull()
    })

    it("names a party path and a direct record accurately, with the recorded values", async () => {
        render("c1", ["campaign.view"], {
            ...item,
            scope: "party",
            character_knowledge: { path: "party", awareness_level: "rumored", confidence: 30, willing_to_share: true },
        })
        expect(await screen.findByText("Known through a party the character belongs to.")).toBeInTheDocument()
        expect(screen.getByText("Rumored")).toBeInTheDocument()
        expect(screen.getByText("30%")).toBeInTheDocument()
        expect(screen.getByText("Yes")).toBeInTheDocument()
    })

    it("says the character has no knowledge only when the server found no path", async () => {
        render("c1", ["campaign.view"], { ...item, scope: "canonical", character_knowledge: null })
        expect(await screen.findByText(/no recorded knowledge of this claim/)).toBeInTheDocument()
    })
})
