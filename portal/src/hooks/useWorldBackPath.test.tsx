import { renderHook } from "@testing-library/react"
import type { ReactNode } from "react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import { pickWorldReturnState, useReviewBackPath, useWorldBackPath, useWorldReturnState } from "./useWorldBackPath"

const wrapper = (state: unknown) =>
    function Wrapper({ children }: { children: ReactNode }) {
        return <MemoryRouter initialEntries={[{ pathname: "/x", state }]}>{children}</MemoryRouter>
    }

describe("pickWorldReturnState", () => {
    it("keeps only well-formed query strings", () => {
        expect(pickWorldReturnState({ worldSearch: "?category=location", reviewSearch: "?status=draft" })).toEqual({
            worldSearch: "?category=location",
            reviewSearch: "?status=draft",
        })
        expect(pickWorldReturnState({ worldSearch: "http://evil.example", reviewSearch: 3 })).toBeUndefined()
        expect(pickWorldReturnState({ reviewSearch: "?status=draft", other: "x" })).toEqual({ reviewSearch: "?status=draft" })
        expect(pickWorldReturnState(null)).toBeUndefined()
        expect(pickWorldReturnState("?status=draft")).toBeUndefined()
    })
})

describe("return hooks", () => {
    it("lead back to the Review queue only for a record opened from it", () => {
        const opened = renderHook(() => useReviewBackPath("c 1"), { wrapper: wrapper({ reviewSearch: "?status=approved&type=quest" }) })
        expect(opened.result.current).toBe("/app/c%201/review?status=approved&type=quest")
        const direct = renderHook(() => useReviewBackPath("c1"), { wrapper: wrapper(null) })
        expect(direct.result.current).toBeNull()
        const crafted = renderHook(() => useReviewBackPath("c1"), { wrapper: wrapper({ reviewSearch: "//evil.example" }) })
        expect(crafted.result.current).toBeNull()
    })

    it("keep the World browser's return behaviour as it was", () => {
        const back = renderHook(() => useWorldBackPath("c1"), { wrapper: wrapper({ worldSearch: "?category=item", reviewSearch: "?status=draft" }) })
        expect(back.result.current).toBe("/app/c1/world?category=item")
        const state = renderHook(() => useWorldReturnState(), { wrapper: wrapper({ worldSearch: "?category=item", reviewSearch: "?status=draft" }) })
        expect(state.result.current).toEqual({ worldSearch: "?category=item" })
        const none = renderHook(() => useWorldBackPath("c1"), { wrapper: wrapper(null) })
        expect(none.result.current).toBe("/app/c1/world")
    })
})
