import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ProfileMenu } from "./ProfileMenu"
import { SessionContext } from "../context/SessionContext"
import type { UseSessionBootstrapResult } from "../hooks/useSessionBootstrap"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"

const fetchMock = vi.fn()

afterEach(() => {
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

function renderMenu(session: UseSessionBootstrapResult) {
  return render(
    <MemoryRouter>
      <SessionContext.Provider value={session}>
        <ProfileMenu />
        <button type="button">Outside control</button>
      </SessionContext.Provider>
    </MemoryRouter>,
  )
}

describe("ProfileMenu basics", () => {
  it("renders nothing when not authenticated", () => {
    renderMenu({ state: { status: "unauthenticated" }, reload: vi.fn() })

    expect(
      screen.queryByRole("button", { name: /account menu/i }),
    ).not.toBeInTheDocument()
  })

  it("has an accessible name built from the display name and visible initials", () => {
    renderMenu({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload: vi.fn(),
    })

    const button = screen.getByRole("button", {
      name: "Account menu for Campaign Administrator",
    })

    expect(button).toHaveAttribute("aria-expanded", "false")
    expect(screen.getByText("CA")).toHaveAttribute("aria-hidden", "true")
  })

  it("toggles aria-expanded and reveals the popup contents", () => {
    renderMenu({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload: vi.fn(),
    })

    const button = screen.getByRole("button", {
      name: "Account menu for Campaign Administrator",
    })

    expect(
      screen.queryByRole("link", { name: "Your Account" }),
    ).not.toBeInTheDocument()

    fireEvent.click(button)

    expect(button).toHaveAttribute("aria-expanded", "true")
    expect(button).toHaveAttribute(
      "aria-controls",
      screen.getByRole("link", { name: "Your Account" })
        .closest("[id]")?.id,
    )
    expect(
      screen.getByRole("link", { name: "Your Account" }),
    ).toBeInTheDocument()
  })

  it("never uses ARIA menu semantics", () => {
    renderMenu({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload: vi.fn(),
    })

    fireEvent.click(
      screen.getByRole("button", { name: /account menu/i }),
    )

    expect(screen.queryByRole("menu")).not.toBeInTheDocument()
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument()
  })
})

describe("ProfileMenu focus and keyboard", () => {
  it("focuses Your Account when opened", async () => {
    renderMenu({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload: vi.fn(),
    })

    fireEvent.click(
      screen.getByRole("button", { name: /account menu/i }),
    )

    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: "Your Account" }),
      ).toHaveFocus()
    })
  })

  it("closes and refocuses the button on Escape", async () => {
    renderMenu({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload: vi.fn(),
    })

    const button = screen.getByRole("button", { name: /account menu/i })
    fireEvent.click(button)

    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: "Your Account" }),
      ).toHaveFocus()
    })

    fireEvent.keyDown(
      screen.getByRole("link", { name: "Your Account" }),
      { key: "Escape" },
    )

    expect(button).toHaveAttribute("aria-expanded", "false")
    expect(button).toHaveFocus()
  })

  it("closes without moving focus when a pointerdown lands outside", () => {
    renderMenu({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload: vi.fn(),
    })

    fireEvent.click(
      screen.getByRole("button", { name: /account menu/i }),
    )

    const outside = screen.getByRole("button", { name: "Outside control" })
    fireEvent.pointerDown(outside)
    outside.focus()

    expect(
      screen.getByRole("button", { name: /account menu/i }),
    ).toHaveAttribute("aria-expanded", "false")
    expect(outside).toHaveFocus()
  })

  it("closes on focusout to an element outside the widget", () => {
    renderMenu({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload: vi.fn(),
    })

    fireEvent.click(
      screen.getByRole("button", { name: /account menu/i }),
    )

    const yourAccount = screen.getByRole("link", { name: "Your Account" })
    const outside = screen.getByRole("button", { name: "Outside control" })

    fireEvent.focusOut(yourAccount, { relatedTarget: outside })

    expect(
      screen.getByRole("button", { name: /account menu/i }),
    ).toHaveAttribute("aria-expanded", "false")
  })

  it("closes and navigates when Your Account is activated", () => {
    renderMenu({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload: vi.fn(),
    })

    fireEvent.click(
      screen.getByRole("button", { name: /account menu/i }),
    )

    fireEvent.click(screen.getByRole("link", { name: "Your Account" }))

    expect(
      screen.getByRole("button", { name: /account menu/i }),
    ).toHaveAttribute("aria-expanded", "false")
  })
})

describe("ProfileMenu capability filtering", () => {
  it("omits the Administration group for a non-administrator", () => {
    renderMenu({
      state: {
        status: "authenticated",
        bootstrap: {
          ...sessionBootstrapFixture,
          is_platform_administrator: false,
        },
      },
      reload: vi.fn(),
    })

    fireEvent.click(
      screen.getByRole("button", { name: /account menu/i }),
    )

    expect(
      screen.queryByRole("group", { name: "Administration" }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("link", { name: "Platform Accounts" }),
    ).not.toBeInTheDocument()
  })

  it("shows the Administration group for a platform administrator", () => {
    renderMenu({
      state: {
        status: "authenticated",
        bootstrap: {
          ...sessionBootstrapFixture,
          is_platform_administrator: true,
        },
      },
      reload: vi.fn(),
    })

    fireEvent.click(
      screen.getByRole("button", { name: /account menu/i }),
    )

    expect(
      screen.getByRole("group", { name: "Administration" }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: "Platform Accounts" }),
    ).toHaveAttribute("href", "/platform/accounts")
  })

  it("stays absent for a campaign owner with access.manage but no platform flag", () => {
    renderMenu({
      state: {
        status: "authenticated",
        bootstrap: {
          ...sessionBootstrapFixture,
          is_platform_administrator: false,
          campaigns: [
            {
              ...sessionBootstrapFixture.campaigns[0]!,
              roles: ["campaign_owner"],
              capabilities: ["access.manage"],
            },
          ],
        },
      },
      reload: vi.fn(),
    })

    fireEvent.click(
      screen.getByRole("button", { name: /account menu/i }),
    )

    expect(
      screen.queryByRole("link", { name: "Platform Accounts" }),
    ).not.toBeInTheDocument()
  })
})

describe("ProfileMenu logout", () => {
  it("posts to /auth/logout and shows a pending, disabled state", async () => {
    let resolveResponse!: (response: Response) => void
    fetchMock.mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveResponse = resolve
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    renderMenu({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload: vi.fn(),
    })

    fireEvent.click(
      screen.getByRole("button", { name: /account menu/i }),
    )

    fireEvent.click(screen.getByRole("button", { name: "Log out" }))

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Logging out…" }),
      ).toBeDisabled()
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

    await act(async () => {
      resolveResponse(new Response(null, { status: 204 }))
    })
  })

  it("shows a recoverable error and keeps the menu open with the button re-enabled", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 500 }))
    vi.stubGlobal("fetch", fetchMock)

    renderMenu({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload: vi.fn(),
    })

    fireEvent.click(
      screen.getByRole("button", { name: /account menu/i }),
    )

    fireEvent.click(screen.getByRole("button", { name: "Log out" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Log out failed (status 500). Please try again.",
    )

    expect(
      screen.getByRole("button", { name: "Log out" }),
    ).toBeEnabled()

    expect(
      screen.getByRole("button", { name: /account menu/i }),
    ).toHaveAttribute("aria-expanded", "true")
  })
})
