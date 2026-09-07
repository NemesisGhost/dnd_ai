import { fireEvent, render, screen } from "@testing-library/react"
import type { ComponentProps } from "react"
import { describe, expect, it, vi } from "vitest"
import { CharacterPerspectiveContext } from "../context/CharacterPerspectiveContext"
import type { CampaignContext } from "../types/bootstrap"
import { CampaignContextPanel } from "./CampaignContextPanel"

const baseCampaign = {
  campaign_id: "campaign-secret-id",
  campaign_name: "Mundivita",
  timeline_id: "timeline-secret-id",
  timeline_name: "Primary Timeline",
  roles: ["campaign_owner"],
  character_perspectives: [
    { character_id: "character-a", character_name: "Ixamarra" },
  ],
  selected_character_id: "character-a",
  capabilities: [],
} satisfies CampaignContext

function renderPanel(
  campaign: CampaignContext,
  overrides: Partial<
    ComponentProps<typeof CampaignContextPanel>
  > = {},
  selectedCharacterId: string | null = null,
  selectCharacter = vi.fn(),
) {
  return render(
    <CharacterPerspectiveContext.Provider
      value={{
        getSelectedCharacterId: () => selectedCharacterId,
        selectCharacter,
      }}
    >
      <CampaignContextPanel campaign={campaign} {...overrides} />
    </CharacterPerspectiveContext.Provider>,
  )
}

describe("CampaignContextPanel", () => {
  it("renders the campaign dimension and omits World and Time when not supplied", () => {
    renderPanel(baseCampaign)

    expect(screen.getByText("Campaign")).toBeInTheDocument()
    expect(screen.getAllByText("Mundivita").length).toBeGreaterThan(0)
    expect(screen.queryByText("World")).not.toBeInTheDocument()
    expect(screen.queryByText("Time")).not.toBeInTheDocument()
  })

  it("renders World and Time when real values are supplied", () => {
    renderPanel(baseCampaign, {
      worldName: "Mundus",
      currentWorldTime: "Year 998, Spring",
    })

    expect(screen.getByText("World")).toBeInTheDocument()
    expect(screen.getByText("Mundus")).toBeInTheDocument()
    expect(screen.getByText("Time")).toBeInTheDocument()
    expect(screen.getByText("Year 998, Spring")).toBeInTheDocument()
  })

  it("labels the perspective dimension 'Viewing as' and reuses the perspective selector", () => {
    renderPanel(baseCampaign, {}, "character-a")

    expect(screen.getByText("Viewing as")).toBeInTheDocument()

    const selector = screen.getByRole("combobox", {
      name: "Character perspective",
    })
    expect(selector).toHaveValue("character-a")
  })

  it("delegates character selection to the shared perspective callback contract", () => {
    const selectCharacter = vi.fn()
    renderPanel(baseCampaign, {}, null, selectCharacter)

    const selector = screen.getByRole("combobox", {
      name: "Character perspective",
    })

    fireEvent.change(selector, { target: { value: "character-a" } })

    expect(selectCharacter).toHaveBeenCalledWith(
      "campaign-secret-id",
      "character-a",
    )
  })

  it("exposes a labeled, native disclosure control for narrow screens", () => {
    renderPanel(baseCampaign, {}, "character-a")

    const disclosure = screen.getByText(
      "Campaign context: Mundivita — Viewing as Ixamarra",
      { selector: "summary" },
    )
    expect(disclosure.closest("details")).toHaveAttribute("open")
  })

  it("never displays raw campaign, timeline, or character ids", () => {
    renderPanel(baseCampaign)

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
