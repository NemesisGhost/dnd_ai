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
    KnowledgeRequestError,
} from "../api/knowledge"
import type {
    KnowledgePage,
    KnowledgeView,
} from "../types/knowledge"
import { useKnowledgeItems } from "./useKnowledgeItems"

const {
    fetchKnowledgeItemsMock,
    reloadMock,
} = vi.hoisted(() => ({
    fetchKnowledgeItemsMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock(
    "../api/knowledge",
    async (importOriginal) => {
        const actual =
            await importOriginal<
                typeof import("../api/knowledge")
            >()

        return {
            ...actual,
            fetchKnowledgeItems:
                fetchKnowledgeItemsMock,
        }
    },
)

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        reload: reloadMock,
    }),
}))

const firstPage = {
    items: [
        {
            knowledge_item_id: "knowledge-a",
            knowledge_type_code: "fact",
            statement:
                "The Glass Ossuary lies beneath the Rootspire.",
            truth_status_code: null,
            sensitivity: null,
            awareness_level: "known",
            confidence: 95,
            willing_to_share: true,
            scope: "party",
            discovery_world_time_id: "world-time-a",
            source_event_id: "event-a",
            source_interaction_id: null,
            subject_entity_id: "location-a",
        },
    ],
    next_cursor: "next-knowledge-page",
} satisfies KnowledgePage

const secondPage = {
    items: [
        {
            knowledge_item_id: "knowledge-b",
            knowledge_type_code: "rumor",
            statement:
                "The Drowned Shard may open the western vault.",
            truth_status_code: null,
            sensitivity: null,
            awareness_level: "rumor",
            confidence: 40,
            willing_to_share: null,
            scope: "party",
            discovery_world_time_id: null,
            source_event_id: null,
            source_interaction_id: null,
            subject_entity_id: null,
        },
    ],
    next_cursor: null,
} satisfies KnowledgePage

interface HookProps {
    campaignId: string
    view: KnowledgeView
    characterId: string | null
    partyId: string | null
    query: string
    knowledgeType: string | null
    cursor: string | null
}

const initialProps: HookProps = {
    campaignId: "campaign-a",
    view: "known",
    characterId: "character-a",
    partyId: "party-a",
    query: "",
    knowledgeType: null,
    cursor: null,
}

beforeEach(() => {
    fetchKnowledgeItemsMock.mockReset()
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

describe("useKnowledgeItems", () => {
    it("loads an authorized knowledge page", async () => {
        fetchKnowledgeItemsMock.mockResolvedValue(
            firstPage,
        )

        const { result } = renderHook(() =>
            useKnowledgeItems(
                "campaign-a",
                "known",
                "character-a",
                "party-a",
                "glass",
                "fact",
            ),
        )

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                page: firstPage,
            })
        })

        expect(
            fetchKnowledgeItemsMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            {
                view: "known",
                characterId: "character-a",
                partyId: "party-a",
                query: "glass",
                knowledgeType: "fact",
                cursor: null,
            },
            expect.any(AbortSignal),
        )
    })

    it.each([403, 404])(
        "treats HTTP %s as unavailable",
        async (status) => {
            fetchKnowledgeItemsMock.mockRejectedValue(
                new KnowledgeRequestError(status),
            )

            const { result } = renderHook(() =>
                useKnowledgeItems(
                    "campaign-a",
                    "known",
                    "character-a",
                    "party-a",
                    "",
                    null,
                ),
            )

            await waitFor(() => {
                expect(result.current.state).toEqual({
                    status: "unavailable",
                })
            })
        },
    )

    it("reloads the session after an unauthorized response", async () => {
        fetchKnowledgeItemsMock.mockRejectedValue(
            new KnowledgeRequestError(401),
        )

        const { result } = renderHook(() =>
            useKnowledgeItems(
                "campaign-a",
                "known",
                "character-a",
                "party-a",
                "",
                null,
            ),
        )

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })
    })

    it("returns a recoverable state for other failures", async () => {
        const requestError = new Error(
            "Internal database information",
        )

        fetchKnowledgeItemsMock.mockRejectedValue(
            requestError,
        )

        const { result } = renderHook(() =>
            useKnowledgeItems(
                "campaign-a",
                "known",
                "character-a",
                "party-a",
                "",
                null,
            ),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "error",
                error: requestError,
            })
        })
    })

    it("retries a failed request", async () => {
        const requestError = new Error(
            "Knowledge service unavailable",
        )

        fetchKnowledgeItemsMock
            .mockRejectedValueOnce(requestError)
            .mockResolvedValueOnce(firstPage)

        const { result } = renderHook(() =>
            useKnowledgeItems(
                "campaign-a",
                "known",
                "character-a",
                "party-a",
                "",
                null,
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
                page: firstPage,
            })
        })

        expect(
            fetchKnowledgeItemsMock,
        ).toHaveBeenCalledTimes(2)
    })

    it("retains the previous page while refreshing within the same authorization scope", async () => {
        let resolveSecondRequest:
            | ((page: KnowledgePage) => void)
            | undefined

        const pendingSecondRequest =
            new Promise<KnowledgePage>((resolve) => {
                resolveSecondRequest = resolve
            })

        fetchKnowledgeItemsMock
            .mockResolvedValueOnce(firstPage)
            .mockReturnValueOnce(
                pendingSecondRequest,
            )

        const { result, rerender } = renderHook(
            ({
                campaignId,
                view,
                characterId,
                partyId,
                query,
                knowledgeType,
                cursor,
            }: HookProps) =>
                useKnowledgeItems(
                    campaignId,
                    view,
                    characterId,
                    partyId,
                    query,
                    knowledgeType,
                    cursor,
                ),
            {
                initialProps,
            },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                page: firstPage,
            })
        })

        const firstSignal =
            fetchKnowledgeItemsMock.mock
                .calls[0]?.[2] as AbortSignal

        rerender({
            ...initialProps,
            query: "shard",
            knowledgeType: "rumor",
            cursor: "next-knowledge-page",
        })

        expect(firstSignal.aborted).toBe(true)

        expect(result.current.state).toEqual({
            status: "refreshing",
            page: firstPage,
        })

        expect(
            fetchKnowledgeItemsMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            {
                view: "known",
                characterId: "character-a",
                partyId: "party-a",
                query: "shard",
                knowledgeType: "rumor",
                cursor: "next-knowledge-page",
            },
            expect.any(AbortSignal),
        )

        act(() => {
            if (resolveSecondRequest === undefined) {
                throw new Error(
                    "The second request was not started",
                )
            }

            resolveSecondRequest(secondPage)
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                page: secondPage,
            })
        })
    })

    it("clears the previous page immediately when the view changes", async () => {
        fetchKnowledgeItemsMock.mockResolvedValueOnce(
            firstPage,
        )

        const { result, rerender } = renderHook(
            ({ view }: { view: KnowledgeView }) =>
                useKnowledgeItems(
                    "campaign-a",
                    view,
                    "character-a",
                    "party-a",
                    "",
                    null,
                ),
            {
                initialProps: {
                    view: "known" as KnowledgeView,
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                page: firstPage,
            })
        })

        fetchKnowledgeItemsMock.mockReturnValueOnce(
            new Promise<KnowledgePage>(() => { }),
        )

        rerender({
            view: "character_private",
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })
    })

    it("clears the previous page immediately when the character changes", async () => {
        fetchKnowledgeItemsMock.mockResolvedValueOnce(
            firstPage,
        )

        const { result, rerender } = renderHook(
            ({
                characterId,
            }: {
                characterId: string | null
            }) =>
                useKnowledgeItems(
                    "campaign-a",
                    "known",
                    characterId,
                    "party-a",
                    "",
                    null,
                ),
            {
                initialProps: {
                    characterId:
                        "character-a" as string | null,
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state.status).toBe(
                "success",
            )
        })

        fetchKnowledgeItemsMock.mockReturnValueOnce(
            new Promise<KnowledgePage>(() => { }),
        )

        rerender({
            characterId: "character-b",
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })
    })

    it("clears the previous page immediately when the party changes", async () => {
        fetchKnowledgeItemsMock.mockResolvedValueOnce(
            firstPage,
        )

        const { result, rerender } = renderHook(
            ({
                partyId,
            }: {
                partyId: string | null
            }) =>
                useKnowledgeItems(
                    "campaign-a",
                    "known",
                    "character-a",
                    partyId,
                    "",
                    null,
                ),
            {
                initialProps: {
                    partyId: "party-a" as string | null,
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state.status).toBe(
                "success",
            )
        })

        fetchKnowledgeItemsMock.mockReturnValueOnce(
            new Promise<KnowledgePage>(() => { }),
        )

        rerender({
            partyId: "party-b",
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })
    })

    it("clears the previous page immediately when the campaign changes", async () => {
        fetchKnowledgeItemsMock.mockResolvedValueOnce(
            firstPage,
        )

        const { result, rerender } = renderHook(
            ({ campaignId }: { campaignId: string }) =>
                useKnowledgeItems(
                    campaignId,
                    "known",
                    "character-a",
                    "party-a",
                    "",
                    null,
                ),
            {
                initialProps: {
                    campaignId: "campaign-a",
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state.status).toBe(
                "success",
            )
        })

        fetchKnowledgeItemsMock.mockReturnValueOnce(
            new Promise<KnowledgePage>(() => { }),
        )

        rerender({
            campaignId: "campaign-b",
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })
    })

    it("discards a retained page when a refresh fails", async () => {
        fetchKnowledgeItemsMock.mockResolvedValueOnce(
            firstPage,
        )

        const { result, rerender } = renderHook(
            ({ query }: { query: string }) =>
                useKnowledgeItems(
                    "campaign-a",
                    "known",
                    "character-a",
                    "party-a",
                    query,
                    null,
                ),
            {
                initialProps: {
                    query: "",
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                page: firstPage,
            })
        })

        fetchKnowledgeItemsMock.mockRejectedValueOnce(
            new KnowledgeRequestError(404),
        )

        rerender({
            query: "missing",
        })

        expect(result.current.state).toEqual({
            status: "refreshing",
            page: firstPage,
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "unavailable",
            })
        })
    })

    it("clears a retained page on a 401 before reloading the session", async () => {
        fetchKnowledgeItemsMock.mockResolvedValueOnce(
            firstPage,
        )

        const { result, rerender } = renderHook(
            ({ query }: { query: string }) =>
                useKnowledgeItems(
                    "campaign-a",
                    "known",
                    "character-a",
                    "party-a",
                    query,
                    null,
                ),
            {
                initialProps: {
                    query: "",
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                page: firstPage,
            })
        })

        fetchKnowledgeItemsMock.mockRejectedValueOnce(
            new KnowledgeRequestError(401),
        )

        rerender({
            query: "expired",
        })

        expect(result.current.state).toEqual({
            status: "refreshing",
            page: firstPage,
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "loading",
            })
        })

        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("aborts the active request when the hook unmounts", () => {
        fetchKnowledgeItemsMock.mockReturnValue(
            new Promise<KnowledgePage>(() => { }),
        )

        const { unmount } = renderHook(() =>
            useKnowledgeItems(
                "campaign-a",
                "known",
                "character-a",
                "party-a",
                "",
                null,
            ),
        )

        const signal =
            fetchKnowledgeItemsMock.mock
                .calls[0]?.[2] as AbortSignal

        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})