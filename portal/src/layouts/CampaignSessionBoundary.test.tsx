import {
  fireEvent,
  render,
  screen,
} from "@testing-library/react"
import {
  MemoryRouter,
  Route,
  Routes,
} from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { useSession } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { CampaignSessionBoundary } from "./CampaignSessionBoundary"

vi.mock("../context/SessionContext", () => ({
  useSession: vi.fn(),
}))

const useSessionMock = vi.mocked(useSession)

beforeEach(() => {
  useSessionMock.mockReset()
})

function renderBoundary() {
  return render(
    <MemoryRouter
      initialEntries={["/app/mundivita/home"]}
    >
      <Routes>
        <Route
          path="/login"
          element={<h1>Log in destination</h1>}
        />

        <Route
          path="/app/:campaignId"
          element={<CampaignSessionBoundary />}
        >
          <Route
            path="home"
            element={<h1>Campaign home</h1>}
          />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe("CampaignSessionBoundary", () => {
  it("shows no campaign content while loading", () => {
    useSessionMock.mockReturnValue({
      state: {
        status: "loading",
      },
      reload: vi.fn(),
    })

    renderBoundary()

    expect(
      screen.getByRole("heading", {
        name: "Loading portal",
      }),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole("navigation", {
        name: "Campaign",
      }),
    ).not.toBeInTheDocument()
  })

  it("redirects an unauthenticated user to login", () => {
    useSessionMock.mockReturnValue({
      state: {
        status: "unauthenticated",
      },
      reload: vi.fn(),
    })

    renderBoundary()

    expect(
      screen.getByRole("heading", {
        name: "Log in destination",
      }),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole("navigation", {
        name: "Campaign",
      }),
    ).not.toBeInTheDocument()
  })

  it("shows a recoverable error without exposing details", () => {
    const reload = vi.fn()

    useSessionMock.mockReturnValue({
      state: {
        status: "error",
        error: new Error("Sensitive internal diagnostic"),
      },
      reload,
    })

    renderBoundary()

    expect(
      screen.getByRole("heading", {
        name: "Portal unavailable",
      }),
    ).toBeInTheDocument()

    expect(
      screen.queryByText("Sensitive internal diagnostic"),
    ).not.toBeInTheDocument()

    expect(
      screen.queryByRole("navigation", {
        name: "Campaign",
      }),
    ).not.toBeInTheDocument()

    fireEvent.click(
      screen.getByRole("button", {
        name: "Try again",
      }),
    )

    expect(reload).toHaveBeenCalledTimes(1)
  })

  it("renders authorized campaign content when authenticated", () => {
    useSessionMock.mockReturnValue({
      state: {
        status: "authenticated",
        bootstrap: sessionBootstrapFixture,
      },
      reload: vi.fn(),
    })

    renderBoundary()

    expect(
      screen.getByRole("navigation", {
        name: "Campaign",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("heading", {
        name: "Campaign home",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByText("Mundivita"),
    ).toBeInTheDocument()
  })
})