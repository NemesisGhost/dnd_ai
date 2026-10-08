import { render, screen, fireEvent } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { KnowledgeDetail } from "../types/knowledge"
import { KnowledgeDetailPage } from "./KnowledgeDetailPage"

const { accessOverviewStateRef } = vi.hoisted(() => ({
    accessOverviewStateRef: { current: { status: "loading" } as Record<string, unknown> },
}))

vi.mock("../hooks/useAccessOverview", () => ({
    useAccessOverview: () => ({ state: accessOverviewStateRef.current, retry: vi.fn() }),
}))

const itemFixture: KnowledgeDetail = {
    knowledge_item_id: "knowledge-a",
    knowledge_type_code: "fact",
    statement: "The Glass Ossuary lies beneath the Rootspire.",
    truth_status_code: null,
    sensitivity: null,
    awareness_level: "understood",
    confidence: 85,
    willing_to_share: true,
}

function renderPage(item: KnowledgeDetail) {
    return render(
        <MemoryRouter>
            <KnowledgeDetailPage campaignId="campaign-a" item={item} />
        </MemoryRouter>,
    )
}

describe("KnowledgeDetailPage", () => {
    it("renders one page heading, back link, and type treatment", () => {
        renderPage(itemFixture)

        expect(
            screen.getByRole("heading", {
                level: 1,
                name: itemFixture.statement,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("link", { name: "Back to Knowledge" }),
        ).toHaveAttribute("href", "/app/campaign-a/knowledge")

        expect(screen.getByText("Fact")).toBeInTheDocument()
    })

    it("shows awareness, confidence, and sharing", () => {
        renderPage(itemFixture)

        expect(screen.getByText("Understood")).toBeInTheDocument()
        expect(screen.getByText("85%")).toBeInTheDocument()
        expect(screen.getByText("Yes")).toBeInTheDocument()
    })

    it("omits the canonical panel when truth and sensitivity are both absent", () => {
        renderPage(itemFixture)

        expect(screen.queryByText("Canonical Information")).not.toBeInTheDocument()
    })

    it("shows canonical/truth information only when present", () => {
        renderPage({
            ...itemFixture,
            truth_status_code: "confirmed_false",
            sensitivity: "high",
        })

        expect(screen.getByText("Canonical Information")).toBeInTheDocument()
        expect(screen.getByText("Confirmed False")).toBeInTheDocument()
        expect(screen.getByText("High")).toBeInTheDocument()
    })

    it("shows deliberate null handling for nullable facts", () => {
        renderPage({
            ...itemFixture,
            awareness_level: null,
            confidence: null,
            willing_to_share: null,
        })

        expect(screen.getAllByText("Not recorded").length).toBeGreaterThan(0)
    })
})

describe("KnowledgeDetailPage — audience preview (Phase 13E-B manual-acceptance fix)", () => {
    it("shows 'Preview as member' locked to this knowledge item for a GM/admin membership", () => {
        accessOverviewStateRef.current = {
            status: "success",
            overview: {
                members: [
                    {
                        campaign_membership_id: "membership-a",
                        display_name: "Player One",
                        user_id: "user-1",
                    },
                ],
                assignable_roles: [],
                assignable_characters: [],
                assignable_relationship_types: [],
                grantable_resource_capabilities: [],
                access_groups: [],
            },
        }

        render(
            <SessionContext.Provider
                value={{
                    state: {
                        status: "authenticated",
                        bootstrap: {
                            ...sessionBootstrapFixture,
                            campaigns: sessionBootstrapFixture.campaigns.map((campaign) => ({
                                ...campaign,
                                campaign_id: "campaign-a",
                                capabilities: ["access.manage"],
                            })),
                        },
                    },
                    reload: vi.fn(), refresh: vi.fn(),
                }}
            >
                <MemoryRouter>
                    <KnowledgeDetailPage campaignId="campaign-a" item={itemFixture} />
                </MemoryRouter>
            </SessionContext.Provider>,
        )

        fireEvent.click(screen.getByRole("button", { name: "Preview as member" }))

        expect(screen.queryByLabelText("Knowledge item")).not.toBeInTheDocument()
    })

    it("does not show 'Preview as member' without access.manage", () => {
        renderPage(itemFixture)

        expect(
            screen.queryByRole("button", { name: "Preview as member" }),
        ).not.toBeInTheDocument()
    })

    describe("subject row", () => {
        it("links an organization subject to its World detail page", () => {
            renderPage({
                ...itemFixture,
                subject: {
                    entity_id: "org-a",
                    name: "The Cartographers Guild",
                    category: "organization",
                    entity_type_code: "organization",
                },
            })

            expect(screen.getByText("About:")).toBeInTheDocument()
            expect(screen.getByText("(Organization)")).toBeInTheDocument()
            expect(
                screen.getByRole("link", { name: "The Cartographers Guild" }),
            ).toHaveAttribute("href", "/app/campaign-a/world/organization/org-a")
            expect(screen.queryByText("org-a")).not.toBeInTheDocument()
        })

        it("links a quest subject with the detail's own party perspective", () => {
            render(
                <MemoryRouter>
                    <KnowledgeDetailPage
                        campaignId="campaign-a"
                        item={{
                            ...itemFixture,
                            subject: {
                                entity_id: "quest-a",
                                name: "Clear the Old Mill",
                                category: "quest",
                                entity_type_code: "quest",
                            },
                        }}
                        characterId="character-a"
                        partyId="party-a"
                    />
                </MemoryRouter>,
            )

            expect(
                screen.getByRole("link", { name: "Clear the Old Mill" }),
            ).toHaveAttribute(
                "href",
                "/app/campaign-a/quests/quest-a?character_id=character-a&party_id=party-a",
            )
        })

        it("omits the row when the server returned no subject summary", () => {
            renderPage({ ...itemFixture, subject: null })

            expect(screen.queryByText("About:")).not.toBeInTheDocument()
        })
    })
})

