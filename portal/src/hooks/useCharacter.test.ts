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
import type { CharacterDetail } from "../types/character"
import { CharacterRequestError } from "../api/character"
import { useCharacter } from "./useCharacter"

const {
    fetchCharacterMock,
    reloadMock,
} = vi.hoisted(() => ({
    fetchCharacterMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock("../api/character", async (importOriginal) => {
    const actual =
        await importOriginal<
            typeof import("../api/character")
        >()

    return {
        ...actual,
        fetchCharacter: fetchCharacterMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        reload: reloadMock,
    }),
}))

const characterFixture: CharacterDetail = {
    character_id: "character-a",
    name: "Character A",
    species_code: "human",
    size_category: "medium",
    current_hit_points: 10,
    maximum_hit_points: 12,
    temporary_hit_points: 0,
    exhaustion_level: 0,
    death_save_successes: 0,
    death_save_failures: 0,
    current_location_id: null,
    active_encounter_id: null,
    conditions: [],
    resources: [],
}

const secondCharacterFixture: CharacterDetail = {
    ...characterFixture,
    character_id: "character-b",
    name: "Character B",
}

beforeEach(() => {
    fetchCharacterMock.mockReset()
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

describe("useCharacter", () => {
    it("loads an authorized character", async () => {
        fetchCharacterMock.mockResolvedValue(characterFixture)

        const { result } = renderHook(() =>
            useCharacter("campaign-a", "character-a"),
        )

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                character: characterFixture,
            })
        })

        expect(fetchCharacterMock).toHaveBeenCalledWith(
            "campaign-a",
            "character-a",
            expect.any(AbortSignal),
        )
    })

    it.each([403, 404])(
        "treats HTTP %s as unavailable",
        async (status) => {
            fetchCharacterMock.mockRejectedValue(
                new CharacterRequestError(status),
            )

            const { result } = renderHook(() =>
                useCharacter("campaign-a", "character-a"),
            )

            await waitFor(() => {
                expect(result.current.state).toEqual({
                    status: "unavailable",
                })
            })
        },
    )

    it("reloads the session after an unauthorized response", async () => {
        fetchCharacterMock.mockRejectedValue(
            new CharacterRequestError(401),
        )

        const { result } = renderHook(() =>
            useCharacter("campaign-a", "character-a"),
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
            "The character service is unavailable",
        )

        fetchCharacterMock.mockRejectedValue(requestError)

        const { result } = renderHook(() =>
            useCharacter("campaign-a", "character-a"),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "error",
                error: requestError,
            })
        })
    })

    it("retries the character request", async () => {
        const requestError = new Error(
            "The character service is unavailable",
        )

        fetchCharacterMock
            .mockRejectedValueOnce(requestError)
            .mockResolvedValueOnce(characterFixture)

        const { result } = renderHook(() =>
            useCharacter("campaign-a", "character-a"),
        )

        await waitFor(() => {
            expect(result.current.state.status).toBe("error")
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
                character: characterFixture,
            })
        })

        expect(fetchCharacterMock).toHaveBeenCalledTimes(2)
    })

    it("hides the previous character while a new character loads", async () => {
        let resolveSecondCharacter:
            | ((character: CharacterDetail) => void)
            | undefined

        const secondCharacterRequest =
            new Promise<CharacterDetail>((resolve) => {
                resolveSecondCharacter = resolve
            })

        fetchCharacterMock
            .mockResolvedValueOnce(characterFixture)
            .mockReturnValueOnce(secondCharacterRequest)

        const { result, rerender } = renderHook(
            ({ characterId }) =>
                useCharacter("campaign-a", characterId),
            {
                initialProps: {
                    characterId: "character-a",
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                character: characterFixture,
            })
        })

        const firstSignal =
            fetchCharacterMock.mock.calls[0]?.[2] as AbortSignal

        rerender({
            characterId: "character-b",
        })

        expect(firstSignal.aborted).toBe(true)
        expect(result.current.state).toEqual({
            status: "loading",
        })

        act(() => {
            resolveSecondCharacter?.(secondCharacterFixture)
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                character: secondCharacterFixture,
            })
        })
    })

    it("aborts the request when the hook unmounts", () => {
        fetchCharacterMock.mockReturnValue(
            new Promise<CharacterDetail>(() => { }),
        )

        const { unmount } = renderHook(() =>
            useCharacter("campaign-a", "character-a"),
        )

        const signal =
            fetchCharacterMock.mock.calls[0]?.[2] as AbortSignal

        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})