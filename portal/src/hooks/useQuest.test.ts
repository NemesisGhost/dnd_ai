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
    QuestDetail,
} from "../types/quest"
import { useQuest } from "./useQuest"

const {
    fetchQuestMock,
    reloadMock,
} = vi.hoisted(() => ({
    fetchQuestMock: vi.fn(),
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
            fetchQuest: fetchQuestMock,
        }
    },
)

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        reload: reloadMock,
    }),
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

const secondQuestFixture: QuestDetail = {
    ...questFixture,
    quest_id: "quest-b",
    name: "Recover the Missing Key",
    stages: [],
}

const secondPerspectiveFixture: QuestDetail = {
    ...questFixture,
    stages: [
        {
            ...questFixture.stages[0],
            objectives: [],
        },
    ],
}

beforeEach(() => {
    fetchQuestMock.mockReset()
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

describe("useQuest", () => {
    it("loads authorized quest detail", async () => {
        fetchQuestMock.mockResolvedValue(
            questFixture,
        )

        const { result } = renderHook(() =>
            useQuest(
                "campaign-a",
                "quest-a",
                "character-a",
            ),
        )

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                quest: questFixture,
            })
        })

        expect(fetchQuestMock).toHaveBeenCalledWith(
            "campaign-a",
            "quest-a",
            "character-a",
            expect.any(AbortSignal),
        )
    })

    it.each([403, 404])(
        "treats HTTP %s as unavailable",
        async (status) => {
            fetchQuestMock.mockRejectedValue(
                new QuestRequestError(status),
            )

            const { result } = renderHook(() =>
                useQuest(
                    "campaign-a",
                    "quest-a",
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
        fetchQuestMock.mockRejectedValue(
            new QuestRequestError(401),
        )

        const { result } = renderHook(() =>
            useQuest(
                "campaign-a",
                "quest-a",
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

        fetchQuestMock.mockRejectedValue(
            requestError,
        )

        const { result } = renderHook(() =>
            useQuest(
                "campaign-a",
                "quest-a",
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

    it("retries the quest-detail request", async () => {
        const requestError = new Error(
            "The quest service is unavailable",
        )

        fetchQuestMock
            .mockRejectedValueOnce(requestError)
            .mockResolvedValueOnce(questFixture)

        const { result } = renderHook(() =>
            useQuest(
                "campaign-a",
                "quest-a",
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
                quest: questFixture,
            })
        })

        expect(fetchQuestMock).toHaveBeenCalledTimes(2)
    })

    it("hides the previous quest while another quest loads", async () => {
        let resolveSecondRequest:
            | ((quest: QuestDetail) => void)
            | undefined

        const secondRequest =
            new Promise<QuestDetail>((resolve) => {
                resolveSecondRequest = resolve
            })

        fetchQuestMock
            .mockResolvedValueOnce(questFixture)
            .mockReturnValueOnce(secondRequest)

        const { result, rerender } = renderHook(
            ({ questId }) =>
                useQuest(
                    "campaign-a",
                    questId,
                    "character-a",
                ),
            {
                initialProps: {
                    questId: "quest-a",
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                quest: questFixture,
            })
        })

        const firstSignal =
            fetchQuestMock.mock
                .calls[0]?.[3] as AbortSignal

        rerender({
            questId: "quest-b",
        })

        expect(firstSignal.aborted).toBe(true)

        expect(result.current.state).toEqual({
            status: "loading",
        })

        act(() => {
            resolveSecondRequest?.(
                secondQuestFixture,
            )
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                quest: secondQuestFixture,
            })
        })
    })

    it("hides the previous detail while another perspective loads", async () => {
        let resolveSecondRequest:
            | ((quest: QuestDetail) => void)
            | undefined

        const secondRequest =
            new Promise<QuestDetail>((resolve) => {
                resolveSecondRequest = resolve
            })

        fetchQuestMock
            .mockResolvedValueOnce(questFixture)
            .mockReturnValueOnce(secondRequest)

        const { result, rerender } = renderHook(
            ({ characterId }) =>
                useQuest(
                    "campaign-a",
                    "quest-a",
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
                quest: questFixture,
            })
        })

        const firstSignal =
            fetchQuestMock.mock
                .calls[0]?.[3] as AbortSignal

        rerender({
            characterId: "character-b",
        })

        expect(firstSignal.aborted).toBe(true)

        expect(result.current.state).toEqual({
            status: "loading",
        })

        act(() => {
            resolveSecondRequest?.(
                secondPerspectiveFixture,
            )
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                quest: secondPerspectiveFixture,
            })
        })
    })

    it("aborts the request when the hook unmounts", () => {
        fetchQuestMock.mockReturnValue(
            new Promise<QuestDetail>(() => { }),
        )

        const { unmount } = renderHook(() =>
            useQuest(
                "campaign-a",
                "quest-a",
                "character-a",
            ),
        )

        const signal =
            fetchQuestMock.mock
                .calls[0]?.[3] as AbortSignal

        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})