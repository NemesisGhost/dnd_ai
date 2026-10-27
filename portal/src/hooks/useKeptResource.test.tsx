import { renderHook } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import type { AuthoringResourceState } from "./useAuthoringResource"
import { useKept } from "./useKeptResource"

type S = AuthoringResourceState<{ name: string }>
const ready = (name: string): S => ({ kind: "ready", data: { name }, refreshing: false })

describe("useKept", () => {
    it("keeps the last read through a recoverable failure and drops it when denied or gone", () => {
        const { result, rerender } = renderHook(({ state }: { state: S }) => useKept(state, "/a"), {
            initialProps: { state: ready("One") },
        })
        expect(result.current).toEqual({ name: "One" })
        rerender({ state: { kind: "error", retryable: true } })
        expect(result.current).toEqual({ name: "One" })
        rerender({ state: { kind: "denied" } })
        expect(result.current).toBeNull()
        rerender({ state: { kind: "error", retryable: true } })
        expect(result.current).toBeNull()
    })

    it("never shows the previous record when the next one fails", () => {
        const { result, rerender } = renderHook(
            ({ state, scope }: { state: S; scope: string }) => useKept(state, scope),
            { initialProps: { state: ready("One"), scope: "/records/1" } },
        )
        expect(result.current).toEqual({ name: "One" })
        rerender({ state: { kind: "loading" }, scope: "/records/2" })
        rerender({ state: { kind: "error", retryable: true }, scope: "/records/2" })
        expect(result.current).toBeNull()
    })
})
