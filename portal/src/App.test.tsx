import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest"
import App from "./App"
import { SessionProvider } from "./context/SessionProvider"
import { sessionBootstrapFixture } from "./fixtures/sessionBootstrap"
import {
  useSessionBootstrap,
} from "./hooks/useSessionBootstrap"

vi.mock("./hooks/useSessionBootstrap", () => ({
  useSessionBootstrap: vi.fn(),
}))

const useSessionBootstrapMock = vi.mocked(
  useSessionBootstrap,
)

beforeEach(() => {
  useSessionBootstrapMock.mockReset()

  useSessionBootstrapMock.mockReturnValue({
    state: {
      status: "authenticated",
      bootstrap: sessionBootstrapFixture,
    },
    reload: vi.fn(),
  })
})

function renderAppAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </MemoryRouter>,
  )
}

describe("portal routing", () => {
  it("does not show campaign navigation on the login route", () => {
    renderAppAt("/login")

    expect(
      screen.getByRole("heading", {
        name: "Log in",
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