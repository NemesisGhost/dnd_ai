import {
  fireEvent,
  render,
  screen,
} from "@testing-library/react"
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { useSession } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { AuthenticatedAppLayout } from "./AuthenticatedAppLayout"
import { useAuthenticatedSession } from "./useAuthenticatedSession"

vi.mock("../context/SessionContext", () => ({
  useSession: vi.fn(),
}))

const useSessionMock = vi.mocked(useSession)

function ProtectedProbe() {
  const { bootstrap } = useAuthenticatedSession()
  return <h1>Protected content for {bootstrap.user.display_name}</h1>
}

function LoginLocationProbe() {
  const location = useLocation()
  return (
    <>
      <h1>Log in destination</h1>
      <p data-testid="from-state">
        {JSON.stringify((location.state as { from?: string } | null)?.from ?? null)}
      </p>
    </>
  )
}

function renderLayout(initialPath = "/home") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/login" element={<LoginLocationProbe />} />

        <Route element={<AuthenticatedAppLayout />}>
          <Route path="/home" element={<ProtectedProbe />} />
          <Route path="/app/:campaignId/quests" element={<ProtectedProbe />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  useSessionMock.mockReset()
})

describe("AuthenticatedAppLayout", () => {
  it("shows global navigation and a loading placeholder with no profile button while loading", () => {
    useSessionMock.mockReturnValue({
      state: { status: "loading" },
      reload: vi.fn(),
    })

    renderLayout()

    expect(
      screen.getByRole("navigation", { name: "Global" }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("heading", { name: "Loading portal" }),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole("button", { name: "Log out" }),
    ).not.toBeInTheDocument()
  })

  it("redirects an unauthenticated user to login", () => {
    useSessionMock.mockReturnValue({
      state: { status: "unauthenticated" },
      reload: vi.fn(),
    })

    renderLayout()

    expect(
      screen.getByRole("heading", { name: "Log in destination" }),
    ).toBeInTheDocument()
  })

  it("carries the requested path as continuation state, with no hash", () => {
    useSessionMock.mockReturnValue({
      state: { status: "unauthenticated" },
      reload: vi.fn(),
    })

    renderLayout("/app/mundivita/quests?x=1#section")

    expect(screen.getByTestId("from-state")).toHaveTextContent(
      JSON.stringify("/app/mundivita/quests?x=1"),
    )
  })

  it("shows global navigation and a recoverable error without exposing details", () => {
    const reload = vi.fn()

    useSessionMock.mockReturnValue({
      state: { status: "error", error: new Error("Sensitive internal diagnostic") },
      reload,
    })

    renderLayout()

    expect(
      screen.getByRole("navigation", { name: "Global" }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("heading", { name: "Portal unavailable" }),
    ).toBeInTheDocument()

    expect(
      screen.queryByText("Sensitive internal diagnostic"),
    ).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Try again" }))

    expect(reload).toHaveBeenCalledTimes(1)
  })

  it("renders the outlet with the authenticated bootstrap in context, and the global shell", () => {
    useSessionMock.mockReturnValue({
      state: {
        status: "authenticated",
        bootstrap: sessionBootstrapFixture,
      },
      reload: vi.fn(),
    })

    renderLayout()

    expect(
      screen.getByRole("navigation", { name: "Global" }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("heading", {
        name: "Protected content for Campaign Administrator",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("button", { name: "Log out" }),
    ).toBeInTheDocument()
  })
})
