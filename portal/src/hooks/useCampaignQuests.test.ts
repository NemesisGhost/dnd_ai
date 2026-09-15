import {
    act,
    renderHook,
    waitFor,
} from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import {
    QuestRequestError,
} from "../api/quests"
import type {
    CampaignQuestListItem,
} from "../types/quest"
import { useCampaignQuests } from "./useCampaignQuests"

const {
    fetchCampaignQuestsMock,
    reloadMock,
} = vi.hoisted(() => ({
    fetchCampaignQuestsMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock(
    "../api/quests",
    async (importOriginal) => {
        const actual =
            await importOriginal<
                typeof import("../api/quests")
            >()

        return {
            ...actual,
            fetchCampaignQuests:
                fetchCampaignQuestsMock,
        }
    },
)

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        reload: reloadMock,
    }),
}))

const firstPerspectiveQuests = [
    {
        quest_id: "quest-a",
        name: "Restore the Lens Array",
        status_code: "active",
    },
] satisfies CampaignQuestListItem[]

const secondPerspectiveQuests = [
    {
        quest_id: "quest-b",
        name: "Recover the Missing Key",
        status_code: "discovered",
    },
] satisfies CampaignQuestListItem[]

beforeEach(() => {
    fetchCampaignQuestsMock.mockReset()
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

describe("useCampaignQuests", () => {
    it("loads the authorized quest list", async () => {
        fetchCampaignQuestsMock.mockResolvedValue(
            firstPerspectiveQuests,
        )

        const { result } = renderHook(() =>
            useCampaignQuests(
                "campaign-a",
                "character-a",
            ),
        )

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                quests: firstPerspectiveQuests,
            })
        })

        expect(
            fetchCampaignQuestsMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "character-a",
            expect.any(AbortSignal),
        )
    })

    it.each([403, 404])(
        "treats HTTP %s as unavailable",
        async (status) => {
            fetchCampaignQuestsMock.mockRejectedValue(
                new QuestRequestError(status),
            )

            const { result } = renderHook(() =>
                useCampaignQuests(
                    "campaign-a",
                    "character-a",
                ),
            )

            await waitFor(() => {
                expect(result.current.state).toEqual({
                    status: "unavailable",
                })
            })
        },
    )

    it("reloads the browser session after an unauthorized response", async () => {
        fetchCampaignQuestsMock.mockRejectedValue(
            new QuestRequestError(401),
        )

        const { result } = renderHook(() =>
            useCampaignQuests(
                "campaign-a",
                "character-a",
            ),
        )

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })
    })

    it("returns a recoverable error for other failures", async () => {
        const requestError = new Error(
            "The quest service is unavailable",
        )

        fetchCampaignQuestsMock.mockRejectedValue(
            requestError,
        )

        const { result } = renderHook(() =>
            useCampaignQuests(
                "campaign-a",
                "character-a",
            ),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "error",
                error: requestError,
            })
        })
    })

    it("retries the quest-list request", async () => {
        const requestError = new Error(
            "The quest service is unavailable",
        )

        fetchCampaignQuestsMock
            .mockRejectedValueOnce(requestError)
            .mockResolvedValueOnce(
                firstPerspectiveQuests,
            )

        const { result } = renderHook(() =>
            useCampaignQuests(
                "campaign-a",
                "character-a",
            ),
        )

        await waitFor(() => {
            expect(result.current.state.status).toBe(
                "error",
            )
        })

        act(() => {
            result.current.retry()
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                quests: firstPerspectiveQuests,
            })
        })

        expect(
            fetchCampaignQuestsMock,
        ).toHaveBeenCalledTimes(2)
    })

    it("hides the previous quest list while a new perspective loads", async () => {
        let resolveSecondRequest:
            | ((
                quests: CampaignQuestListItem[],
            ) => void)
            | undefined

        const secondRequest =
            new Promise<CampaignQuestListItem[]>(
                (resolve) => {
                    resolveSecondRequest = resolve
                },
            )

        fetchCampaignQuestsMock
            .mockResolvedValueOnce(
                firstPerspectiveQuests,
            )
            .mockReturnValueOnce(secondRequest)

        const { result, rerender } = renderHook(
            ({ characterId }) =>
                useCampaignQuests(
                    "campaign-a",
                    characterId,
                ),
            {
                initialProps: {
                    characterId: "character-a",
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                quests: firstPerspectiveQuests,
            })
        })

        const firstSignal =
            fetchCampaignQuestsMock.mock
                .calls[0]?.[2] as AbortSignal

        rerender({
            characterId: "character-b",
        })

        expect(firstSignal.aborted).toBe(true)

        expect(result.current.state).toEqual({
            status: "loading",
        })

        act(() => {
            resolveSecondRequest?.(
                secondPerspectiveQuests,
            )
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                quests: secondPerspectiveQuests,
            })
        })
    })

    it("aborts the request when the hook unmounts", () => {
        fetchCampaignQuestsMock.mockReturnValue(
            new Promise<CampaignQuestListItem[]>(
                () => { },
            ),
        )

        const { unmount } = renderHook(() =>
            useCampaignQuests(
                "campaign-a",
                "character-a",
            ),
        )

        const signal =
            fetchCampaignQuestsMock.mock
                .calls[0]?.[2] as AbortSignal

        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})