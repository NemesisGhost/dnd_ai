import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { LocationDetail } from "../types/world"
import { useLocationDetail } from "./useLocationDetail"

const { fetchLocationDetailMock } = vi.hoisted(() => ({
    fetchLocationDetailMock: vi.fn(),
}))

vi.mock("../api/world", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/world")>()
    return {
        ...actual,
        fetchLocationDetail: fetchLocationDetailMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: vi.fn() }),
}))

const locationFixture: LocationDetail = {
    location_id: "location-a",
    name: "The Sunken Archive",
    summary: null,
    location_type_code: "building",
    parent_location_id: null,
    breadcrumbs: [],
    population: null,
    building_use: null,
    danger_level: null,
    is_searched: null,
    is_destroyed: null,
    alarm_level: null,
    condition_notes: null,
}

beforeEach(() => {
    fetchLocationDetailMock.mockReset()
})

describe("useLocationDetail", () => {
    it("calls fetchLocationDetail with the campaign and location id", async () => {
        fetchLocationDetailMock.mockResolvedValue(locationFixture)

        const { result } = renderHook(() =>
            useLocationDetail("campaign-a", "location-a"),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                detail: locationFixture,
            })
        })

        expect(fetchLocationDetailMock).toHaveBeenCalledWith(
            "campaign-a",
            "location-a",
            expect.any(AbortSignal),
        )
    })
})
