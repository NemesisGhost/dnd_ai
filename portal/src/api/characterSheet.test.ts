import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { characterSheetFixture } from "../fixtures/characterSheet"
import {
    CharacterSheetRequestError,
    fetchCharacterSheet,
} from "./characterSheet"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchCharacterSheet", () => {
    it("returns a character sheet from a successful response", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify(characterSheetFixture),
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
            fetchCharacterSheet(
                "campaign/a b",
                "character:c d",
                controller.signal,
            ),
        ).resolves.toEqual(characterSheetFixture)

        expect(fetchMock).toHaveBeenCalledTimes(1)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/characters/character%3Ac%20d/sheet",
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

    it("throws a typed error containing the HTTP status", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(null, {
                status: 404,
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        const request = fetchCharacterSheet(
            "missing-campaign",
            "missing-character",
        )

        await expect(request).rejects.toBeInstanceOf(
            CharacterSheetRequestError,
        )

        await expect(request).rejects.toMatchObject({
            name: "CharacterSheetRequestError",
            status: 404,
            message:
                "Character sheet request failed with status 404",
        })
    })

    it("preserves network failures for the caller", async () => {
        const networkError = new TypeError(
            "Failed to fetch",
        )

        const fetchMock = vi
            .fn()
            .mockRejectedValue(networkError)

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchCharacterSheet(
                "campaign-a",
                "character-a",
            ),
        ).rejects.toBe(networkError)
    })

    it("forwards the provided abort signal", async () => {
        const controller = new AbortController()

        const abortError = new DOMException(
            "The operation was aborted.",
            "AbortError",
        )

        const fetchMock = vi
            .fn()
            .mockRejectedValue(abortError)

        vi.stubGlobal("fetch", fetchMock)

        controller.abort()

        await expect(
            fetchCharacterSheet(
                "campaign-a",
                "character-a",
                controller.signal,
            ),
        ).rejects.toBe(abortError)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/characters/character-a/sheet",
            expect.objectContaining({
                signal: controller.signal,
            }),
        )
    })
})