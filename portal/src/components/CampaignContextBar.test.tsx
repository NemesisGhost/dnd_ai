import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { CampaignContextBar } from "./CampaignContextBar"
import type { CampaignContext } from "../types/bootstrap"

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
  it("renders the campaign and timeline status", () => {
    render(<CampaignContextBar campaign={mockCampaign} />)

    expect(screen.getByText("Test Campaign")).toBeTruthy()
    expect(screen.getByText("No timeline selected")).toBeTruthy()
    expect(screen.getByText("No role assigned")).toBeTruthy()
  })
})
