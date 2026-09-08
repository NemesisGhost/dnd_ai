import { fireEvent, render, screen, within } from "@testing-library/react"
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { SessionBootstrap } from "../types/bootstrap"
import { CampaignLayout } from "./CampaignLayout"

vi.mock("../context/CharacterPerspectiveContext", () => ({
  usePerspective: vi.fn(),
}))
vi.mock("../hooks/useCharacter", () => ({
  useCharacter: () => ({
    state: { status: "unavailable" },
    retry: vi.fn(),
  }),
}))

const usePerspectiveMock = vi.mocked(usePerspective)

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
  usePerspectiveMock.mockReturnValue({
    getSelectedCharacterId: () => null,
    selectCharacter,
  })
})

describe("CampaignLayout campaign switching", () => {
  it("keeps the current section and drops the detail id", () => {
    renderAt("/app/mundivita/quests/quest-7")

    fireEvent.change(
      screen.getByRole("combobox", { name: "Campaign" }),
      { target: { value: "secundivita" } },
    )

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/app/secundivita/quests",
    )
    expect(selectCharacter).toHaveBeenCalledWith("secundivita", null)
  })

  it("preserves a plain section route", () => {
    renderAt("/app/mundivita/home")

    fireEvent.change(
      screen.getByRole("combobox", { name: "Campaign" }),
      { target: { value: "secundivita" } },
    )

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/app/secundivita/home",
    )
  })

  it("does not navigate when the active campaign is re-selected", () => {
    renderAt("/app/mundivita/quests/quest-7")

    fireEvent.change(
      screen.getByRole("combobox", { name: "Campaign" }),
      { target: { value: "mundivita" } },
    )

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/app/mundivita/quests/quest-7",
    )
    expect(selectCharacter).not.toHaveBeenCalled()
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
})
