import { afterEach, describe, expect, it, vi } from "vitest"
import type { CharacterDetail } from "../types/character"
import { liveBody, MARKER_FIELDS, publicBody, RELEASED } from "../fixtures/publicCharacter"
import {
  CharacterContractError,
  CharacterRequestError,
  editorCharacterRead,
  fetchCharacter,
  isRunnableRead,
  normalizeCharacterRead,
} from "./character"

const characterFixture: CharacterDetail = {
  character_id: "1",
  name: "Test Character",
  character_kind: "character",
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
describe("normalizeCharacterRead", () => {
  const PUBLIC_KEYS = ["character_id", "character_kind", "name", "public_profile", "sections", "view_tier"]

  it("rebuilds the public tier from exactly the contracted keys (A4)", () => {
    const read = normalizeCharacterRead(publicBody({ ...MARKER_FIELDS, extra_key: "x" }))
    expect(Object.keys(read).sort()).toEqual(PUBLIC_KEYS)
    expect(Object.keys((read as { public_profile: object }).public_profile).sort()).toEqual([
      "appearance",
      "background",
      "size",
      "species",
      "summary",
    ])
    expect(JSON.stringify(read)).not.toMatch(/MARKER|777|888/)
  })

  it("keeps only code and label of a released species and size", () => {
    const read = normalizeCharacterRead(
      publicBody({ public_profile: { ...RELEASED, species: { code: "elf", label: "Elf", species_id: "SECRET" } } }),
    ) as { public_profile: { species: object } }
    expect(read.public_profile.species).toEqual({ code: "elf", label: "Elf" })
  })

  it("reads the section flags strictly, so only true offers a section", () => {
    const read = normalizeCharacterRead(publicBody({ sections: { details: true, inventory: "yes" } })) as unknown as {
      sections: Record<string, boolean>
    }
    expect(read.sections).toEqual({
      details: true,
      sheet: false,
      relationships: false,
      inventory: false,
      parties: false,
      public_profile: false,
    })
  })

  it("passes summary and full through, projecting the released profile and defaulting a missing one to null", () => {
    const full = normalizeCharacterRead(liveBody("full", { public_profile: { ...RELEASED, release_id: "r1" } })) as {
      public_profile: object
      species_code: string
    }
    expect(full.species_code).toBe("LIVE-SPECIES-MARKER")
    expect(Object.keys(full.public_profile).sort()).toEqual(["appearance", "background", "size", "species", "summary"])
    const bare = liveBody("summary") as Record<string, unknown>
    delete bare.public_profile
    expect((normalizeCharacterRead(bare) as { public_profile: unknown }).public_profile).toBeNull()
  })

  it.each([
    ["an unknown tier", publicBody({ view_tier: "everything" })],
    ["a null tier", publicBody({ view_tier: null })],
    ["a public tier without its profile", (() => { const b = publicBody() as Record<string, unknown>; delete b.public_profile; return b })()],
    ["a public tier with a non-object profile", publicBody({ public_profile: "text" })],
    ["a public tier with a malformed species", publicBody({ public_profile: { ...RELEASED, species: { code: 1 } } })],
    ["a public tier with a non-text summary", publicBody({ public_profile: { ...RELEASED, summary: 5 } })],
    ["a public tier without sections", publicBody({ sections: undefined })],
    ["a public tier without a name", publicBody({ name: undefined })],
    ["a public tier of an unknown kind", publicBody({ character_kind: "dragon" })],
    ["a summary tier without sections", liveBody("summary", { sections: undefined })],
    ["a full tier with a malformed profile", liveBody("full", { public_profile: { summary: 3 } })],
    ["a non-object body", "character"],
    ["an array body", []],
    ["a null body", null],
  ])("refuses %s", (_label, body) => {
    expect(() => normalizeCharacterRead(body)).toThrow(CharacterContractError)
  })

  describe("a body without view_tier (D-3)", () => {
    const legacy = () => ({ ...characterFixture }) as Record<string, unknown>

    it("is read as summary/full only when it is the recognized pre-tier shape", () => {
      expect(normalizeCharacterRead(legacy())).toEqual(characterFixture)
      expect(normalizeCharacterRead({ ...legacy(), sections: { details: true } })).toMatchObject({ character_id: "1" })
    })

    it("does not turn an incomplete public-shaped body into a legacy read", () => {
      const { view_tier: _tier, ...noTier } = publicBody() as Record<string, unknown>
      void _tier
      expect(() => normalizeCharacterRead(noTier)).toThrow(CharacterContractError)
      // Even with the live definition added, a body carrying a public profile has a tier or is refused.
      expect(() => normalizeCharacterRead({ ...legacy(), public_profile: RELEASED })).toThrow(CharacterContractError)
    })

    it.each([
      ["no species_code", "species_code"],
      ["no size_category", "size_category"],
      ["no conditions key", "conditions"],
      ["no resources key", "resources"],
      ["no name", "name"],
      ["no character_id", "character_id"],
      ["no character_kind", "character_kind"],
    ])("refuses a body with %s", (_label, key) => {
      const body = legacy()
      delete body[key]
      expect(() => normalizeCharacterRead(body)).toThrow(CharacterContractError)
    })

    it("refuses a body whose live-state keys are not arrays or null", () => {
      expect(() => normalizeCharacterRead({ ...legacy(), conditions: "none" })).toThrow(CharacterContractError)
    })
  })
})

describe("editorCharacterRead", () => {
  it("rebuilds the public tier and refuses an unknown or public-shaped body without a tier", () => {
    expect(editorCharacterRead(publicBody({ ...MARKER_FIELDS }))).toMatchObject({ view_tier: "public_profile" })
    expect(editorCharacterRead(publicBody({ view_tier: "everything" }))).toBeNull()
    const { view_tier: _tier, ...noTier } = publicBody() as Record<string, unknown>
    void _tier
    expect(editorCharacterRead(noTier)).toBeNull()
    expect(editorCharacterRead(publicBody({ public_profile: null }))).toBeNull()
    expect(editorCharacterRead(null)).toBeNull()
  })

  it("refuses an incomplete or contradictory body, with no permissive fallback (L-1)", () => {
    expect(editorCharacterRead({ character_id: "c1", name: "Aldric" })).toBeNull()
    expect(editorCharacterRead({ ...characterFixture, species_code: undefined })).toBeNull()
    expect(editorCharacterRead(liveBody("summary", { current_hit_points: 5 }))).toBeNull()
    expect(editorCharacterRead(liveBody("summary", { conditions: [] }))).toBeNull()
    expect(editorCharacterRead(liveBody("full", { sections: undefined }))).toBeNull()
  })

  it("accepts a valid full, summary and pre-tier body, projecting a released profile", () => {
    expect(editorCharacterRead({ ...characterFixture })).toEqual(characterFixture)
    expect(editorCharacterRead(liveBody("summary"))).toMatchObject({ view_tier: "summary" })
    expect(editorCharacterRead(liveBody("full", { public_profile: { ...RELEASED, x: 1 } }))).toMatchObject({
      public_profile: RELEASED,
    })
    expect(editorCharacterRead(liveBody("summary", { public_profile: { summary: 3 } }))).toBeNull()
  })
})

describe("isRunnableRead", () => {
  it("is true only for the full tier and a recognized pre-tier body", () => {
    expect(isRunnableRead(normalizeCharacterRead(liveBody("full")))).toBe(true)
    expect(isRunnableRead(normalizeCharacterRead({ ...characterFixture }))).toBe(true)
    expect(isRunnableRead(normalizeCharacterRead(liveBody("summary")))).toBe(false)
    expect(isRunnableRead(normalizeCharacterRead(publicBody()))).toBe(false)
  })
})

describe("normalizeCharacterRead: contradictory summary", () => {
  it.each([
    ["hit points", { current_hit_points: 3 }],
    ["a condition list", { conditions: [] }],
    ["a resource list", { resources: [{ resource_code: "x", current_amount: 1, maximum_amount: 2 }] }],
    ["a location", { current_location_id: "l1" }],
  ])("refuses a summary body carrying %s", (_label, extra) => {
    expect(() => normalizeCharacterRead(liveBody("summary", extra))).toThrow(CharacterContractError)
  })
})

describe("fetchCharacter tiers", () => {
  it("answers the normalized public tier and refuses an unrecognized 2xx body", async () => {
    const answer = (body: unknown) =>
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200 })))
    answer(publicBody({ ...MARKER_FIELDS }))
    const read = await fetchCharacter("c", "pc-1")
    expect(JSON.stringify(read)).not.toContain("MARKER")
    answer(publicBody({ view_tier: "everything" }))
    await expect(fetchCharacter("c", "pc-1")).rejects.toBeInstanceOf(CharacterContractError)
  })
})
