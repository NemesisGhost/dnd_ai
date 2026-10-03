import { render, screen, within } from "@testing-library/react"
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import * as userPreferences from "../api/userPreferences"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { SessionBootstrap } from "../types/bootstrap"
import { CampaignLayout } from "./CampaignLayout"

vi.mock("../context/CharacterPerspectiveContext", () => ({
  usePerspective: vi.fn(),
}))
vi.mock("../api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))
vi.mock("../hooks/useCharacter", () => ({
  useCharacter: () => ({
    state: { status: "unavailable" },
    retry: vi.fn(),
  }),
}))

const usePerspectiveMock = vi.mocked(usePerspective)
const recordLastVisited = vi.mocked(userPreferences.recordLastVisitedCampaign)

const secondCampaign = {
  ...sessionBootstrapFixture.campaigns[0]!,
  campaign_id: "secundivita",
  campaign_name: "Secundivita",
  timeline_name: "Divergent Timeline",
}

const bootstrap: SessionBootstrap = {
  ...sessionBootstrapFixture,
  campaigns: [sessionBootstrapFixture.campaigns[0]!, secondCampaign],
}

const selectCharacter = vi.fn()

function LocationProbe() {
  const location = useLocation()
  return <p data-testid="location">{location.pathname}</p>
}

function renderAt(pathname: string) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <Routes>
        <Route
          path="/app/:campaignId"
          element={<CampaignLayout bootstrap={bootstrap} />}
        >
          <Route path="home" element={<h1>Campaign home</h1>} />
          <Route path="quests" element={<h1>Quests</h1>} />
          <Route
            path="quests/:questId"
            element={<h1>Quest detail</h1>}
          />
        </Route>
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  usePerspectiveMock.mockReset()
  selectCharacter.mockReset()
  recordLastVisited.mockClear()
  usePerspectiveMock.mockReturnValue({
    getSelectedCharacterId: () => null,
    selectCharacter,
  })
})

describe("CampaignLayout", () => {
  it("renders no navigation of its own (the shell owns the sidebar)", () => {
    renderAt("/app/mundivita/home")

    expect(screen.queryByRole("navigation")).not.toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
  })

  it("renders the workspace with the panel before the routed content", () => {
    renderAt("/app/mundivita/home")

    const main = screen.getByRole("main")
    expect(
      within(main).getByText(/^Campaign context:/, { selector: "summary" }),
    ).toBeInTheDocument()
    expect(
      within(main).getByRole("heading", { name: "Campaign home" }),
    ).toBeInTheDocument()
  })

  it("offers a non-disclosing Browse campaigns link for an unknown campaign", () => {
    renderAt("/app/not-a-real-campaign/home")

    expect(
      screen.getByRole("heading", { name: "Campaign not found" }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("link", { name: "Browse campaigns" }),
    ).toHaveAttribute("href", "/campaigns")
  })
})

describe("CampaignLayout last-visited recording", () => {
  it("records an authorized route campaign once", () => {
    renderAt("/app/secundivita/home")

    expect(recordLastVisited).toHaveBeenCalledTimes(1)
    expect(recordLastVisited).toHaveBeenCalledWith(
      "secundivita",
      bootstrap.csrf_token,
      expect.any(AbortSignal),
    )
  })

  it("does not record an unknown or unauthorized campaign", () => {
    renderAt("/app/not-a-real-campaign/home")

    expect(recordLastVisited).not.toHaveBeenCalled()
  })
})
