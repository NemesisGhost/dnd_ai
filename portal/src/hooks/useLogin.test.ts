import {
    act,
    renderHook,
} from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import {
    login,
    LoginRequestError,
} from "../api/login"
import { useSession } from "../context/SessionContext"
import { useLogin } from "./useLogin"

vi.mock("../api/login", async () => {
    const actual =
        await vi.importActual<
            typeof import("../api/login")
        >("../api/login")

    return {
        ...actual,
        login: vi.fn(),
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: vi.fn(),
}))

const loginMock = vi.mocked(login)
const useSessionMock = vi.mocked(useSession)
const reloadMock = vi.fn()

const credentials = {
    login_name: "test-user",
    password: "test-password",
}

beforeEach(() => {
    loginMock.mockReset()
    useSessionMock.mockReset()
    reloadMock.mockReset()

    useSessionMock.mockReturnValue({
        state: {
            status: "unauthenticated",
        },
        reload: reloadMock,
    })
})

describe("useLogin", () => {
    it("starts idle and refreshes the session after successful login", async () => {
        loginMock.mockResolvedValue({
            user_id: "user-123",
            csrf_token: "csrf-456",
        })

        const { result } = renderHook(() => useLogin())

        expect(result.current.state).toEqual({
            status: "idle",
        })

        let succeeded: boolean | undefined

        await act(async () => {
            succeeded = await result.current.submit(
                credentials,
            )
        })

        expect(succeeded).toBe(true)

        expect(loginMock).toHaveBeenCalledWith(
            credentials,
        )

        expect(result.current.state).toEqual({
            status: "complete",
        })

        expect(reloadMock).toHaveBeenCalledOnce()
    })

    it("shows a generic message for rejected credentials", async () => {
        loginMock.mockRejectedValue(
            new LoginRequestError(401),
        )

        const { result } = renderHook(() => useLogin())

        let succeeded: boolean | undefined

        await act(async () => {
            succeeded = await result.current.submit(
                credentials,
            )
        })

        expect(succeeded).toBe(false)

        expect(result.current.state).toEqual({
            status: "error",
            message:
                "The login name or password is incorrect.",
        })

        expect(reloadMock).not.toHaveBeenCalled()
    })

    it("shows a bounded message when login is rate limited", async () => {
        loginMock.mockRejectedValue(
            new LoginRequestError(429),
        )

        const { result } = renderHook(() => useLogin())

        await act(async () => {
            await result.current.submit(credentials)
        })

        expect(result.current.state).toEqual({
            status: "error",
            message:
                "Too many login attempts. Wait and try again.",
        })

        expect(reloadMock).not.toHaveBeenCalled()
    })

    it.each([
        [
            "a server failure",
            new LoginRequestError(500),
        ],
        [
            "a network failure",
            new TypeError("Failed to fetch"),
        ],
    ])(
        "shows a recoverable generic message for %s",
        async (_description, cause) => {
            loginMock.mockRejectedValue(cause)

            const { result } = renderHook(() => useLogin())

            await act(async () => {
                await result.current.submit(credentials)
            })

            expect(result.current.state).toEqual({
                status: "error",
                message:
                    "The portal could not sign you in. Try again.",
            })

            expect(reloadMock).not.toHaveBeenCalled()
        },
    )
})