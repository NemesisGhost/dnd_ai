import {
  render,
  screen,
  within,
} from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { CampaignsPage } from "./CampaignsPage"

const fixtureCampaign =
  sessionBootstrapFixture.campaigns[0]

if (fixtureCampaign === undefined) {
  throw new Error(
    "The session bootstrap fixture must contain a campaign",
  )
}

describe("CampaignsPage", () => {
  it("shows an empty state when the user has no campaigns", () => {
    render(
      <MemoryRouter>
        <CampaignsPage
          bootstrap={{
            ...sessionBootstrapFixture,
            is_platform_administrator: false,
            startup_campaign_id: null,
            campaign_preferences: {
              startup_mode: "resume_last_visited",
              preferred_campaign_id: null,
              last_visited_campaign_id: null,
            },
            campaigns: [],
          }}
        />
      </MemoryRouter>,
    )

    expect(
      screen.getByRole("heading", {
        name: "Campaigns",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByText(
        "You do not have access to any campaigns yet. Ask a GM to grant you access.",
      ),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole("link"),
    ).not.toBeInTheDocument()
  })

  it("lists an authorized campaign as a link", () => {
    render(
      <MemoryRouter>
        <CampaignsPage
          bootstrap={sessionBootstrapFixture}
        />
      </MemoryRouter>,
    )

    const link = screen.getByRole("link", {
      name: /Mundivita/,
    })

    expect(link).toHaveAttribute(
      "href",
      "/app/mundivita/home",
    )

    expect(
      within(link).getByRole("heading", {
        name: "Mundivita",
      }),
    ).toBeInTheDocument()

    expect(
      within(link).getByText("Primary Timeline"),
    ).toBeInTheDocument()

    expect(
      within(link).queryByText("Opens at sign-in"),
    ).not.toBeInTheDocument()
  })

  it("marks the campaign that opens at sign-in and the last visited one", () => {
    const second = {
      ...fixtureCampaign,
      campaign_id: "second",
      campaign_name: "Second",
    }
    render(
      <MemoryRouter>
        <CampaignsPage
          bootstrap={{
            ...sessionBootstrapFixture,
            campaign_preferences: {
              startup_mode: "preferred_campaign",
              preferred_campaign_id: "mundivita",
              last_visited_campaign_id: "second",
            },
            campaigns: [fixtureCampaign, second],
          }}
        />
      </MemoryRouter>,
    )

    expect(
      within(screen.getByRole("link", { name: /Mundivita/ })).getByText(
        "Opens at sign-in",
      ),
    ).toBeInTheDocument()
    expect(
      within(screen.getByRole("link", { name: /Second/ })).getByText(
        "Last visited",
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText("Default campaign")).not.toBeInTheDocument()
  })

  it("handles a campaign without a timeline", () => {
    render(
      <MemoryRouter>
        <CampaignsPage
          bootstrap={{
            ...sessionBootstrapFixture,
            is_platform_administrator: false,
            startup_campaign_id: null,
            campaign_preferences: {
              startup_mode: "resume_last_visited",
              preferred_campaign_id: null,
              last_visited_campaign_id: null,
            },
            campaigns: [
              {
                ...fixtureCampaign,
                timeline_id: null,
                timeline_name: null,
              },
            ],
          }}
        />
      </MemoryRouter>,
    )

    const link = screen.getByRole("link", {
      name: /Mundivita/,
    })

    expect(
      within(link).getByText("No timeline selected"),
    ).toBeInTheDocument()

    expect(
      within(link).queryByText("Opens at sign-in"),
    ).not.toBeInTheDocument()
  })
})