import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { CharacterPerspectiveContext } from "../context/CharacterPerspectiveContext"
import type { CampaignContext } from "../types/bootstrap"
import { CampaignContextBar } from "./CampaignContextBar"

const mockCampaign = {
  campaign_id: "campaign-test",
  campaign_name: "Test Campaign",
  timeline_id: null,
  timeline_name: null,
  roles: [],
  character_perspectives: [],
  selected_character_id: null,
  capabilities: [],
} satisfies CampaignContext

describe("CampaignContextBar", () => {
  it("renders the campaign and empty context states", () => {
    render(
      <CharacterPerspectiveContext.Provider
        value={{
          getSelectedCharacterId: () => null,
          selectCharacter: vi.fn(),
        }}
      >
        <CampaignContextBar campaign={mockCampaign} />
      </CharacterPerspectiveContext.Provider>,
    )

    expect(
      screen.getByText("Test Campaign"),
    ).toBeInTheDocument()

    expect(
      screen.getByText("No timeline selected"),
    ).toBeInTheDocument()

    expect(
      screen.getByText("No role assigned"),
    ).toBeInTheDocument()

    expect(
      screen.getByText("No character selected"),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("combobox", {
        name: "Character perspective",
      }),
    ).toBeDisabled()
  })
})