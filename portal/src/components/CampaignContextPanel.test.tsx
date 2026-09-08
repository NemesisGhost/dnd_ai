import { fireEvent, render, screen, within } from "@testing-library/react"
import type { ComponentProps } from "react"
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest"
import type { CampaignContext } from "../types/bootstrap"
import { CampaignContextPanel } from "./CampaignContextPanel"

const { useCharacterMock } = vi.hoisted(() => ({
  useCharacterMock: vi.fn(),
}))

vi.mock("../hooks/useCharacter", () => ({
  useCharacter: useCharacterMock,
}))

const baseCampaign = {
  campaign_id: "campaign-secret-id",
  campaign_name: "Mundivita",
  timeline_id: "timeline-secret-id",
  timeline_name: "Primary Timeline",
  roles: ["campaign_owner"],
  character_perspectives: [
    { character_id: "character-a", character_name: "Ixamarra" },
    { character_id: "character-b", character_name: "Corvane" },
  ],
  selected_character_id: "character-a",
  capabilities: [],
} satisfies CampaignContext

const otherCampaign = {
  ...baseCampaign,
  campaign_id: "campaign-other-id",
  campaign_name: "Second World",
  timeline_name: null,
} satisfies CampaignContext

function renderPanel(
  overrides: Partial<ComponentProps<typeof CampaignContextPanel>> = {},
) {
  const props: ComponentProps<typeof CampaignContextPanel> = {
    campaign: baseCampaign,
    campaigns: [baseCampaign, otherCampaign],
    selectedCharacterId: null,
    onSelectCampaign: vi.fn(),
    onSelectCharacter: vi.fn(),
    ...overrides,
  }

  return { props, ...render(<CampaignContextPanel {...props} />) }
}

beforeEach(() => {
  useCharacterMock.mockReset()
  useCharacterMock.mockReturnValue({
    state: { status: "unavailable" },
    retry: vi.fn(),
  })
})

describe("CampaignContextPanel", () => {
  it("renders the four hierarchy sections in order", () => {
    renderPanel()

    const headings = screen
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent)

    expect(headings).toEqual([
      "World",
      "Campaign",
      "Timeline",
      "Character",
    ])
  })

  it("shows World as a read-only value with no control", () => {
    renderPanel()

    const world = screen
      .getByRole("heading", { name: "World" })
      .closest("section") as HTMLElement

    expect(within(world).getByText("Not available")).toBeInTheDocument()
    expect(
      within(world).queryByRole("combobox"),
    ).not.toBeInTheDocument()
  })

  it("shows Timeline as a disabled control carrying the current value", () => {
    renderPanel()

    const timeline = screen.getByRole("combobox", { name: "Timeline" })
    expect(timeline).toBeDisabled()
    expect(timeline).toHaveTextContent("Primary Timeline")
  })

  it("shows the neutral timeline value when none is set", () => {
    renderPanel({ campaign: otherCampaign })

    expect(
      screen.getByRole("combobox", { name: "Timeline" }),
    ).toHaveTextContent("No timeline selected")
  })

  it("lists every campaign and reports a change", () => {
    const onSelectCampaign = vi.fn()
    renderPanel({ onSelectCampaign })

    const campaignSelect = screen.getByRole("combobox", {
      name: "Campaign",
    })
    expect(campaignSelect).toHaveValue("campaign-secret-id")
    expect(
      within(campaignSelect).getAllByRole("option"),
    ).toHaveLength(2)

    fireEvent.change(campaignSelect, {
      target: { value: "campaign-other-id" },
    })

    expect(onSelectCampaign).toHaveBeenCalledWith("campaign-other-id")
  })

  it("does not report a change when the current campaign is re-selected", () => {
    const onSelectCampaign = vi.fn()
    renderPanel({ onSelectCampaign })

    fireEvent.change(
      screen.getByRole("combobox", { name: "Campaign" }),
      { target: { value: "campaign-secret-id" } },
    )

    expect(onSelectCampaign).not.toHaveBeenCalled()
  })

  it("reflects the selected character and reports perspective changes", () => {
    const onSelectCharacter = vi.fn()
    renderPanel({
      selectedCharacterId: "character-a",
      onSelectCharacter,
    })

    const selector = screen.getByRole("combobox", {
      name: "Character perspective",
    })
    expect(selector).toHaveValue("character-a")

    fireEvent.change(selector, { target: { value: "character-b" } })
    expect(onSelectCharacter).toHaveBeenCalledWith("character-b")

    fireEvent.change(selector, { target: { value: "" } })
    expect(onSelectCharacter).toHaveBeenCalledWith(null)
  })

  it("renders character detail only when a character is selected", () => {
    useCharacterMock.mockReturnValue({
      state: {
        status: "success",
        character: {
          character_id: "character-a",
          name: "Ixamarra",
          species_code: "elf",
          size_category: "medium",
          current_hit_points: null,
          maximum_hit_points: null,
          temporary_hit_points: null,
          exhaustion_level: null,
          death_save_successes: null,
          death_save_failures: null,
          current_location_id: null,
          active_encounter_id: null,
          conditions: null,
          resources: null,
        },
      },
      retry: vi.fn(),
    })

    const { rerender, props } = renderPanel({
      selectedCharacterId: null,
    })
    expect(screen.queryByText("Species")).not.toBeInTheDocument()

    rerender(
      <CampaignContextPanel
        {...props}
        selectedCharacterId="character-a"
      />,
    )
    expect(screen.getByText("Species")).toBeInTheDocument()
    expect(useCharacterMock).toHaveBeenCalledWith(
      "campaign-secret-id",
      "character-a",
    )
  })

  it("keeps the disclosure summary and open state", () => {
    renderPanel({ selectedCharacterId: "character-a" })

    const summary = screen.getByText(
      "Campaign context: Mundivita — Viewing as Ixamarra",
      { selector: "summary" },
    )
    expect(summary.closest("details")).toHaveAttribute("open")
  })

  it("has no campaign-selection link and never shows raw ids", () => {
    renderPanel({ selectedCharacterId: "character-a" })

    expect(
      screen.queryByRole("link", { name: "Change campaign" }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText("campaign-secret-id"),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText("timeline-secret-id"),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText("character-a"),
    ).not.toBeInTheDocument()
  })
})
