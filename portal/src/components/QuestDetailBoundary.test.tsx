import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type {
    QuestDetail,
} from "../types/quest"
import {
    QuestDetailBoundary,
} from "./QuestDetailBoundary"

const {
    retryMock,
    useQuestMock,
} = vi.hoisted(() => ({
    retryMock: vi.fn(),
    useQuestMock: vi.fn(),
}))

vi.mock("../hooks/useQuest", () => ({
    useQuest: useQuestMock,
}))

const questFixture: QuestDetail = {
    quest_id: "quest-a",
    name: "Restore the Lens Array",
    status_code: "active",
    stages: [
        {
            quest_stage_id: "stage-a",
            name: "Restore Balance",
            description:
                "Repair the facility's balancing systems.",
            sequence_number: 1,
            stage_type: "sequential",
            objectives: [
                {
                    quest_objective_id: "objective-a",
                    name: "Align the lens pylons",
                    description:
                        "Rotate each pylon into position.",
                    requirement_level: "required",
                    completion_mode: "all",
                    visibility_policy: "visible",
                    quantity_required: 4,
                    status_code: "active",
                },
            ],
        },
    ],
}

function renderBoundary() {
    render(
        <QuestDetailBoundary
            campaignId="campaign-a"
            questId="quest-a"
            characterId="character-a"
        >
            {(quest) => (
                <p>{quest.name}</p>
            )}
        </QuestDetailBoundary>,
    )
}

beforeEach(() => {
    retryMock.mockReset()
    useQuestMock.mockReset()
})

describe("QuestDetailBoundary", () => {
    it("shows loading without rendering quest content", () => {
        useQuestMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Loading quest",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(
                "Restore the Lens Array",
            ),
        ).not.toBeInTheDocument()

        expect(useQuestMock).toHaveBeenCalledWith(
            "campaign-a",
            "quest-a",
            "character-a",
        )
    })

    it("shows a non-disclosing unavailable state", () => {
        useQuestMock.mockReturnValue({
            state: {
                status: "unavailable",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Quest unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "The requested quest information is not available.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(
                "Restore the Lens Array",
            ),
        ).not.toBeInTheDocument()
    })

    it("shows a safe recoverable error and retries", () => {
        const diagnosticError = new Error(
            "Database connection failed for internal host",
        )

        useQuestMock.mockReturnValue({
            state: {
                status: "error",
                error: diagnosticError,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Quest information unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(diagnosticError.message),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText(
                "Restore the Lens Array",
            ),
        ).not.toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Try again",
            }),
        )

        expect(retryMock).toHaveBeenCalledTimes(1)
    })

    it("renders authorized quest content after a successful request", () => {
        useQuestMock.mockReturnValue({
            state: {
                status: "success",
                quest: questFixture,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByText(
                "Restore the Lens Array",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("button", {
                name: "Try again",
            }),
        ).not.toBeInTheDocument()
    })
})