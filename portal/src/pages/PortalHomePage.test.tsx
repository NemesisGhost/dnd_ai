import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { PortalHomePage } from "./PortalHomePage"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"

function campaign(overrides: Partial<CampaignContext>): CampaignContext {
  return {
    ...sessionBootstrapFixture.campaigns[0]!,
    ...overrides,
  }
}

function renderHome(bootstrap: SessionBootstrap) {
  return render(
    <MemoryRouter>
      <PortalHomePage bootstrap={bootstrap} />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("PortalHomePage", () => {
  it("makes no network requests", () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    renderHome(sessionBootstrapFixture)

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("shows a default-campaign link when startup_campaign_id matches an authorized campaign", () => {
    renderHome(sessionBootstrapFixture)

    expect(
      screen.getByRole("heading", { name: "Default campaign" }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("link", { name: /Open default campaign/ }),
    ).toHaveAttribute("href", "/app/mundivita/home")
  })

  it("omits the default-campaign section when startup_campaign_id is null", () => {
    renderHome({ ...sessionBootstrapFixture, startup_campaign_id: null })

    expect(
      screen.queryByRole("heading", { name: "Default campaign" }),
    ).not.toBeInTheDocument()
  })

  it("omits the default-campaign section when startup_campaign_id is not in the campaign list", () => {
    renderHome({
      ...sessionBootstrapFixture,
      startup_campaign_id: "not-a-real-campaign",
    })

    expect(
      screen.queryByRole("heading", { name: "Default campaign" }),
    ).not.toBeInTheDocument()
  })

  it("lists at most 6 campaigns in server order with no raw ids", () => {
    const campaigns = Array.from({ length: 8 }, (_, index) =>
      campaign({
        campaign_id: `campaign-secret-${index}`,
        campaign_name: `Campaign ${index}`,
        world_name: `World ${index}`,
        timeline_name: index === 0 ? null : `Timeline ${index}`,
        roles: ["campaign_owner"],
      }),
    )

    renderHome({
      ...sessionBootstrapFixture,
      startup_campaign_id: null,
      campaigns,
    })

    const links = screen.getAllByRole("link", { name: /Campaign \d/ })
    expect(links).toHaveLength(6)
    expect(links[0]).toHaveTextContent("Campaign 0")
    expect(links[0]).toHaveTextContent("No timeline selected")
    expect(links[0]).toHaveTextContent("Campaign Owner")
    expect(screen.queryByText("campaign-secret-0")).not.toBeInTheDocument()
  })

  it("links to the full campaign browser with the authorized-only count", () => {
    renderHome(sessionBootstrapFixture)

    expect(
      screen.getByRole("link", { name: /View all campaigns/ }),
    ).toHaveAttribute("href", "/campaigns")

    expect(
      screen.getByText("View all campaigns (1)"),
    ).toBeInTheDocument()
  })

  it("shows the empty state with Browse and Accept-invitation links when there are no campaigns", () => {
    renderHome({ ...sessionBootstrapFixture, campaigns: [], startup_campaign_id: null })

    expect(
      screen.getByText("You do not have access to any campaigns yet."),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("link", { name: "Browse campaigns" }),
    ).toHaveAttribute("href", "/campaigns")

    expect(
      screen.getByRole("link", { name: "Accept a campaign invitation" }),
    ).toHaveAttribute("href", "/campaign-invitations/accept")
  })

  it("gates the Platform accounts account-section link on is_platform_administrator", () => {
    const { rerender } = render(
      <MemoryRouter>
        <PortalHomePage
          bootstrap={{
            ...sessionBootstrapFixture,
            is_platform_administrator: false,
          }}
        />
      </MemoryRouter>,
    )

    expect(
      screen.queryByRole("link", { name: "Platform accounts" }),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: "Your account" }),
    ).toHaveAttribute("href", "/account")

    rerender(
      <MemoryRouter>
        <PortalHomePage
          bootstrap={{
            ...sessionBootstrapFixture,
            is_platform_administrator: true,
          }}
        />
      </MemoryRouter>,
    )

    expect(
      screen.getByRole("link", { name: "Platform accounts" }),
    ).toHaveAttribute("href", "/platform/accounts")
  })

  it("omits the welcome line when the display name has no usable value", () => {
    renderHome({
      ...sessionBootstrapFixture,
      user: { ...sessionBootstrapFixture.user, display_name: "  " },
    })

    expect(screen.queryByText(/Welcome,/)).not.toBeInTheDocument()
  })

  it("shows a welcome line with the display name when usable", () => {
    renderHome(sessionBootstrapFixture)

    expect(
      within(screen.getByRole("main")).getByText(
        "Welcome, Campaign Administrator.",
      ),
    ).toBeInTheDocument()
  })
})
