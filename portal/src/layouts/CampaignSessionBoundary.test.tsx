import { render, screen, within } from "@testing-library/react"
import {
  MemoryRouter,
  Route,
  Routes,
} from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { ThemeProvider } from "../themes/ThemeProvider"
import { CampaignSessionBoundary } from "./CampaignSessionBoundary"
import { AuthenticatedAppLayout } from "./AuthenticatedAppLayout"
import { useSession } from "../context/SessionContext"

vi.mock("../context/SessionContext", () => ({
  useSession: vi.fn(),
}))
vi.mock("../context/CharacterPerspectiveContext", () => ({
  usePerspective: vi.fn(),
}))
vi.mock("../hooks/useCharacter", () => ({
  useCharacter: () => ({
    state: { status: "unavailable" },
    retry: vi.fn(),
  }),
}))

const useSessionMock = vi.mocked(useSession)
const usePerspectiveMock = vi.mocked(usePerspective)

beforeEach(() => {
  useSessionMock.mockReset()
  usePerspectiveMock.mockReset()

  useSessionMock.mockReturnValue({
    state: {
      status: "authenticated",
      bootstrap: sessionBootstrapFixture,
    },
    reload: vi.fn(),
  })

  usePerspectiveMock.mockReturnValue({
    getSelectedCharacterId: (campaignId) =>
      sessionBootstrapFixture.campaigns.find(
        (campaign) => campaign.campaign_id === campaignId,
      )?.selected_character_id ?? null,
    selectCharacter: vi.fn(),
  })
})

function renderAt(pathname: string) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <ThemeProvider>
        <Routes>
          <Route element={<AuthenticatedAppLayout />}>
            <Route path="/app/:campaignId" element={<CampaignSessionBoundary />}>
              <Route path="home" element={<h1>Campaign home</h1>} />
            </Route>
          </Route>
        </Routes>
      </ThemeProvider>
    </MemoryRouter>,
  )
}

describe("CampaignSessionBoundary", () => {
  it("renders the authorized campaign workspace when authenticated", () => {
    renderAt("/app/mundivita/home")

    expect(
      screen.getByRole("navigation", { name: "Campaign" }),
    ).toBeInTheDocument()

    const main = screen.getByRole("main")

    expect(
      within(main).getByRole("heading", { name: "Campaign home" }),
    ).toBeInTheDocument()

    expect(
      within(main).getByText(
        "Campaign context: Mundivita — Viewing as Ixamarra",
        { selector: "summary" },
      ),
    ).toBeInTheDocument()

    expect(
      within(main).getByText("Primary Timeline"),
    ).toBeInTheDocument()

    expect(
      within(main).getByRole("combobox", { name: "Character perspective" }),
    ).toHaveValue("character-ixamarra")

    expect(
      within(main).getByRole("combobox", { name: "Campaign" }),
    ).toHaveValue("mundivita")
  })

  it("does not disclose campaign chrome for an unknown campaign", () => {
    renderAt("/app/not-a-real-campaign/home")

    expect(
      screen.getByRole("heading", { name: "Campaign not found" }),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole("navigation", { name: "Campaign" }),
    ).not.toBeInTheDocument()
  })
})
