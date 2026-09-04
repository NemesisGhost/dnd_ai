import {
  afterEach,
  describe,
  expect,
  it,
  vi,
} from "vitest"
import {
  login,
  LoginRequestError,
} from "./login"

const fetchMock = vi.fn()

afterEach(() => {
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe("login", () => {
  it("posts credentials and returns the successful response", async () => {
    const controller = new AbortController()

    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          user_id: "user-123",
          csrf_token: "csrf-456",
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    )

    vi.stubGlobal("fetch", fetchMock)

    const result = await login(
      {
        login_name: "test-user",
        password: "test-password",
      },
      controller.signal,
    )

    expect(result).toEqual({
      user_id: "user-123",
      csrf_token: "csrf-456",
    })

    expect(fetchMock).toHaveBeenCalledOnce()

    expect(fetchMock).toHaveBeenCalledWith(
      "/auth/login",
      {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          login_name: "test-user",
          password: "test-password",
        }),
      },
    )
  })

  it("returns a typed HTTP error for rejected credentials", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          error_code: "unauthorized",
          message: "The request could not be authenticated.",
        }),
        {
          status: 401,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    )

    vi.stubGlobal("fetch", fetchMock)

    const request = login({
      login_name: "test-user",
      password: "incorrect-password",
    })

    await expect(request).rejects.toEqual(
      expect.objectContaining({
        name: "LoginRequestError",
        status: 401,
        message: "Login request failed with status 401",
      }),
    )

    await request.catch((error: unknown) => {
      expect(error).toBeInstanceOf(LoginRequestError)
    })
  })

  it("preserves a network failure", async () => {
    const networkError = new TypeError("Failed to fetch")

    fetchMock.mockRejectedValue(networkError)
    vi.stubGlobal("fetch", fetchMock)

    await expect(
      login({
        login_name: "test-user",
        password: "test-password",
      }),
    ).rejects.toBe(networkError)
  })
})