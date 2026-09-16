import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { LogoutButton } from "./LogoutButton"
import { SessionContext } from "../context/SessionContext"
import type { UseSessionBootstrapResult } from "../hooks/useSessionBootstrap"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"

const fetchMock = vi.fn()

afterEach(() => {
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

function renderWithSession(
  session: UseSessionBootstrapResult,
) {
  return render(
    <SessionContext.Provider value={session}>
      <LogoutButton />
    </SessionContext.Provider>,
  )
}

describe("LogoutButton", () => {
  it("renders nothing when the caller is not authenticated", () => {
    renderWithSession({
      state: { status: "unauthenticated" },
      reload: vi.fn(),
    })

    expect(
      screen.queryByRole("button", { name: /log out/i }),
    ).not.toBeInTheDocument()
  })

  it("posts to /auth/logout with same-origin credentials and the in-memory CSRF token", async () => {
    const reload = vi.fn()

    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchMock)

    renderWithSession({
      state: {
        status: "authenticated",
        bootstrap: sessionBootstrapFixture,
      },
      reload,
    })

    fireEvent.click(screen.getByRole("button", { name: "Log out" }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledOnce()
    })

    expect(fetchMock).toHaveBeenCalledWith(
      "/auth/logout",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        headers: expect.objectContaining({
          "X-CSRF-Token": sessionBootstrapFixture.csrf_token,
        }),
      }),
    )
  })

  it("shows a pending state, then removes protected UI by reloading session state on success", async () => {
    const reload = vi.fn()

    let resolveResponse!: (response: Response) => void
    fetchMock.mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveResponse = resolve
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    renderWithSession({
      state: {
        status: "authenticated",
        bootstrap: sessionBootstrapFixture,
      },
      reload,
    })

    fireEvent.click(screen.getByRole("button", { name: "Log out" }))

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Logging out…" }),
      ).toBeDisabled()
    })
    expect(reload).not.toHaveBeenCalled()

    await act(async () => {
      resolveResponse(new Response(null, { status: 204 }))
    })

    await waitFor(() => {
      expect(reload).toHaveBeenCalledOnce()
    })
  })

  it("shows a recoverable error and does not reload session state on failure", async () => {
    const reload = vi.fn()

    fetchMock.mockResolvedValue(new Response(null, { status: 500 }))
    vi.stubGlobal("fetch", fetchMock)

    renderWithSession({
      state: {
        status: "authenticated",
        bootstrap: sessionBootstrapFixture,
      },
      reload,
    })

    fireEvent.click(screen.getByRole("button", { name: "Log out" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Log out failed (status 500). Please try again.",
    )
    expect(reload).not.toHaveBeenCalled()

    const retryButton = screen.getByRole("button", { name: "Log out" })
    expect(retryButton).toBeEnabled()
  })
})
