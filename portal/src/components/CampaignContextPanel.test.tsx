import {
  fireEvent,
  render,
  screen,
} from "@testing-library/react"
import type { ComponentProps } from "react"
import { MemoryRouter } from "react-router"
import {
  describe,
  expect,
  it,
  vi,
} from "vitest"
import {
  CharacterPerspectiveContext,
} from "../context/CharacterPerspectiveContext"
import type {
  CampaignContext,
} from "../types/bootstrap"
import {
  CampaignContextPanel,
} from "./CampaignContextPanel"

const baseCampaign = {
  campaign_id: "campaign-secret-id",
  campaign_name: "Mundivita",
  timeline_id: "timeline-secret-id",
  timeline_name: "Primary Timeline",
  roles: ["campaign_owner"],
  character_perspectives: [
    {
      character_id: "character-a",
      character_name: "Ixamarra",
    },
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
    <MemoryRouter>
      <CharacterPerspectiveContext.Provider
        value={{
          getSelectedCharacterId: () =>
            selectedCharacterId,
          selectCharacter,
        }}
      >
        <CampaignContextPanel
          campaign={campaign}
          {...overrides}
        />
      </CharacterPerspectiveContext.Provider>
    </MemoryRouter>,
  )
}

describe("CampaignContextPanel", () => {
  it("renders the campaign and timeline dimensions", () => {
    renderPanel(baseCampaign)

    expect(
      screen.getByText("Campaign"),
    ).toBeInTheDocument()

    expect(
      screen.getAllByText("Mundivita").length,
    ).toBeGreaterThan(0)

    expect(
      screen.getByText("Timeline"),
    ).toBeInTheDocument()

    expect(
      screen.getByText("Primary Timeline"),
    ).toBeInTheDocument()

    expect(
      screen.queryByText("World"),
    ).not.toBeInTheDocument()

    expect(
      screen.queryByText("Time"),
    ).not.toBeInTheDocument()
  })

  it("uses neutral wording when no timeline is selected", () => {
    renderPanel({
      ...baseCampaign,
      timeline_id: null,
      timeline_name: null,
    })

    expect(
      screen.getByText("Timeline"),
    ).toBeInTheDocument()

    expect(
      screen.getByText("No timeline selected"),
    ).toBeInTheDocument()
  })

  it("renders World and Time when real values are supplied", () => {
    renderPanel(baseCampaign, {
      worldName: "Mundus",
      currentWorldTime: "Year 998, Spring",
    })

    expect(
      screen.getByText("World"),
    ).toBeInTheDocument()

    expect(
      screen.getByText("Mundus"),
    ).toBeInTheDocument()

    expect(
      screen.getByText("Time"),
    ).toBeInTheDocument()

    expect(
      screen.getByText("Year 998, Spring"),
    ).toBeInTheDocument()
  })

  it("labels and displays the selected character perspective", () => {
    renderPanel(
      baseCampaign,
      {},
      "character-a",
    )

    expect(
      screen.getByText("Viewing as"),
    ).toBeInTheDocument()

    const selector = screen.getByRole(
      "combobox",
      {
        name: "Character perspective",
      },
    )

    expect(selector).toHaveValue("character-a")
  })

  it("delegates character selection to the shared perspective callback", () => {
    const selectCharacter = vi.fn()

    renderPanel(
      baseCampaign,
      {},
      null,
      selectCharacter,
    )

    const selector = screen.getByRole(
      "combobox",
      {
        name: "Character perspective",
      },
    )

    fireEvent.change(selector, {
      target: {
        value: "character-a",
      },
    })

    expect(selectCharacter).toHaveBeenCalledWith(
      "campaign-secret-id",
      "character-a",
    )
  })

  it("links to the campaign-selection page", () => {
    renderPanel(baseCampaign)

    expect(
      screen.getByRole("link", {
        name: "Change campaign",
      }),
    ).toHaveAttribute("href", "/campaigns")
  })

  it("exposes a labeled native disclosure control", () => {
    renderPanel(
      baseCampaign,
      {},
      "character-a",
    )

    const disclosure = screen.getByText(
      "Campaign context: Mundivita — Viewing as Ixamarra",
      {
        selector: "summary",
      },
    )

    expect(
      disclosure.closest("details"),
    ).toHaveAttribute("open")
  })

  it("never displays raw campaign, timeline, or character IDs", () => {
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