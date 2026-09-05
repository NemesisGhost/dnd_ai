import {
  render,
  screen,
} from "@testing-library/react"
import { MemoryRouter } from "react-router"
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest"
import App from "./App"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import { sessionBootstrapFixture } from "./fixtures/sessionBootstrap"
import { useCampaignSessions } from "./hooks/useCampaignSessions"
import { useCampaignSummary } from "./hooks/useCampaignSummary"
import { useCharacter } from "./hooks/useCharacter"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import type { CampaignSessionListItem } from "./types/campaignSession"
import type { CampaignSummary } from "./types/campaignSummary"

vi.mock("./hooks/useSessionBootstrap", () => ({
  useSessionBootstrap: vi.fn(),
}))

vi.mock("./hooks/useCampaignSummary", () => ({
  useCampaignSummary: vi.fn(),
}))

vi.mock("./hooks/useCharacter", () => ({
  useCharacter: vi.fn(),
}))

vi.mock("./hooks/useCampaignSessions", () => ({
  useCampaignSessions: vi.fn(),
}))

const useSessionBootstrapMock = vi.mocked(
  useSessionBootstrap,
)

const useCampaignSummaryMock = vi.mocked(
  useCampaignSummary,
)

const useCharacterMock = vi.mocked(
  useCharacter,
)

const useCampaignSessionsMock = vi.mocked(
  useCampaignSessions,
)

const emptyCampaignSummary = {
  current_session: null,
  previous_session_recap: null,
  recent_events: [],
} satisfies CampaignSummary

const campaignSessions = [
  {
    session_id: "session-2",
    session_number: 2,
    title: "Most Recent Session",
    status_code: "completed",
    started_at: "2026-02-01T18:00:00Z",
    ended_at: "2026-02-01T22:00:00Z",
  },
] satisfies CampaignSessionListItem[]

beforeEach(() => {
  useSessionBootstrapMock.mockReset()

  useSessionBootstrapMock.mockReturnValue({
    state: {
      status: "authenticated",
      bootstrap: sessionBootstrapFixture,
    },
    reload: vi.fn(),
  })

  useCampaignSummaryMock.mockReset()

  useCampaignSummaryMock.mockReturnValue({
    state: {
      status: "success",
      summary: emptyCampaignSummary,
    },
    retry: vi.fn(),
  })

  useCharacterMock.mockReset()

  useCharacterMock.mockReturnValue({
    state: {
      status: "unavailable",
    },
    retry: vi.fn(),
  })

  useCampaignSessionsMock.mockReset()

  useCampaignSessionsMock.mockReturnValue({
    state: {
      status: "success",
      sessions: campaignSessions,
    },
    retry: vi.fn(),
  })
})

function renderAppAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <RouteSessionProvider>
        <App />
      </RouteSessionProvider>
    </MemoryRouter>,
  )
}

describe("portal routing", () => {
  it("shows login without campaign navigation for an unauthenticated user", () => {
    useSessionBootstrapMock.mockReturnValue({
      state: {
        status: "unauthenticated",
      },
      reload: vi.fn(),
    })

    renderAppAt("/login")

    expect(
      screen.getByRole("heading", {
        name: "D&D AI World",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("button", {
        name: "Sign In",
      }),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole("navigation", {
        name: "Campaign",
      }),
    ).not.toBeInTheDocument()
  })

  it("shows campaign navigation and disables unavailable Ask", () => {
    renderAppAt("/app/mundivita/home")

    expect(
      screen.getByRole("navigation", {
        name: "Campaign",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("link", {
        name: "Home",
      }),
    ).toHaveAttribute("aria-current", "page")

    expect(
      screen.queryByRole("link", {
        name: "Ask",
      }),
    ).not.toBeInTheDocument()

    expect(
      screen.getByText("Ask"),
    ).toHaveAttribute("aria-disabled", "true")

    expect(
      screen.getByRole("link", {
        name: "Access",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("link", {
        name: "Change campaign",
      }),
    ).toHaveAttribute("href", "/campaigns")

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Home",
      }),
    ).toBeInTheDocument()
  })

  it("does not disclose campaign chrome for an unknown campaign", () => {
    renderAppAt("/app/not-a-real-campaign/home")

    expect(
      screen.getByRole("heading", {
        name: "Campaign not found",
      }),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole("navigation", {
        name: "Campaign",
      }),
    ).not.toBeInTheDocument()
  })

  it("routes Characters to the selected character workspace", () => {
    renderAppAt("/app/mundivita/characters")

    expect(
      screen.getByRole("link", {
        name: "Characters",
      }),
    ).toHaveAttribute("aria-current", "page")

    expect(
      useCharacterMock,
    ).toHaveBeenCalledWith(
      "mundivita",
      "character-ixamarra",
    )

    expect(
      screen.getByRole("heading", {
        name: "Character unavailable",
      }),
    ).toBeInTheDocument()
  })

  it("routes Sessions through the campaign sessions boundary", () => {
    renderAppAt("/app/mundivita/sessions")

    expect(
      screen.getByRole("link", {
        name: "Sessions",
      }),
    ).toHaveAttribute("aria-current", "page")

    expect(
      useCampaignSessionsMock,
    ).toHaveBeenCalledWith("mundivita")

    expect(
      screen.getByRole("heading", {
        name: "Sessions",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("table", {
        name: "Sessions",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("link", {
        name: "Most Recent Session",
      }),
    ).toHaveAttribute(
      "href",
      "/app/mundivita/sessions/session-2",
    )
  })
})