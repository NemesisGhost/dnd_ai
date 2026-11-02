import type { ReactNode } from "react"
import {
    MemoryRouter,
    Route,
    Routes,
} from "react-router"
import { fireEvent, render, screen } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import {
    CharacterPerspectiveContext,
} from "../context/CharacterPerspectiveContext"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { AuthorizedParty } from "../types/bootstrap"
import type { CampaignQuestListItem } from "../types/quest"
import { CampaignQuestDetailPage } from "./CampaignQuestDetailPage"
import { CampaignQuestsPage } from "./CampaignQuestsPage"

const { listBoundarySpy, detailBoundarySpy } = vi.hoisted(() => ({
    listBoundarySpy: vi.fn(),
    detailBoundarySpy: vi.fn(),
}))

const listedQuests: CampaignQuestListItem[] = [
    { quest_id: "quest-one", name: "Restore the Lens Array", status_code: "active" },
]

vi.mock(
    "../components/CampaignQuestsBoundary",
    () => ({
        CampaignQuestsBoundary: ({
            campaignId,
            characterId,
            partyId,
            children,
        }: {
            campaignId: string
            characterId: string | null
            partyId?: string | null
            children: (quests: CampaignQuestListItem[]) => ReactNode
        }) => {
            listBoundarySpy(campaignId, characterId, partyId ?? null)
            return children(listedQuests)
        },
    }),
)

vi.mock(
    "../components/QuestDetailBoundary",
    () => ({
        QuestDetailBoundary: ({
            campaignId,
            questId,
            characterId,
            partyId,
        }: {
            campaignId: string
            questId: string
            characterId: string | null
            partyId?: string | null
        }) => {
            detailBoundarySpy(campaignId, questId, characterId, partyId ?? null)
            return <p>Quest boundary rendered</p>
        },
    }),
)

vi.mock("../hooks/useAccessOverview", () => ({
    useAccessOverview: () => ({ state: { status: "loading" }, retry: vi.fn() }),
}))

const partyA: AuthorizedParty = { party_id: "party-a", party_name: "The Adventuring Party" }
const partyB: AuthorizedParty = { party_id: "party-b", party_name: "The Merchant Council" }

beforeEach(() => {
    listBoundarySpy.mockClear()
    detailBoundarySpy.mockClear()
})

interface CampaignOptions {
    // Fields of the route campaign's own bootstrap entry (e.g. current_time_set, capabilities).
    own?: Record<string, unknown>
    // Other campaigns in the same bootstrap, to prove the route campaign's metadata is the one read.
    others?: Record<string, unknown>[]
}

function sessionWithParties(parties: Record<string, AuthorizedParty[]>, options: CampaignOptions = {}) {
    return {
        state: {
            status: "authenticated" as const,
            bootstrap: {
                ...sessionBootstrapFixture,
                campaigns: [
                    {
                        ...sessionBootstrapFixture.campaigns[0],
                        campaign_id: "campaign-one",
                        capabilities: ["campaign.view"],
                        character_perspectives: Object.entries(parties).map(
                            ([characterId, authorizedParties]) => ({
                                character_id: characterId,
                                character_name: characterId,
                                authorized_parties: authorizedParties,
                            }),
                        ),
                        ...options.own,
                    },
                    ...(options.others ?? []).map((other) => ({
                        ...sessionBootstrapFixture.campaigns[0],
                        character_perspectives: [],
                        ...other,
                    })),
                ],
            },
        },
        reload: vi.fn(),
        refresh: vi.fn(),
    }
}

function renderQuests(
    characterId: string | null,
    parties: Record<string, AuthorizedParty[]>,
    initialEntry = "/app/campaign-one/quests",
    options: CampaignOptions = {},
) {
    const getSelectedCharacterId = vi.fn(() => characterId)
    const perspective = { getSelectedCharacterId, selectCharacter: vi.fn() }
    const session = sessionWithParties(parties, options)

    function tree(entry: string, key?: string) {
        return (
            <SessionContext.Provider value={session}>
                <CharacterPerspectiveContext.Provider value={perspective}>
                    <MemoryRouter key={key} initialEntries={[entry]}>
                        <Routes>
                            <Route
                                path="/app/:campaignId/quests"
                                element={<CampaignQuestsPage />}
                            />
                            <Route
                                path="/app/:campaignId/quests/:questId"
                                element={<CampaignQuestDetailPage />}
                            />
                            <Route path="/quests" element={<CampaignQuestsPage />} />
                        </Routes>
                    </MemoryRouter>
                </CharacterPerspectiveContext.Provider>
            </SessionContext.Provider>
        )
    }

    const view = render(tree(initialEntry))
    return { ...view, getSelectedCharacterId, tree }
}

function partySelect() {
    return screen.getByRole("combobox", { name: "Party" })
}

function questLink() {
    return screen.getByRole("link", { name: /Restore the Lens Array/ })
}

describe("CampaignQuestsPage", () => {
    it("sends no party when the character has no authorized party", () => {
        const { getSelectedCharacterId } = renderQuests("character-one", {
            "character-one": [],
        })

        expect(getSelectedCharacterId).toHaveBeenCalledWith("campaign-one")
        expect(listBoundarySpy).toHaveBeenLastCalledWith(
            "campaign-one",
            "character-one",
            null,
        )
        expect(partySelect()).toBeDisabled()
        expect(questLink()).toHaveAttribute("href", "/app/campaign-one/quests/quest-one")
    })

    it("sends the character's only authorized party with its character", () => {
        renderQuests("character-one", { "character-one": [partyA] })

        expect(listBoundarySpy).toHaveBeenLastCalledWith(
            "campaign-one",
            "character-one",
            "party-a",
        )
        expect(partySelect()).toHaveValue("party-a")
        expect(questLink()).toHaveAttribute(
            "href",
            "/app/campaign-one/quests/quest-one?character_id=character-one&party_id=party-a",
        )
    })

    it("never guesses among several authorized parties, and sends the one the user picks", () => {
        renderQuests("character-one", { "character-one": [partyA, partyB] })

        expect(listBoundarySpy).toHaveBeenLastCalledWith(
            "campaign-one",
            "character-one",
            null,
        )
        expect(partySelect()).toHaveValue("")

        fireEvent.change(partySelect(), { target: { value: "party-b" } })

        expect(listBoundarySpy).toHaveBeenLastCalledWith(
            "campaign-one",
            "character-one",
            "party-b",
        )
        expect(questLink()).toHaveAttribute(
            "href",
            "/app/campaign-one/quests/quest-one?character_id=character-one&party_id=party-b",
        )
    })

    it("keeps the same party perspective from the list into the quest detail", () => {
        renderQuests("character-one", { "character-one": [partyA, partyB] })

        fireEvent.change(partySelect(), { target: { value: "party-b" } })
        fireEvent.click(questLink())

        expect(screen.getByText("Quest boundary rendered")).toBeInTheDocument()
        expect(detailBoundarySpy).toHaveBeenLastCalledWith(
            "campaign-one",
            "quest-one",
            "character-one",
            "party-b",
        )
    })

    it("ignores a URL party that belongs to another character or is not authorized", () => {
        const { getSelectedCharacterId, rerender, tree } = renderQuests(
            "character-two",
            { "character-one": [partyA, partyB], "character-two": [partyA, partyB] },
            "/app/campaign-one/quests?character_id=character-one&party_id=party-b",
        )

        // Picked for character-one; character-two is now selected.
        expect(listBoundarySpy).toHaveBeenLastCalledWith(
            "campaign-one",
            "character-two",
            null,
        )

        getSelectedCharacterId.mockReturnValue("character-one")
        rerender(
            tree(
                "/app/campaign-one/quests?character_id=character-one&party_id=party-unknown",
                "unauthorized",
            ),
        )

        expect(listBoundarySpy).toHaveBeenLastCalledWith(
            "campaign-one",
            "character-one",
            null,
        )
    })

    it("resets the party when the selected character changes", () => {
        const { getSelectedCharacterId, rerender, tree } = renderQuests(
            "character-one",
            { "character-one": [partyA, partyB], "character-two": [partyB] },
        )

        fireEvent.change(partySelect(), { target: { value: "party-a" } })
        expect(listBoundarySpy).toHaveBeenLastCalledWith(
            "campaign-one",
            "character-one",
            "party-a",
        )

        getSelectedCharacterId.mockReturnValue("character-two")
        rerender(
            tree("/app/campaign-one/quests?character_id=character-one&party_id=party-a"),
        )

        // party-a is not character-two's; its only party is derived instead.
        expect(listBoundarySpy).toHaveBeenLastCalledWith(
            "campaign-one",
            "character-two",
            "party-b",
        )
    })

    it("passes a null perspective without a selected character", () => {
        renderQuests(null, { "character-one": [partyA] })

        expect(listBoundarySpy).toHaveBeenLastCalledWith("campaign-one", null, null)
        expect(screen.queryByRole("combobox", { name: "Party" })).not.toBeInTheDocument()
    })

    it("does not request quests without a campaign ID", () => {
        const { getSelectedCharacterId } = renderQuests(
            "character-one",
            { "character-one": [partyA] },
            "/quests",
        )

        expect(
            screen.getByRole("heading", {
                name: "Quests unavailable",
            }),
        ).toBeInTheDocument()

        expect(getSelectedCharacterId).not.toHaveBeenCalled()
        expect(listBoundarySpy).not.toHaveBeenCalled()
    })
})

describe("CampaignQuestsPage party selector without an effective clock", () => {
    const NOTICE = /Party membership cannot be determined because the campaign time has not been set/

    it("says party membership is undetermined, not that no party is available", () => {
        renderQuests("character-one", { "character-one": [] }, undefined, {
            own: { current_time_set: false },
        })

        expect(partySelect()).toBeDisabled()
        expect(screen.getByRole("option", { name: "Party membership undetermined" })).toBeInTheDocument()
        expect(screen.queryByRole("option", { name: "No party available" })).toBeNull()
        expect(screen.getByText(NOTICE)).toBeInTheDocument()
        // Authorization filtering is untouched: nothing is invented, nothing is sent.
        expect(screen.getAllByRole("option").filter((o) => partySelect().contains(o))).toHaveLength(1)
        expect(listBoundarySpy).toHaveBeenLastCalledWith("campaign-one", "character-one", null)
        // Campaign-wide quests still list.
        expect(questLink()).toBeInTheDocument()
    })

    it("offers Campaign Home only to a user who can edit canon", () => {
        const { unmount } = renderQuests("character-one", { "character-one": [] }, undefined, {
            own: { current_time_set: false },
        })
        expect(screen.queryByRole("link", { name: /Set the campaign time/ })).toBeNull()
        unmount()

        renderQuests("character-one", { "character-one": [] }, undefined, {
            own: { current_time_set: false, capabilities: ["campaign.view", "canon.edit"] },
        })
        expect(screen.getByRole("link", { name: /Set the campaign time/ })).toHaveAttribute(
            "href",
            "/app/campaign-one",
        )
    })

    it("keeps the ordinary empty wording when the clock is set", () => {
        renderQuests("character-one", { "character-one": [] }, undefined, {
            own: { current_time_set: true },
        })
        expect(screen.getByRole("option", { name: "No party available" })).toBeInTheDocument()
        expect(screen.queryByText(NOTICE)).toBeNull()
    })

    it("treats a payload without current_time_set as unknown, not as a missing clock", () => {
        renderQuests("character-one", { "character-one": [] })
        expect(screen.getByRole("option", { name: "No party available" })).toBeInTheDocument()
        expect(screen.queryByText(NOTICE)).toBeNull()
    })

    it("reads the route campaign's own entry, not another campaign's", () => {
        renderQuests("character-one", { "character-one": [] }, undefined, {
            own: { current_time_set: true },
            others: [{ campaign_id: "campaign-two", current_time_set: false }],
        })
        expect(screen.getByRole("option", { name: "No party available" })).toBeInTheDocument()
        expect(screen.queryByText(NOTICE)).toBeNull()
    })

    it("lists the authorized parties as usual when the clock is set", () => {
        renderQuests("character-one", { "character-one": [partyA, partyB] }, undefined, {
            own: { current_time_set: true },
        })
        expect(partySelect()).toBeEnabled()
        expect(screen.queryByText(NOTICE)).toBeNull()
    })

    it("shows no party selector, and no notice, without a selected character", () => {
        renderQuests(null, { "character-one": [] }, undefined, { own: { current_time_set: false } })
        expect(screen.queryByRole("combobox", { name: "Party" })).toBeNull()
        expect(screen.queryByText(NOTICE)).toBeNull()
    })
})
