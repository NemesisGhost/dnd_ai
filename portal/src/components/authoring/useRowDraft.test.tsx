import { act, renderHook } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { useRowDraft } from "./useRowDraft"

const row = (description: string) => ({ description })

describe("useRowDraft", () => {
    it("follows the server while untouched, and reports a conflict only for a dirty draft", () => {
        const { result, rerender } = renderHook(({ server }) => useRowDraft(server), {
            initialProps: { server: row("a") },
        })
        rerender({ server: row("b") })
        expect(result.current.values.description).toBe("b")
        act(() => result.current.setValues(row("mine")))
        expect(result.current.dirty).toBe(true)
        rerender({ server: row("theirs") })
        expect(result.current.conflict).toBe(true)
        expect(result.current.values.description).toBe("mine")
    })

    it("accept makes the sent values the clean baseline even if the server is not read again", () => {
        const { result, rerender } = renderHook(({ server }) => useRowDraft(server), {
            initialProps: { server: row("a") },
        })
        act(() => result.current.setValues(row("sent")))
        act(() => result.current.accept(row("sent")))
        expect(result.current.dirty).toBe(false)
        expect(result.current.conflict).toBe(false)
        // The server is still the old row (the read after the save failed): the accepted values stay.
        rerender({ server: row("a") })
        expect(result.current.values.description).toBe("sent")
        expect(result.current.dirty).toBe(false)
        // Typing again is a new edit against the accepted values, not a conflict with the old row.
        act(() => result.current.setValues(row("more")))
        expect(result.current.dirty).toBe(true)
        expect(result.current.conflict).toBe(false)
        // When the server does answer, an untouched draft follows it again.
        act(() => result.current.setValues(row("sent")))
        rerender({ server: row("sent") })
        expect(result.current.values.description).toBe("sent")
        rerender({ server: row("changed later") })
        expect(result.current.values.description).toBe("changed later")
    })
})
