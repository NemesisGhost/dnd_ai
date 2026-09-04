import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react"
import {
  MemoryRouter,
  Route,
  Routes,
} from "react-router"
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest"
import { useSession } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { useLogin } from "../hooks/useLogin"
import { LoginPage } from "./LoginPage"

vi.mock("../context/SessionContext", () => ({
  useSession: vi.fn(),
}))

vi.mock("../hooks/useLogin", () => ({
  useLogin: vi.fn(),
}))

const useSessionMock = vi.mocked(useSession)
const useLoginMock = vi.mocked(useLogin)

const reloadMock = vi.fn()
const submitMock = vi.fn()

beforeEach(() => {
  reloadMock.mockReset()
  submitMock.mockReset()

  useSessionMock.mockReset()
  useLoginMock.mockReset()

  useSessionMock.mockReturnValue({
    state: {
      status: "unauthenticated",
    },
    reload: reloadMock,
  })

  useLoginMock.mockReturnValue({
    state: {
      status: "idle",
    },
    submit: submitMock,
  })
})

function renderLoginPage() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route
          path="/login"
          element={<LoginPage />}
        />

        <Route
          path="/campaigns"
          element={
            <h1>Campaign destination</h1>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

describe("LoginPage", () => {
  it("submits the accessible login form and clears successful credentials", async () => {
    submitMock.mockResolvedValue(true)

    renderLoginPage()

    const loginNameInput = screen.getByRole(
      "textbox",
      {
        name: "Email or Username",
      },
    )

    const passwordInput =
      screen.getByLabelText("Password")

    fireEvent.change(loginNameInput, {
      target: {
        value: "test-user",
      },
    })

    fireEvent.change(passwordInput, {
      target: {
        value: "test-password",
      },
    })

    fireEvent.click(
      screen.getByRole("button", {
        name: "Sign In",
      }),
    )

    await waitFor(() => {
      expect(submitMock).toHaveBeenCalledWith({
        login_name: "test-user",
        password: "test-password",
      })
    })

    expect(loginNameInput).toHaveValue("")
    expect(passwordInput).toHaveValue("")
  })

  it("announces a safe login failure", () => {
    useLoginMock.mockReturnValue({
      state: {
        status: "error",
        message:
          "The login name or password is incorrect.",
      },
      submit: submitMock,
    })

    renderLoginPage()

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The login name or password is incorrect.",
    )
  })

  it("allows a failed session check to be retried", () => {
    useSessionMock.mockReturnValue({
      state: {
        status: "error",
        error: new Error(
          "Sensitive backend diagnostic",
        ),
      },
      reload: reloadMock,
    })

    renderLoginPage()

    expect(
      screen.getByRole("heading", {
        name: "Portal unavailable",
      }),
    ).toBeInTheDocument()

    expect(
      screen.queryByText(
        "Sensitive backend diagnostic",
      ),
    ).not.toBeInTheDocument()

    fireEvent.click(
      screen.getByRole("button", {
        name: "Try again",
      }),
    )

    expect(reloadMock).toHaveBeenCalledOnce()
  })

  it("redirects an authenticated user to campaign selection", async () => {
    useSessionMock.mockReturnValue({
      state: {
        status: "authenticated",
        bootstrap: sessionBootstrapFixture,
      },
      reload: reloadMock,
    })

    renderLoginPage()

    expect(
      await screen.findByRole("heading", {
        name: "Campaign destination",
      }),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole("button", {
        name: "Sign In",
      }),
    ).not.toBeInTheDocument()
  })
})