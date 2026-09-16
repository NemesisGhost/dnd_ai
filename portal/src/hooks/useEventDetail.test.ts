import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { EventDetail } from "../types/world"
import { useEventDetail } from "./useEventDetail"

const { fetchEventDetailMock } = vi.hoisted(() => ({
    fetchEventDetailMock: vi.fn(),
}))

vi.mock("../api/world", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/world")>()
    return {
        ...actual,
        fetchEventDetail: fetchEventDetailMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: vi.fn() }),
}))

const eventFixture: EventDetail = {
    event_id: "event-a",
    name: "The Sundering of the Vale",
    summary: null,
    event_type_code: "historical_event",
    event_status_code: "recorded",
    world_time_id: "world-time-a",
    details: null,
    session_id: null,
    participants: [],
    locations: [],
}

beforeEach(() => {
    fetchEventDetailMock.mockReset()
})

describe("useEventDetail", () => {
    it("calls fetchEventDetail with the campaign and event id", async () => {
        fetchEventDetailMock.mockResolvedValue(eventFixture)

        const { result } = renderHook(() =>
            useEventDetail("campaign-a", "event-a"),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                detail: eventFixture,
            })
        })

        expect(fetchEventDetailMock).toHaveBeenCalledWith(
            "campaign-a",
            "event-a",
            expect.any(AbortSignal),
        )
    })
})
