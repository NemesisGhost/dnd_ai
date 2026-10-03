import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    MemoryRouter,
    Route,
    Routes,
} from "react-router"
import {
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type {
    CampaignQuestListItem,
} from "../types/quest"
import { QuestsPage } from "./QuestsPage"

const { accessOverviewStateRef } = vi.hoisted(() => ({
    accessOverviewStateRef: { current: { status: "loading" } as Record<string, unknown> },
}))

vi.mock("../hooks/useAccessOverview", () => ({
    useAccessOverview: () => ({ state: accessOverviewStateRef.current, retry: vi.fn() }),
}))

const quests = [
    {
        quest_id: "quest-zeta",
        name: "Zeta Quest",
        status_code: "active",
    },
    {
        quest_id: "quest-alpha",
        name: "Alpha Quest",
        status_code: null,
    },
    {
        quest_id: "quest-beta",
        name: "Beta Quest",
        status_code: "completed",
    },
] satisfies CampaignQuestListItem[]

function renderQuestsPage(
    pageQuests: CampaignQuestListItem[],
) {
    render(
        <MemoryRouter
            initialEntries={[
                "/app/test-campaign/quests",
            ]}
        >
            <Routes>
                <Route
                    path="/app/:campaignId/quests"
                    element={
                        <QuestsPage
                            campaignId="test-campaign"
                            quests={pageQuests}
                        />
                    }
                />
            </Routes>
        </MemoryRouter>,
    )
}

function questNamesInCardOrder(): string[] {
    const grid = screen.getByRole("list", { name: "Quests" })

    return Array.from(
        grid.querySelectorAll(".entity-card__title"),
    ).map((element) => element.textContent ?? "")
}

describe("QuestsPage", () => {
    it("shows a perspective-aware empty state", () => {
        renderQuestsPage([])

        expect(
            screen.getByRole("heading", {
                level: 1,
                name: "Quests",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "No quests are available for this campaign and perspective.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("list"),
        ).not.toBeInTheDocument()
    })

    it("lists quests alphabetically by default with campaign-relative detail links", () => {
        renderQuestsPage(quests)

        expect(questNamesInCardOrder()).toEqual([
            "Alpha Quest",
            "Beta Quest",
            "Zeta Quest",
        ])

        expect(
            screen.getByRole("link", {
                name: /Alpha Quest/,
            }),
        ).toHaveAttribute(
            "href",
            "/app/test-campaign/quests/quest-alpha",
        )

        expect(
            screen.getByText("No status recorded"),
        ).toBeInTheDocument()
    })

    it("does not invent card content beyond name and status", () => {
        renderQuestsPage(quests)

        expect(screen.queryByText(/objective/i)).not.toBeInTheDocument()
        expect(screen.queryByText(/reward/i)).not.toBeInTheDocument()
    })

    it("sorts by name in descending order", () => {
        renderQuestsPage(quests)

        fireEvent.change(
            screen.getByRole("combobox", { name: "Direction" }),
            { target: { value: "desc" } },
        )

        expect(questNamesInCardOrder()).toEqual([
            "Zeta Quest",
            "Beta Quest",
            "Alpha Quest",
        ])
    })

    it("sorts by status ascending, keeping missing status last", () => {
        renderQuestsPage(quests)

        fireEvent.change(
            screen.getByRole("combobox", { name: "Sort by" }),
            { target: { value: "status" } },
        )

        expect(questNamesInCardOrder()).toEqual([
            "Zeta Quest",
            "Beta Quest",
            "Alpha Quest",
        ])
    })

    it("sorts by status descending, still keeping missing status last", () => {
        renderQuestsPage(quests)

        fireEvent.change(
            screen.getByRole("combobox", { name: "Sort by" }),
            { target: { value: "status" } },
        )

        fireEvent.change(
            screen.getByRole("combobox", { name: "Direction" }),
            { target: { value: "desc" } },
        )

        expect(questNamesInCardOrder()).toEqual([
            "Beta Quest",
            "Zeta Quest",
            "Alpha Quest",
        ])
    })
})

describe("QuestsPage — audience preview (Phase 13E-B manual-acceptance fix)", () => {
    it("shows 'Preview as member' to a GM/admin campaign membership", () => {
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
                                campaign_id: "test-campaign",
                                capabilities: ["access.manage"],
                            })),
                        },
                    },
                    reload: vi.fn(), refresh: vi.fn(),
                }}
            >
                <MemoryRouter initialEntries={["/app/test-campaign/quests"]}>
                    <Routes>
                        <Route
                            path="/app/:campaignId/quests"
                            element={<QuestsPage campaignId="test-campaign" quests={quests} />}
                        />
                    </Routes>
                </MemoryRouter>
            </SessionContext.Provider>,
        )

        expect(screen.getByRole("button", { name: "Preview as member" })).toBeInTheDocument()
    })

    it("does not show 'Preview as member' without access.manage", () => {
        renderQuestsPage(quests)

        expect(
            screen.queryByRole("button", { name: "Preview as member" }),
        ).not.toBeInTheDocument()
    })
})
