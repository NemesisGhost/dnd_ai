import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ResourceTargetSelector } from "./ResourceTargetSelector"

const { worldEntitiesStateRef, knowledgeStateRef, questsStateRef, sessionsStateRef } = vi.hoisted(
    () => ({
        worldEntitiesStateRef: { current: { status: "loading" } as Record<string, unknown> },
        knowledgeStateRef: { current: { status: "loading" } as Record<string, unknown> },
        questsStateRef: { current: { status: "loading" } as Record<string, unknown> },
        sessionsStateRef: { current: { status: "loading" } as Record<string, unknown> },
    }),
)

vi.mock("../hooks/useWorldEntities", () => ({
    useWorldEntities: () => ({ state: worldEntitiesStateRef.current, retry: vi.fn() }),
}))
vi.mock("../hooks/useKnowledgeItems", () => ({
    useKnowledgeItems: () => ({ state: knowledgeStateRef.current, retry: vi.fn() }),
}))
vi.mock("../hooks/useCampaignQuests", () => ({
    useCampaignQuests: () => ({ state: questsStateRef.current, retry: vi.fn() }),
}))
vi.mock("../hooks/useCampaignSessions", () => ({
    useCampaignSessions: () => ({ state: sessionsStateRef.current, retry: vi.fn() }),
}))

beforeEach(() => {
    worldEntitiesStateRef.current = { status: "loading" }
    knowledgeStateRef.current = { status: "loading" }
    questsStateRef.current = { status: "loading" }
    sessionsStateRef.current = { status: "loading" }
})

describe("ResourceTargetSelector", () => {
    it("renders the character list from assignableCharacters directly, no fetch", () => {
        const onChange = vi.fn()
        render(
            <ResourceTargetSelector
                campaignId="campaign-1"
                targetType="character"
                assignableCharacters={[
                    { character_id: "char-1", display_name: "Aria" },
                    { character_id: "char-2", display_name: "Bram" },
                ]}
                value="char-2"
                disabled={false}
                labelId="resource-label"
                onChange={onChange}
            />,
        )

        expect(screen.getByRole("option", { name: "Aria" })).toBeInTheDocument()
        expect(screen.getByRole("combobox")).toHaveValue("char-2")
    })

    it("filters entity results to location/organization/religion/item, excluding character/event", () => {
        worldEntitiesStateRef.current = {
            status: "success",
            page: {
                items: [
                    { entity_id: "loc-1", category: "location", name: "A Location" },
                    { entity_id: "char-1", category: "character", name: "A Character" },
                    { entity_id: "event-1", category: "event", name: "An Event" },
                    { entity_id: "item-1", category: "item", name: "An Item" },
                ],
                next_cursor: null,
            },
        }
        const onChange = vi.fn()
        render(
            <ResourceTargetSelector
                campaignId="campaign-1"
                targetType="entity"
                assignableCharacters={[]}
                value=""
                disabled={false}
                labelId="resource-label"
                onChange={onChange}
            />,
        )

        expect(screen.getByRole("option", { name: "A Location" })).toBeInTheDocument()
        expect(screen.getByRole("option", { name: "An Item" })).toBeInTheDocument()
        expect(screen.queryByRole("option", { name: "A Character" })).not.toBeInTheDocument()
        expect(screen.queryByRole("option", { name: "An Event" })).not.toBeInTheDocument()
    })

    it("auto-selects the first option once the list loads", () => {
        const onChange = vi.fn()
        const { rerender } = render(
            <ResourceTargetSelector
                campaignId="campaign-1"
                targetType="quest"
                assignableCharacters={[]}
                value=""
                disabled={false}
                labelId="resource-label"
                onChange={onChange}
            />,
        )
        expect(screen.getByText("Loading…")).toBeInTheDocument()

        questsStateRef.current = {
            status: "success",
            quests: [{ quest_id: "quest-1", name: "Find the Amulet", status_code: "active" }],
        }
        rerender(
            <ResourceTargetSelector
                campaignId="campaign-1"
                targetType="quest"
                assignableCharacters={[]}
                value=""
                disabled={false}
                labelId="resource-label"
                onChange={onChange}
            />,
        )

        expect(onChange).toHaveBeenCalledWith({ id: "quest-1", display_name: "Find the Amulet" })
    })

    it("renders session titles, falling back to a numbered label", () => {
        sessionsStateRef.current = {
            status: "success",
            sessions: [
                { session_id: "session-1", session_number: 3, title: null },
                { session_id: "session-2", session_number: 4, title: "The Ambush" },
            ],
        }
        render(
            <ResourceTargetSelector
                campaignId="campaign-1"
                targetType="session"
                assignableCharacters={[]}
                value="session-1"
                disabled={false}
                labelId="resource-label"
                onChange={vi.fn()}
            />,
        )

        expect(screen.getByRole("option", { name: "Session 3" })).toBeInTheDocument()
        expect(screen.getByRole("option", { name: "The Ambush" })).toBeInTheDocument()
    })

    it("lets the caller search knowledge items and passes the query through", () => {
        knowledgeStateRef.current = { status: "success", page: { items: [], next_cursor: null } }
        render(
            <ResourceTargetSelector
                campaignId="campaign-1"
                targetType="knowledge_item"
                assignableCharacters={[]}
                value=""
                disabled={false}
                labelId="resource-label"
                onChange={vi.fn()}
            />,
        )

        const searchBox = screen.getByLabelText("Search knowledge items")
        fireEvent.change(searchBox, { target: { value: "door" } })
        expect(searchBox).toHaveValue("door")
    })
})
