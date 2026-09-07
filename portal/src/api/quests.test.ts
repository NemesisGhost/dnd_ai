import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type {
    CampaignQuestListItem,
    QuestDetail,
} from "../types/quest"
import {
    fetchCampaignQuests,
    fetchQuest,
    QuestRequestError,
} from "./quests"

const questListFixture = [
    {
        quest_id: "quest-a",
        name: "Restore the Lens Array",
        status_code: "active",
    },
    {
        quest_id: "quest-b",
        name: "Enter the God-Heart Forge",
        status_code: null,
    },
] satisfies CampaignQuestListItem[]

const questDetailFixture = {
    quest_id: "quest-a",
    name: "Restore the Lens Array",
    status_code: "active",
    stages: [
        {
            quest_stage_id: "stage-a",
            name: "Restore Balance",
            description:
                "Repair the systems that regulate the facility.",
            sequence_number: 1,
            stage_type: "sequential",
            objectives: [
                {
                    quest_objective_id: "objective-a",
                    name: "Align the lens pylons",
                    description:
                        "Rotate each pylon into its balanced position.",
                    requirement_level: "required",
                    completion_mode: "all",
                    visibility_policy: "visible",
                    quantity_required: 4,
                    status_code: "active",
                },
            ],
        },
    ],
} satisfies QuestDetail

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchCampaignQuests", () => {
    it("returns the authorized quest list for a character perspective", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify(questListFixture),
                {
                    status: 200,
                    headers: {
                        "Content-Type": "application/json",
                    },
                },
            ),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchCampaignQuests(
                "campaign/a b",
                "character/c d",
                controller.signal,
            ),
        ).resolves.toEqual(questListFixture)

        expect(fetchMock).toHaveBeenCalledTimes(1)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/quests?character_id=character%2Fc+d",
            {
                method: "GET",
                headers: {
                    Accept: "application/json",
                },
                cache: "no-store",
                signal: controller.signal,
            },
        )
    })

    it("omits the perspective parameter and returns an empty list when no character is selected", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify([]), {
                status: 200,
                headers: {
                    "Content-Type": "application/json",
                },
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchCampaignQuests(
                "campaign-a",
                null,
            ),
        ).resolves.toEqual([])

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/quests",
            {
                method: "GET",
                headers: {
                    Accept: "application/json",
                },
                cache: "no-store",
                signal: undefined,
            },
        )
    })

    it("throws a typed error for an unsuccessful list response", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(null, {
                status: 403,
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        const request = fetchCampaignQuests(
            "campaign-a",
            null,
        )

        await expect(request).rejects.toBeInstanceOf(
            QuestRequestError,
        )

        await expect(request).rejects.toMatchObject({
            name: "QuestRequestError",
            status: 403,
            message:
                "Quest request failed with status 403",
        })
    })
})

describe("fetchQuest", () => {
    it("returns authorized quest detail for a character perspective", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify(questDetailFixture),
                {
                    status: 200,
                    headers: {
                        "Content-Type": "application/json",
                    },
                },
            ),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchQuest(
                "campaign/a b",
                "quest/e f",
                "character/c d",
                controller.signal,
            ),
        ).resolves.toEqual(questDetailFixture)

        expect(fetchMock).toHaveBeenCalledTimes(1)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/quests/quest%2Fe%20f?character_id=character%2Fc+d",
            {
                method: "GET",
                headers: {
                    Accept: "application/json",
                },
                cache: "no-store",
                signal: controller.signal,
            },
        )
    })

    it("throws the same typed error for a missing or inaccessible quest", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(null, {
                status: 404,
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        const request = fetchQuest(
            "campaign-a",
            "unavailable-quest",
            null,
        )

        await expect(request).rejects.toBeInstanceOf(
            QuestRequestError,
        )

        await expect(request).rejects.toMatchObject({
            name: "QuestRequestError",
            status: 404,
            message:
                "Quest request failed with status 404",
        })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/quests/unavailable-quest",
            expect.objectContaining({
                cache: "no-store",
            }),
        )
    })
})