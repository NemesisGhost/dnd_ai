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
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import { useCampaignSummary } from "./hooks/useCampaignSummary"
import type { CampaignSummary } from "./types/campaignSummary"

vi.mock("./hooks/useSessionBootstrap", () => ({
  useSessionBootstrap: vi.fn(),
}))

vi.mock("./hooks/useCampaignSummary", () => ({
  useCampaignSummary: vi.fn(),
}))

const useSessionBootstrapMock = vi.mocked(
  useSessionBootstrap,
)

const useCampaignSummaryMock = vi.mocked(useCampaignSummary)

const emptyCampaignSummary = {
  current_session: null,
  previous_session_recap: null,
  recent_events: [],
} satisfies CampaignSummary

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
})