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
    QuestDetail,
} from "../types/quest"
import { QuestDetailPage } from "./QuestDetailPage"

const { accessOverviewStateRef } = vi.hoisted(() => ({
    accessOverviewStateRef: { current: { status: "loading" } as Record<string, unknown> },
}))

vi.mock("../hooks/useAccessOverview", () => ({
    useAccessOverview: () => ({ state: accessOverviewStateRef.current, retry: vi.fn() }),
}))

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
                        <QuestDetailPage campaignId="test-campaign" quest={quest} />
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

        const stageHeadings = screen.getAllByRole("heading", { level: 3 })

        expect(stageHeadings).toHaveLength(2)
        expect(stageHeadings[0]).toHaveTextContent(/^2\. Second Returned Stage/)
        expect(stageHeadings[1]).toHaveTextContent(/^1\. First Numbered Stage/)
    })

    it("shows stage type and description", () => {
        renderQuestDetail(questFixture)

        expect(screen.getAllByText(/Sequential/).length).toBeGreaterThan(0)
        expect(
            screen.getByText(
                "This stage appears first in the authorized response.",
            ),
        ).toBeInTheDocument()
    })

    const withStatuses = (statuses: (string | null)[]) => ({
        ...questFixture,
        stages: [
            {
                ...questFixture.stages[0]!,
                objectives: statuses.map((status_code, i) => ({
                    ...questFixture.stages[0]!.objectives[0]!,
                    quest_objective_id: `objective-${i}`,
                    name: `Objective ${i}`,
                    status_code,
                })),
            },
        ],
    })
    const stageButton = () => screen.getByRole("button", { name: /^2\. Second Returned Stage/ })

    it("counts only the shown objectives and never claims a whole-stage status", () => {
        renderQuestDetail(withStatuses(["completed"]))

        expect(stageButton()).toHaveTextContent("Shown objectives: 1 of 1 complete")
        expect(screen.getByText("Shown objectives: 1 of 1 complete.")).toBeVisible()
        expect(document.body.textContent).not.toMatch(/Stage progress|Not started|In progress/)
        expect(stageButton().textContent).not.toMatch(/bCompleteb/)
    })

    it.each([["failed"], ["skipped"], ["superseded"]])(
        "shows a %s objective's exact status and no stage-wide claim",
        (code) => {
            renderQuestDetail(withStatuses([code]))

            expect(stageButton()).toHaveTextContent("Shown objectives: 0 of 1 complete")
            expect(screen.getByText(code.charAt(0).toUpperCase() + code.slice(1))).toBeInTheDocument()
            expect(document.body.textContent).not.toMatch(/Not started|In progress/)
        },
    )

    it("counts mixed statuses and collapses without hiding the summary", () => {
        renderQuestDetail(withStatuses(["completed", "active", "failed", null]))

        expect(stageButton()).toHaveTextContent("Shown objectives: 1 of 4 complete")
        expect(screen.getByText("Active")).toBeInTheDocument()
        expect(screen.getByText("No status recorded")).toBeInTheDocument()

        fireEvent.click(stageButton())
        expect(stageButton()).toHaveAttribute("aria-expanded", "false")
        expect(screen.getByText("Shown objectives: 1 of 4 complete.")).not.toBeVisible()
        expect(stageButton()).toHaveTextContent("Shown objectives: 1 of 4 complete")
    })

    it("says no objectives are shown when none are returned", () => {
        renderQuestDetail(withStatuses([]))

        expect(stageButton()).toHaveTextContent("No objectives shown")
        expect(screen.getByText("No objectives shown.")).toBeVisible()
        expect(screen.getByText("No objectives are shown for this stage.")).toBeVisible()
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
                "No objectives are shown for this stage.",
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

describe("QuestDetailPage — audience preview (Phase 13E-B manual-acceptance fix)", () => {
    it("shows 'Preview as member' locked to this quest for a GM/admin membership", () => {
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
                <MemoryRouter initialEntries={["/app/test-campaign/quests/quest-a"]}>
                    <Routes>
                        <Route
                            path="/app/:campaignId/quests/:questId"
                            element={<QuestDetailPage campaignId="test-campaign" quest={questFixture} />}
                        />
                    </Routes>
                </MemoryRouter>
            </SessionContext.Provider>,
        )

        fireEvent.click(screen.getByRole("button", { name: "Preview as member" }))

        // No ResourceTargetSelector for the quest itself -- it is already
        // fixed to the quest this page is showing.
        expect(screen.queryByLabelText("Quest")).not.toBeInTheDocument()
        expect(screen.getByText(questFixture.name, { selector: "strong" })).toBeInTheDocument()
    })

    it("does not show 'Preview as member' without access.manage", () => {
        renderQuestDetail(questFixture)

        expect(
            screen.queryByRole("button", { name: "Preview as member" }),
        ).not.toBeInTheDocument()
    })
})
