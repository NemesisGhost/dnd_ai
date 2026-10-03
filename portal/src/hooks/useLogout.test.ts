import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useLogout } from "./useLogout"
import { useSession } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"

const fetchMock = vi.fn()
const navigateMock = vi.fn()

vi.mock("../context/SessionContext", () => ({
  useSession: vi.fn(),
}))

vi.mock("react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router")>()
  return {
    ...actual,
    useNavigate: () => navigateMock,
  }
})

const useSessionMock = vi.mocked(useSession)

afterEach(() => {
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

beforeEach(() => {
  useSessionMock.mockReset()
})

describe("useLogout", () => {
  it("posts to /auth/logout with same-origin credentials and the in-memory CSRF token", async () => {
    const reload = vi.fn()
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchMock)

    useSessionMock.mockReturnValue({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload,
      refresh: vi.fn(),
    })

    const { result } = renderHook(() => useLogout())

    await act(async () => {
      await result.current.logout()
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

  it("reloads session state and then navigates to /login with no continuation state on success", async () => {
    const reload = vi.fn()
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchMock)

    useSessionMock.mockReturnValue({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload,
      refresh: vi.fn(),
    })

    const { result } = renderHook(() => useLogout())

    await act(async () => {
      await result.current.logout()
    })

    expect(reload).toHaveBeenCalledOnce()
    expect(navigateMock).toHaveBeenCalledWith("/login", { replace: true })

    const reloadOrder = reload.mock.invocationCallOrder[0]
    const navigateOrder = navigateMock.mock.invocationCallOrder[0]
    expect(reloadOrder).toBeLessThan(navigateOrder)
  })

  it("shows a pending state before resolving, then clears it on success", async () => {
    const reload = vi.fn()
    let resolveResponse!: (response: Response) => void
    fetchMock.mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveResponse = resolve
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    useSessionMock.mockReturnValue({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload,
      refresh: vi.fn(),
    })

    const { result } = renderHook(() => useLogout())

    let logoutPromise!: Promise<void>
    act(() => {
      logoutPromise = result.current.logout()
    })

    await waitFor(() => {
      expect(result.current.status).toEqual({ kind: "pending" })
    })

    expect(reload).not.toHaveBeenCalled()

    await act(async () => {
      resolveResponse(new Response(null, { status: 204 }))
      await logoutPromise
    })

    expect(reload).toHaveBeenCalledOnce()
    expect(navigateMock).toHaveBeenCalledWith("/login", { replace: true })
  })

  it("shows a recoverable error and does not reload or navigate on failure", async () => {
    const reload = vi.fn()
    fetchMock.mockResolvedValue(new Response(null, { status: 500 }))
    vi.stubGlobal("fetch", fetchMock)

    useSessionMock.mockReturnValue({
      state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
      reload,
      refresh: vi.fn(),
    })

    const { result } = renderHook(() => useLogout())

    await act(async () => {
      await result.current.logout()
    })

    expect(result.current.status).toEqual({
      kind: "error",
      message: "Log out failed (status 500). Please try again.",
    })
    expect(reload).not.toHaveBeenCalled()
    expect(navigateMock).not.toHaveBeenCalled()
  })

  it("does nothing when the caller is not authenticated", async () => {
    const reload = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    useSessionMock.mockReturnValue({
      state: { status: "unauthenticated" },
      reload,
      refresh: vi.fn(),
    })

    const { result } = renderHook(() => useLogout())

    await act(async () => {
      await result.current.logout()
    })

    expect(fetchMock).not.toHaveBeenCalled()
    expect(reload).not.toHaveBeenCalled()
    expect(navigateMock).not.toHaveBeenCalled()
  })
})
