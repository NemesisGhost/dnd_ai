import {
    fireEvent,
    render,
    screen,
    within,
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
} from "vitest"
import type {
    CampaignQuestListItem,
} from "../types/quest"
import { QuestsPage } from "./QuestsPage"

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
                        <QuestsPage quests={pageQuests} />
                    }
                />
            </Routes>
        </MemoryRouter>,
    )
}

function questNamesInTableOrder(): string[] {
    const table = screen.getByRole("table", {
        name: "Quests",
    })

    return within(table)
        .getAllByRole("link")
        .map((link) => link.textContent ?? "")
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
            screen.queryByRole("table"),
        ).not.toBeInTheDocument()
    })

    it("lists quests alphabetically with campaign-relative detail links", () => {
        renderQuestsPage(quests)

        expect(questNamesInTableOrder()).toEqual([
            "Alpha Quest",
            "Beta Quest",
            "Zeta Quest",
        ])

        expect(
            screen.getByRole("link", {
                name: "Alpha Quest",
            }),
        ).toHaveAttribute(
            "href",
            "/app/test-campaign/quests/quest-alpha",
        )

        expect(
            screen.getByText("No status recorded"),
        ).toBeInTheDocument()
    })

    it("sorts status in either direction while keeping missing status last", () => {
        renderQuestsPage(quests)

        const statusButton = screen.getByRole(
            "button",
            {
                name: "Status",
            },
        )

        fireEvent.click(statusButton)

        expect(questNamesInTableOrder()).toEqual([
            "Zeta Quest",
            "Beta Quest",
            "Alpha Quest",
        ])

        expect(
            screen.getByRole("columnheader", {
                name: "Status",
            }),
        ).toHaveAttribute(
            "aria-sort",
            "ascending",
        )

        fireEvent.click(statusButton)

        expect(questNamesInTableOrder()).toEqual([
            "Beta Quest",
            "Zeta Quest",
            "Alpha Quest",
        ])

        expect(
            screen.getByRole("columnheader", {
                name: "Status",
            }),
        ).toHaveAttribute(
            "aria-sort",
            "descending",
        )
    })
})