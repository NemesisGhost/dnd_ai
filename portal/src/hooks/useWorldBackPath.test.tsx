import { renderHook } from "@testing-library/react"
import type { ReactNode } from "react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import { useDefinitionsBackPath, useItemsBackPath } from "./useItemsBackPath"
import { useReviewBackPath, useWorldBackPath, useWorldReturnState } from "./useWorldBackPath"

const RECORD = "/app/c1/world/location/e1"
const ITEM = "/app/c1/items/i1"

const wrapper = (state: unknown, pathname = RECORD) =>
    function Wrapper({ children }: { children: ReactNode }) {
        return <MemoryRouter initialEntries={[{ pathname, state }]}>{children}</MemoryRouter>
    }

const task = (root: string, list?: { route: string; search: string }, campaignId = "c1") => ({
    task: { v: 1, root, scope: { campaignId }, trail: [], ...(list === undefined ? {} : { list }) },
})

describe("return hooks read the task's list state", () => {
    it("lead back to the Review queue only for a record opened from it", () => {
        const opened = renderHook(() => useReviewBackPath("c 1"), {
            wrapper: wrapper(task("review", { route: "review.queue", search: "?status=approved&type=quest" })),
        })
        expect(opened.result.current).toBe("/app/c%201/review?status=approved&type=quest")
        const direct = renderHook(() => useReviewBackPath("c1"), { wrapper: wrapper(null) })
        expect(direct.result.current).toBeNull()
        const crafted = renderHook(() => useReviewBackPath("c1"), {
            wrapper: wrapper(task("review", { route: "review.queue", search: "//evil.example" })),
        })
        expect(crafted.result.current).toBeNull()
        const rejected = renderHook(() => useReviewBackPath("c1"), {
            wrapper: wrapper(task("review", { route: "review.queue", search: "?status=draft&redirect=/x" })),
        })
        expect(rejected.result.current).toBeNull()
    })

    it("return to the World browser as it was left, from any root's hand-off", () => {
        const back = renderHook(() => useWorldBackPath("c1"), {
            wrapper: wrapper(task("world", { route: "campaign.world", search: "?category=item" })),
        })
        expect(back.result.current).toBe("/app/c1/world?category=item")
        const none = renderHook(() => useWorldBackPath("c1"), { wrapper: wrapper(null) })
        expect(none.result.current).toBe("/app/c1/world")
        // Another root's list, another campaign's task, a query the browser does not produce: the plain address.
        for (const state of [
            task("review", { route: "review.queue", search: "?status=draft" }),
            task("world", { route: "campaign.world", search: "?category=item" }, "c2"),
            task("world", { route: "campaign.world", search: "?next=/elsewhere" }),
        ]) {
            const plain = renderHook(() => useWorldBackPath("c1"), { wrapper: wrapper(state) })
            expect(plain.result.current).toBe("/app/c1/world")
        }
    })

    it("pass the task on through a related link, and nothing after a direct entry", () => {
        const state = renderHook(() => useWorldReturnState(), {
            wrapper: wrapper(task("world", { route: "campaign.world", search: "?category=item" })),
        })
        expect(state.result.current?.task.root).toBe("world")
        expect(state.result.current?.task.list).toEqual({ route: "campaign.world", search: "?category=item" })
        const none = renderHook(() => useWorldReturnState(), { wrapper: wrapper(null) })
        expect(none.result.current).toBeUndefined()
    })

    it("still resolve an entry written before the task existed", () => {
        const back = renderHook(() => useWorldBackPath("c1"), {
            wrapper: wrapper({ worldSearch: "?category=item", reviewSearch: "?status=draft" }),
        })
        // The older keys adapt to the Review queue first (reviewSearch outranks worldSearch).
        expect(back.result.current).toBe("/app/c1/world")
        const review = renderHook(() => useReviewBackPath("c1"), {
            wrapper: wrapper({ worldSearch: "?category=item", reviewSearch: "?status=draft" }),
        })
        expect(review.result.current).toBe("/app/c1/review?status=draft")
        const world = renderHook(() => useWorldBackPath("c1"), { wrapper: wrapper({ worldSearch: "?category=item" }) })
        expect(world.result.current).toBe("/app/c1/world?category=item")
    })
})

describe("item return hooks", () => {
    it("keep the inventory and the definitions catalog apart", () => {
        const items = renderHook(() => useItemsBackPath("c1"), {
            wrapper: wrapper(task("items", { route: "items.list", search: "" }), ITEM),
        })
        expect(items.result.current).toBe("/app/c1/items")
        const definitions = renderHook(() => useDefinitionsBackPath("c1"), {
            wrapper: wrapper(task("items", { route: "itemDefinitions.list", search: "?category=weapon&homebrew=1" }), ITEM),
        })
        expect(definitions.result.current).toBe("/app/c1/item-definitions?category=weapon&homebrew=1")
        // A definitions list state is not the inventory's, and the reverse.
        const crossed = renderHook(() => useItemsBackPath("c1"), {
            wrapper: wrapper(task("items", { route: "itemDefinitions.list", search: "?category=weapon" }), ITEM),
        })
        expect(crossed.result.current).toBe("/app/c1/items")
        const direct = renderHook(() => useDefinitionsBackPath("c1"), { wrapper: wrapper(null, ITEM) })
        expect(direct.result.current).toBe("/app/c1/item-definitions")
    })
})
