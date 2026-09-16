import {
  afterEach,
  describe,
  expect,
  it,
  vi,
} from "vitest"
import {
  logout,
  LogoutRequestError,
} from "./logout"

const fetchMock = vi.fn()

afterEach(() => {
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe("logout", () => {
  it("posts to /auth/logout with same-origin credentials and the CSRF header", async () => {
    const controller = new AbortController()

    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchMock)

    await logout("csrf-456", controller.signal)

    expect(fetchMock).toHaveBeenCalledOnce()

    expect(fetchMock).toHaveBeenCalledWith(
      "/auth/logout",
      {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          "X-CSRF-Token": "csrf-456",
        },
      },
    )
  })

  it("returns a typed HTTP error for a rejected logout", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 403 }))
    vi.stubGlobal("fetch", fetchMock)

    const request = logout("csrf-456")

    await expect(request).rejects.toEqual(
      expect.objectContaining({
        name: "LogoutRequestError",
        status: 403,
        message: "Logout request failed with status 403",
      }),
    )

    await request.catch((error: unknown) => {
      expect(error).toBeInstanceOf(LogoutRequestError)
    })
  })

  it("preserves a network failure", async () => {
    const networkError = new TypeError("Failed to fetch")

    fetchMock.mockRejectedValue(networkError)
    vi.stubGlobal("fetch", fetchMock)

    await expect(logout("csrf-456")).rejects.toBe(networkError)
  })
})
