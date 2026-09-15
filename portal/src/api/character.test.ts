import { afterEach, describe, expect, it, vi } from "vitest"
import type { CharacterDetail } from "../types/character"
import {
  CharacterRequestError,
  fetchCharacter,
} from "./character"

const characterFixture: CharacterDetail = {
  character_id: "1",
  name: "Test Character",
  species_code: "human",
  size_category: "medium",
  current_hit_points: 10,
  maximum_hit_points: 10,
  temporary_hit_points: 0,
  exhaustion_level: 0,
  death_save_successes: 0,
  death_save_failures: 0,
  current_location_id: null,
  active_encounter_id: null,
  conditions: null,
  resources: null,
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("fetchCharacter", () => {
  it("returns character detail from a successful response", async () => {
    const controller = new AbortController()

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(characterFixture), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
        },
      }),
    )

    vi.stubGlobal("fetch", fetchMock)

    await expect(
      fetchCharacter("campaign/a b", "character:c d", controller.signal),
    ).resolves.toEqual(characterFixture)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/campaigns/campaign%2Fa%20b/characters/character%3Ac%20d",
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

  it("throws a typed error with HTTP status when the request fails", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, {
        status: 404,
      }),
    )

    vi.stubGlobal("fetch", fetchMock)

    const request = fetchCharacter("missing-campaign", "missing-character")

    await expect(request).rejects.toBeInstanceOf(CharacterRequestError)
    await expect(request).rejects.toMatchObject({
      name: "CharacterRequestError",
      status: 404,
      message: "Character request failed with status 404",
    })
  })

  it("preserves network failures for the caller to handle", async () => {
    const networkError = new TypeError("Failed to fetch")
    const fetchMock = vi.fn().mockRejectedValue(networkError)

    vi.stubGlobal("fetch", fetchMock)

    await expect(
      fetchCharacter("campaign-a", "character-a"),
    ).rejects.toBe(networkError)
  })

  it("forwards the provided abort signal to fetch", async () => {
    const controller = new AbortController()
    const abortError = new DOMException("The operation was aborted.", "AbortError")

    const fetchMock = vi.fn().mockRejectedValue(abortError)

    vi.stubGlobal("fetch", fetchMock)

    controller.abort()

    await expect(
      fetchCharacter("campaign-a", "character-a", controller.signal),
    ).rejects.toBe(abortError)

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/campaigns/campaign-a/characters/character-a",
      expect.objectContaining({
        signal: controller.signal,
      }),
    )
  })
})