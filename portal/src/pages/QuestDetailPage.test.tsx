import {
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
    it("renders the quest and preserves the server-provided stage order", () => {
        renderQuestDetail(questFixture)

        expect(
            screen.getByRole("heading", {
                level: 1,
                name: "Restore the Lens Array",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText("Status: active"),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("heading", {
                level: 2,
                name: "Stages and objectives",
            }),
        ).toBeInTheDocument()

        const table = screen.getByRole("table", {
            name: "Quest stages and objectives",
        })

        const stageRows =
            within(table).getAllByRole("row").slice(1)

        const stageNames = stageRows.map((row) =>
            within(row).getAllByRole("cell")[1]
                ?.textContent ?? "",
        )

        expect(stageNames).toEqual([
            "Second Returned Stage",
            "First Numbered Stage",
        ])

        expect(
            screen.getByRole("link", {
                name: "Back to quests",
            }),
        ).toHaveAttribute(
            "href",
            "/app/test-campaign/quests",
        )
    })

    it("renders only returned objective information without exposing visibility metadata", () => {
        renderQuestDetail(questFixture)

        expect(
            screen.getByText(
                "1 available objective",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "Align the lens pylons",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "Rotate each pylon into position.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "No status recorded",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "No objectives are available for this stage.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "No description recorded",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(
                "hidden_until_active",
            ),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText(
                "objective-a",
            ),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText(
                "stage-second",
            ),
        ).not.toBeInTheDocument()
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

        expect(
            screen.queryByRole("table"),
        ).not.toBeInTheDocument()
    })
})