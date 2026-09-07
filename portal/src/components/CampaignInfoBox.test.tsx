import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { CampaignContext } from "../types/bootstrap"
import { CampaignInfoBox } from "./CampaignInfoBox"

const baseCampaign = {
  campaign_id: "campaign-secret-id",
  campaign_name: "Mundivita",
  timeline_id: "timeline-secret-id",
  timeline_name: "Primary Timeline",
  roles: ["campaign_owner", "player"],
  character_perspectives: [
    { character_id: "character-a", character_name: "Ixamarra" },
  ],
  selected_character_id: "character-a",
  capabilities: ["access.manage"],
} satisfies CampaignContext

function renderCampaignInfoBox(campaign: CampaignContext) {
  return render(
    <MemoryRouter>
      <CampaignInfoBox campaign={campaign} />
    </MemoryRouter>,
  )
}

describe("CampaignInfoBox", () => {
  it("maps the campaign name, timeline, roles, and character perspectives", () => {
    renderCampaignInfoBox(baseCampaign)

    expect(
      screen.getByRole("heading", { name: "Mundivita" }),
    ).toBeInTheDocument()
    expect(screen.getByText("Primary Timeline")).toBeInTheDocument()
    expect(
      screen.getByText("campaign_owner, player"),
    ).toBeInTheDocument()
    expect(screen.getByText("Ixamarra")).toBeInTheDocument()
  })

  it("links to the campaign's characters page without exposing the raw campaign id as text", () => {
    renderCampaignInfoBox(baseCampaign)

    expect(
      screen.getByRole("link", { name: "View characters" }),
    ).toHaveAttribute(
      "href",
      "/app/campaign-secret-id/characters",
    )
    expect(
      screen.queryByText("campaign-secret-id"),
    ).not.toBeInTheDocument()
  })

  it("falls back to neutral wording for a missing timeline or roles", () => {
    renderCampaignInfoBox({
      ...baseCampaign,
      timeline_name: null,
      roles: [],
      character_perspectives: [],
    })

    expect(screen.getAllByText("Not available")).toHaveLength(3)
  })

  it("never displays raw entity ids or capability/authorization grants", () => {
    renderCampaignInfoBox(baseCampaign)

    expect(
      screen.queryByText("timeline-secret-id"),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText("character-a"),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText("access.manage"),
    ).not.toBeInTheDocument()
  })
})
