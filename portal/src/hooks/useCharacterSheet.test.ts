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
    CharacterSheetRequestError,
} from "../api/characterSheet"
import { characterSheetFixture } from "../fixtures/characterSheet"
import type { CharacterSheet } from "../types/characterSheet"
import { useCharacterSheet } from "./useCharacterSheet"

const {
    fetchCharacterSheetMock,
    reloadMock,
} = vi.hoisted(() => ({
    fetchCharacterSheetMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock(
    "../api/characterSheet",
    async (importOriginal) => {
        const actual =
            await importOriginal<
                typeof import("../api/characterSheet")
            >()

        return {
            ...actual,
            fetchCharacterSheet:
                fetchCharacterSheetMock,
        }
    },
)

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        reload: reloadMock,
    }),
}))

const secondSheetFixture = {
    ...characterSheetFixture,
    character_id: "character-b",
    name: "Character B",
    character_build_id: "build-character-b",
    build_label: "Alternate Build",
} satisfies CharacterSheet

beforeEach(() => {
    fetchCharacterSheetMock.mockReset()
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

describe("useCharacterSheet", () => {
    it("loads an authorized character sheet", async () => {
        fetchCharacterSheetMock.mockResolvedValue(
            characterSheetFixture,
        )

        const { result } = renderHook(() =>
            useCharacterSheet(
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
                sheet: characterSheetFixture,
            })
        })

        expect(
            fetchCharacterSheetMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "character-a",
            expect.any(AbortSignal),
        )
    })

    it.each([403, 404])(
        "treats HTTP %s as unavailable",
        async (status) => {
            fetchCharacterSheetMock.mockRejectedValue(
                new CharacterSheetRequestError(
                    status,
                ),
            )

            const { result } = renderHook(() =>
                useCharacterSheet(
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

    it("reloads the session after an unauthorized response", async () => {
        fetchCharacterSheetMock.mockRejectedValue(
            new CharacterSheetRequestError(401),
        )

        const { result } = renderHook(() =>
            useCharacterSheet(
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
            "The character sheet service is unavailable",
        )

        fetchCharacterSheetMock.mockRejectedValue(
            requestError,
        )

        const { result } = renderHook(() =>
            useCharacterSheet(
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

    it("retries the character sheet request", async () => {
        const requestError = new Error(
            "The character sheet service is unavailable",
        )

        fetchCharacterSheetMock
            .mockRejectedValueOnce(requestError)
            .mockResolvedValueOnce(
                characterSheetFixture,
            )

        const { result } = renderHook(() =>
            useCharacterSheet(
                "campaign-a",
                "character-a",
            ),
        )

        await waitFor(() => {
            expect(
                result.current.state.status,
            ).toBe("error")
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
                sheet: characterSheetFixture,
            })
        })

        expect(
            fetchCharacterSheetMock,
        ).toHaveBeenCalledTimes(2)
    })

    it.each([
        {
            scope: "campaign",
            initialCampaignId: "campaign-a",
            initialCharacterId: "character-a",
            nextCampaignId: "campaign-b",
            nextCharacterId: "character-a",
        },
        {
            scope: "character",
            initialCampaignId: "campaign-a",
            initialCharacterId: "character-a",
            nextCampaignId: "campaign-a",
            nextCharacterId: "character-b",
        },
    ])(
        "hides the previous sheet while a new $scope scope loads",
        async ({
            initialCampaignId,
            initialCharacterId,
            nextCampaignId,
            nextCharacterId,
        }) => {
            let resolveSecondRequest:
                | ((
                    sheet: CharacterSheet,
                ) => void)
                | undefined

            const secondRequest =
                new Promise<CharacterSheet>(
                    (resolve) => {
                        resolveSecondRequest = resolve
                    },
                )

            fetchCharacterSheetMock
                .mockResolvedValueOnce(
                    characterSheetFixture,
                )
                .mockReturnValueOnce(secondRequest)

            const { result, rerender } =
                renderHook(
                    ({
                        campaignId,
                        characterId,
                    }) =>
                        useCharacterSheet(
                            campaignId,
                            characterId,
                        ),
                    {
                        initialProps: {
                            campaignId:
                                initialCampaignId,
                            characterId:
                                initialCharacterId,
                        },
                    },
                )

            await waitFor(() => {
                expect(
                    result.current.state,
                ).toEqual({
                    status: "success",
                    sheet: characterSheetFixture,
                })
            })

            const firstSignal =
                fetchCharacterSheetMock.mock
                    .calls[0]?.[2] as AbortSignal

            rerender({
                campaignId: nextCampaignId,
                characterId: nextCharacterId,
            })

            expect(firstSignal.aborted).toBe(true)

            expect(result.current.state).toEqual({
                status: "loading",
            })

            act(() => {
                resolveSecondRequest?.(
                    secondSheetFixture,
                )
            })

            await waitFor(() => {
                expect(
                    result.current.state,
                ).toEqual({
                    status: "success",
                    sheet: secondSheetFixture,
                })
            })
        },
    )

    it("aborts the request when the hook unmounts", () => {
        fetchCharacterSheetMock.mockReturnValue(
            new Promise<CharacterSheet>(() => { }),
        )

        const { unmount } = renderHook(() =>
            useCharacterSheet(
                "campaign-a",
                "character-a",
            ),
        )

        const signal =
            fetchCharacterSheetMock.mock
                .calls[0]?.[2] as AbortSignal

        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})