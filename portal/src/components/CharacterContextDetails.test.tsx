import { render, screen } from "@testing-library/react"
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest"
import type { CharacterDetail } from "../types/character"
import { CharacterContextDetails } from "./CharacterContextDetails"

const { useCharacterMock } = vi.hoisted(() => ({
  useCharacterMock: vi.fn(),
}))

vi.mock("../hooks/useCharacter", () => ({
  useCharacter: useCharacterMock,
}))

const baseCharacter: CharacterDetail = {
  character_id: "character-secret-id",
  name: "Ixamarra",
  species_code: "elf",
  size_category: "medium",
  current_hit_points: 9,
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

function renderDetails() {
  return render(
    <CharacterContextDetails
      campaignId="campaign-a"
      characterId="character-a"
    />,
  )
}

beforeEach(() => {
  useCharacterMock.mockReset()
})

describe("CharacterContextDetails", () => {
  it("requests the character it was asked for", () => {
    useCharacterMock.mockReturnValue({
      state: { status: "loading" },
      retry: vi.fn(),
    })

    renderDetails()

    expect(useCharacterMock).toHaveBeenCalledWith(
      "campaign-a",
      "character-a",
    )
    expect(screen.getByText("Loading character…")).toBeInTheDocument()
  })

  it("shows a compact unavailable note for a non-success state", () => {
    useCharacterMock.mockReturnValue({
      state: { status: "error", error: new Error("internal host down") },
      retry: vi.fn(),
    })

    renderDetails()

    expect(
      screen.getByText("Character details unavailable."),
    ).toBeInTheDocument()
    expect(
      screen.queryByText("internal host down"),
    ).not.toBeInTheDocument()
  })

  it("renders species and size, and no live-state rows when omitted", () => {
    useCharacterMock.mockReturnValue({
      state: {
        status: "success",
        character: {
          ...baseCharacter,
          conditions: null,
          resources: null,
        },
      },
      retry: vi.fn(),
    })

    renderDetails()

    expect(screen.getByText("Species")).toBeInTheDocument()
    expect(screen.getByText("elf")).toBeInTheDocument()
    expect(screen.getByText("Size")).toBeInTheDocument()
    expect(screen.queryByText("Hit points")).not.toBeInTheDocument()
  })

  it("renders live state, conditions, and resources when present", () => {
    useCharacterMock.mockReturnValue({
      state: {
        status: "success",
        character: {
          ...baseCharacter,
          conditions: [
            { condition_code: "poisoned", source_description: "giant spider" },
          ],
          resources: [
            {
              resource_code: "spell_slot_1",
              current_amount: 1,
              maximum_amount: 3,
            },
          ],
        },
      },
      retry: vi.fn(),
    })

    renderDetails()

    expect(
      screen.getByRole("meter", { name: "Hit points" }),
    ).toBeInTheDocument()
    expect(screen.getByText("poisoned")).toBeInTheDocument()
    expect(screen.getByText("giant spider")).toBeInTheDocument()
    expect(screen.getByText("spell_slot_1")).toBeInTheDocument()
    expect(screen.getByText("1 / 3")).toBeInTheDocument()
  })

  it("never renders the raw character id", () => {
    useCharacterMock.mockReturnValue({
      state: { status: "success", character: baseCharacter },
      retry: vi.fn(),
    })

    renderDetails()

    expect(
      screen.queryByText("character-secret-id"),
    ).not.toBeInTheDocument()
  })
})
