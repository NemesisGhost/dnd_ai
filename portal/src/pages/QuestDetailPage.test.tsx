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
} from "vitest"
import type {
    QuestDetail,
} from "../types/quest"
import { QuestDetailPage } from "./QuestDetailPage"

const questFixture = {
    quest_id: "quest-a",
    name: "Restore the Lens Array",
    status_code: "active",
    stages: [
        {
            quest_stage_id: "stage-second",
            name: "Second Returned Stage",
            description:
                "This stage appears first in the authorized response.",
            sequence_number: 2,
            stage_type: "sequential",
            objectives: [
                {
                    quest_objective_id: "objective-a",
                    name: "Align the lens pylons",
                    description:
                        "Rotate each pylon into position.",
                    requirement_level: "required",
                    completion_mode: "all",
                    visibility_policy:
                        "hidden_until_active",
                    quantity_required: 4,
                    status_code: null,
                },
            ],
        },
        {
            quest_stage_id: "stage-first",
            name: "First Numbered Stage",
            description: null,
            sequence_number: 1,
            stage_type: "optional",
            objectives: [],
        },
    ],
} satisfies QuestDetail

function renderQuestDetail(
    quest: QuestDetail,
) {
    return render(
        <MemoryRouter
            initialEntries={[
                `/app/test-campaign/quests/${quest.quest_id}`,
            ]}
        >
            <Routes>
                <Route
                    path="/app/:campaignId/quests/:questId"
                    element={
                        <QuestDetailPage quest={quest} />
                    }
                />
            </Routes>
        </MemoryRouter>,
    )
}

describe("QuestDetailPage", () => {
    it("renders one page heading, status, and a Back to quests link", () => {
        renderQuestDetail(questFixture)

        expect(
            screen.getByRole("heading", {
                level: 1,
                name: "Restore the Lens Array",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText("Status: Active"),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("heading", {
                level: 2,
                name: "Stages and Objectives",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("link", {
                name: "Back to quests",
            }),
        ).toHaveAttribute(
            "href",
            "/app/test-campaign/quests",
        )
    })

    it("preserves the server-provided stage order rather than alphabetizing", () => {
        renderQuestDetail(questFixture)

        const stageHeadings = screen.getAllByRole("heading", {
            level: 2,
        }).slice(1) // drop "Stages and Objectives"

        expect(stageHeadings.map((h) => h.textContent)).toEqual([
            "2. Second Returned Stage",
            "1. First Numbered Stage",
        ])
    })

    it("shows stage type and description", () => {
        renderQuestDetail(questFixture)

        expect(screen.getByText("Sequential")).toBeInTheDocument()
        expect(
            screen.getByText(
                "This stage appears first in the authorized response.",
            ),
        ).toBeInTheDocument()
    })

    it("renders objectives as expandable, keyboard-accessible disclosures", () => {
        renderQuestDetail(questFixture)

        const summary = screen.getByText("Align the lens pylons")
        const details = summary.closest("details")
        expect(details).not.toBeNull()
        expect(details).not.toHaveAttribute("open")

        // Description is inside the collapsed body — not visible as text
        // content in a way that implies it's already open, but present in
        // the DOM for a native <details> element.
        fireEvent.click(summary)
        expect(details).toHaveAttribute("open")

        expect(
            screen.getByText("Rotate each pylon into position."),
        ).toBeInTheDocument()
        expect(screen.getByText("No status recorded")).toBeInTheDocument()
        expect(screen.getByText("Required")).toBeInTheDocument()
        expect(screen.getByText("All")).toBeInTheDocument()
        expect(screen.getByText("4")).toBeInTheDocument()
    })

    it("omits quantity when not present and never exposes visibility metadata or raw ids", () => {
        renderQuestDetail(questFixture)

        expect(
            screen.queryByText("hidden_until_active"),
        ).not.toBeInTheDocument()
        expect(screen.queryByText("objective-a")).not.toBeInTheDocument()
        expect(screen.queryByText("stage-second")).not.toBeInTheDocument()
    })

    it("shows a deliberate empty state for a stage with no objectives", () => {
        renderQuestDetail(questFixture)

        expect(
            screen.getByText(
                "No objectives are available for this stage.",
            ),
        ).toBeInTheDocument()
    })

    it("shows neutral fallbacks when quest status and stages are unavailable", () => {
        const emptyQuest = {
            quest_id: "quest-empty",
            name: "Unstructured Quest",
            status_code: null,
            stages: [],
        } satisfies QuestDetail

        renderQuestDetail(emptyQuest)

        expect(
            screen.getByText(
                "Status: No status recorded",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "No stages are available for this quest.",
            ),
        ).toBeInTheDocument()
    })
})
