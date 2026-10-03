import { fireEvent, render, screen, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AudiencePreviewPanel } from "./AudiencePreviewPanel"

const { audiencePreviewStateRef, questsStateRef } = vi.hoisted(() => ({
    audiencePreviewStateRef: { current: { status: "loading" } as Record<string, unknown> },
    questsStateRef: { current: { status: "loading" } as Record<string, unknown> },
}))

vi.mock("../hooks/useAudiencePreview", () => ({
    useAudiencePreview: () => ({ state: audiencePreviewStateRef.current, retry: vi.fn() }),
}))

vi.mock("../hooks/useCampaignQuests", () => ({
    useCampaignQuests: () => ({ state: questsStateRef.current, retry: vi.fn() }),
}))

const members = [
    { campaign_membership_id: "membership-a", display_name: "Player One" },
    { campaign_membership_id: "membership-b", display_name: "Player Two" },
]

function resultContainer(): HTMLElement | null {
    return document.querySelector(".audience-preview-panel__result")
}

beforeEach(() => {
    audiencePreviewStateRef.current = { status: "loading" }
    questsStateRef.current = {
        status: "success",
        quests: [{ quest_id: "quest-1", name: "Find the Amulet", status_code: "active" }],
    }
})

describe("AudiencePreviewPanel", () => {
    it("does not show the selection form until opened", () => {
        render(<AudiencePreviewPanel campaignId="campaign-1" members={members} />)

        expect(screen.queryByLabelText("Member")).not.toBeInTheDocument()
    })

    it("does not fetch a preview until both a member and a resource are selected", () => {
        render(<AudiencePreviewPanel campaignId="campaign-1" members={members} />)

        fireEvent.click(screen.getByRole("button", { name: "Preview as member" }))

        expect(screen.getByLabelText("Member")).toBeInTheDocument()
        expect(screen.queryByText(/Loading preview/)).not.toBeInTheDocument()
    })

    it("shows the rendered preview once a member and resource are both selected", () => {
        audiencePreviewStateRef.current = {
            status: "success",
            result: {
                resourceType: "quest",
                quest: {
                    quest_id: "quest-1",
                    name: "Find the Amulet",
                    status_code: "active",
                    stages: [],
                },
            },
        }

        render(<AudiencePreviewPanel campaignId="campaign-1" members={members} />)

        fireEvent.click(screen.getByRole("button", { name: "Preview as member" }))
        fireEvent.change(screen.getByLabelText("Member"), {
            target: { value: "membership-a" },
        })

        const target = screen.getByText(/Previewing quest/)
        expect(target).toBeInTheDocument()
        expect(within(target).getByText("Player One")).toBeInTheDocument()
        expect(within(resultContainer() as HTMLElement).getByText("Find the Amulet")).toBeInTheDocument()
    })

    it("clears the preview when the member selection is reset", () => {
        audiencePreviewStateRef.current = {
            status: "success",
            result: {
                resourceType: "quest",
                quest: {
                    quest_id: "quest-1",
                    name: "Find the Amulet",
                    status_code: "active",
                    stages: [],
                },
            },
        }

        render(<AudiencePreviewPanel campaignId="campaign-1" members={members} />)

        fireEvent.click(screen.getByRole("button", { name: "Preview as member" }))
        fireEvent.change(screen.getByLabelText("Member"), {
            target: { value: "membership-a" },
        })
        expect(resultContainer()).not.toBeNull()

        fireEvent.change(screen.getByLabelText("Member"), { target: { value: "" } })
        expect(resultContainer()).toBeNull()
    })

    it("clears its content when the disclosure closes", () => {
        audiencePreviewStateRef.current = {
            status: "success",
            result: {
                resourceType: "quest",
                quest: {
                    quest_id: "quest-1",
                    name: "Find the Amulet",
                    status_code: "active",
                    stages: [],
                },
            },
        }

        render(<AudiencePreviewPanel campaignId="campaign-1" members={members} />)

        fireEvent.click(screen.getByRole("button", { name: "Preview as member" }))
        fireEvent.change(screen.getByLabelText("Member"), {
            target: { value: "membership-a" },
        })
        expect(resultContainer()).not.toBeNull()

        fireEvent.click(screen.getByRole("button", { name: "Hide audience preview" }))
        expect(resultContainer()).toBeNull()
    })

    it("hides the resource-type selector and locks it when fixedResourceType is set", () => {
        render(
            <AudiencePreviewPanel
                campaignId="campaign-1"
                members={members}
                fixedResourceType="quest"
            />,
        )

        fireEvent.click(screen.getByRole("button", { name: "Preview as member" }))

        expect(screen.queryByLabelText("Resource type")).not.toBeInTheDocument()
    })

    it("hides the resource picker and previews the fixed resource once a member is selected", () => {
        audiencePreviewStateRef.current = {
            status: "success",
            result: {
                resourceType: "knowledge_item",
                knowledgeItem: {
                    statement: "The Glass Ossuary lies beneath the Rootspire.",
                    truth_status_code: null,
                    confidence: null,
                },
            },
        }

        render(
            <AudiencePreviewPanel
                campaignId="campaign-1"
                members={members}
                fixedResourceType="knowledge_item"
                fixedResource={{ id: "knowledge-1", display_name: "The Glass Ossuary" }}
            />,
        )

        fireEvent.click(screen.getByRole("button", { name: "Preview as member" }))

        expect(screen.queryByLabelText("Knowledge item")).not.toBeInTheDocument()
        expect(screen.getByText("The Glass Ossuary")).toBeInTheDocument()

        fireEvent.change(screen.getByLabelText("Member"), {
            target: { value: "membership-a" },
        })

        expect(
            screen.getByText("The Glass Ossuary lies beneath the Rootspire."),
        ).toBeInTheDocument()
    })
})
