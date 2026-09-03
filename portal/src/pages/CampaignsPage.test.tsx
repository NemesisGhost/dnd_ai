import {
  render,
  screen,
  within,
} from "@testing-library/react"
import { MemoryRouter } from "react-router"
import {
  describe,
  expect,
  it,
} from "vitest"
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
            selected_campaign_id: null,
            campaigns: [],
          }}
          onCampaignSelect={() => {}}
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
          onCampaignSelect={() => {}}
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
      within(link).getByText("Currently selected"),
    ).toBeInTheDocument()
  })

  it("handles a campaign without a timeline", () => {
    render(
      <MemoryRouter>
        <CampaignsPage
          bootstrap={{
            ...sessionBootstrapFixture,
            selected_campaign_id: null,
            campaigns: [
              {
                ...fixtureCampaign,
                timeline_id: null,
                timeline_name: null,
              },
            ],
          }}
          onCampaignSelect={() => {}}
        />
      </MemoryRouter>,
    )

    const link = screen.getByRole("link", {
      name: /Mundivita/,
    })

    expect(
      within(link).getByText(
        "No timeline selected",
      ),
    ).toBeInTheDocument()

    expect(
      within(link).queryByText(
        "Currently selected",
      ),
    ).not.toBeInTheDocument()
  })
})