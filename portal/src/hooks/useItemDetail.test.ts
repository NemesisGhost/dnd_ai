import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { ItemDetail } from "../types/world"
import { useItemDetail } from "./useItemDetail"

const { fetchItemDetailMock } = vi.hoisted(() => ({
    fetchItemDetailMock: vi.fn(),
}))

vi.mock("../api/world", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/world")>()
    return {
        ...actual,
        fetchItemDetail: fetchItemDetailMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: vi.fn() }),
}))

const itemFixture: ItemDetail = {
    item_instance_id: "item-a",
    name: "The Warden's Lantern",
    summary: null,
    item_definition_id: "item-def-a",
    origin_notes: null,
    quantity: 1,
    condition_percentage: null,
    charges_current: null,
    charges_maximum: null,
    is_equipped: null,
    is_destroyed: null,
}

beforeEach(() => {
    fetchItemDetailMock.mockReset()
})

describe("useItemDetail", () => {
    it("calls fetchItemDetail with the campaign and item instance id", async () => {
        fetchItemDetailMock.mockResolvedValue(itemFixture)

        const { result } = renderHook(() =>
            useItemDetail("campaign-a", "item-a"),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                detail: itemFixture,
            })
        })

        expect(fetchItemDetailMock).toHaveBeenCalledWith(
            "campaign-a",
            "item-a",
            expect.any(AbortSignal),
        )
    })
})
