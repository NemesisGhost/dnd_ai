import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fetchOwnSessions } from "../api/ownSessions"
import { useOwnSessions } from "./useOwnSessions"

const { reloadMock } = vi.hoisted(() => ({ reloadMock: vi.fn() }))

vi.mock("../api/ownSessions", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/ownSessions")>()
    return { ...actual, fetchOwnSessions: vi.fn() }
})
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: { status: "authenticated" }, reload: reloadMock }),
}))

beforeEach(() => {
    reloadMock.mockReset()
    vi.mocked(fetchOwnSessions).mockReset()
})

describe("useOwnSessions", () => {
    it("loads sessions", async () => {
        vi.mocked(fetchOwnSessions).mockResolvedValue([
            {
                browser_session_id: "session-1",
                created_at: "2026-09-01T00:00:00Z",
                last_used_at: "2026-09-01T00:00:00Z",
                idle_expires_at: "2026-09-01T00:30:00Z",
                absolute_expires_at: "2026-09-01T12:00:00Z",
                created_ip: null,
                last_used_ip: null,
                user_agent: null,
                is_current: true,
            },
        ])

        const { result } = renderHook(() => useOwnSessions())
        expect(result.current.state).toEqual({ status: "loading" })

        await waitFor(() => {
            expect(result.current.state.status).toBe("success")
        })
    })
})
