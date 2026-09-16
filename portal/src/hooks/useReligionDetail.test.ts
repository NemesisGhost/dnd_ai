import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { ReligionDetail } from "../types/world"
import { useReligionDetail } from "./useReligionDetail"

const { fetchReligionDetailMock } = vi.hoisted(() => ({
    fetchReligionDetailMock: vi.fn(),
}))

vi.mock("../api/world", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/world")>()
    return {
        ...actual,
        fetchReligionDetail: fetchReligionDetailMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: vi.fn() }),
}))

const religionFixture: ReligionDetail = {
    religion_id: "religion-a",
    name: "The Tidefather Communion",
    summary: null,
    pantheon_structure: null,
    serving_organization_ids: [],
}

beforeEach(() => {
    fetchReligionDetailMock.mockReset()
})

describe("useReligionDetail", () => {
    it("calls fetchReligionDetail with the campaign and religion id", async () => {
        fetchReligionDetailMock.mockResolvedValue(religionFixture)

        const { result } = renderHook(() =>
            useReligionDetail("campaign-a", "religion-a"),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                detail: religionFixture,
            })
        })

        expect(fetchReligionDetailMock).toHaveBeenCalledWith(
            "campaign-a",
            "religion-a",
            expect.any(AbortSignal),
        )
    })
})
