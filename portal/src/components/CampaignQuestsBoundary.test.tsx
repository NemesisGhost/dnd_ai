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
    CampaignQuestListItem,
} from "../types/quest"
import {
    CampaignQuestsBoundary,
} from "./CampaignQuestsBoundary"

const {
    retryMock,
    useCampaignQuestsMock,
} = vi.hoisted(() => ({
    retryMock: vi.fn(),
    useCampaignQuestsMock: vi.fn(),
}))

vi.mock("../hooks/useCampaignQuests", () => ({
    useCampaignQuests: useCampaignQuestsMock,
}))

const questListFixture = [
    {
        quest_id: "quest-a",
        name: "Restore the Lens Array",
        status_code: "active",
    },
    {
        quest_id: "quest-b",
        name: "Recover the Missing Key",
        status_code: null,
    },
] satisfies CampaignQuestListItem[]

function renderBoundary() {
    render(
        <CampaignQuestsBoundary
            campaignId="campaign-a"
            characterId="character-a"
        >
            {(quests) => (
                <ul>
                    {quests.map((quest) => (
                        <li key={quest.quest_id}>
                            {quest.name}
                        </li>
                    ))}
                </ul>
            )}
        </CampaignQuestsBoundary>,
    )
}

beforeEach(() => {
    retryMock.mockReset()
    useCampaignQuestsMock.mockReset()
})

describe("CampaignQuestsBoundary", () => {
    it("shows loading without rendering quest content", () => {
        useCampaignQuestsMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Loading quests",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(
                "Restore the Lens Array",
            ),
        ).not.toBeInTheDocument()

        expect(
            useCampaignQuestsMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "character-a",
        )
    })

    it("shows a non-disclosing unavailable state", () => {
        useCampaignQuestsMock.mockReturnValue({
            state: {
                status: "unavailable",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Quests unavailable",
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

        useCampaignQuestsMock.mockReturnValue({
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

    it("renders the authorized quest list after a successful request", () => {
        useCampaignQuestsMock.mockReturnValue({
            state: {
                status: "success",
                quests: questListFixture,
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
            screen.getByText(
                "Recover the Missing Key",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("button", {
                name: "Try again",
            }),
        ).not.toBeInTheDocument()
    })
})