import { act, renderHook } from "@testing-library/react"
import type { PropsWithChildren } from "react"
import { describe, expect, it, vi } from "vitest"
import { AnnouncerContext } from "../components/authoring/announcer"
import { useKnowledgeSaveReads } from "./useKnowledgeSaveReads"

interface Props {
  scope: string
  applied: { authoring: unknown; detail: unknown; lifecycle: unknown }
}

const NONE = { authoring: null, detail: null, lifecycle: null }

function setup(initial: Props = { scope: "a", applied: { ...NONE } }) {
  const announce = vi.fn()
  const wrapper = ({ children }: PropsWithChildren) => (
    <AnnouncerContext.Provider value={{ announce }}>{children}</AnnouncerContext.Provider>
  )
  const rendered = renderHook((props: Props) => useKnowledgeSaveReads(props), { initialProps: initial, wrapper })
  return { announce, ...rendered }
}

describe("useKnowledgeSaveReads", () => {
  it("reports ok and tracks nothing when every read was applied", () => {
    const { result, announce } = setup()
    let outcome = ""
    act(() => {
      outcome = result.current.open("claim", "Saved", { authoring: "ok", detail: "ok" })
    })
    expect(outcome).toBe("ok")
    expect(result.current.authoringHeld).toBe(false)
    expect(result.current.notice("claim")).toBeNull()
    expect(announce).not.toHaveBeenCalled()
  })

  it("holds only for the authoring read, and names only what is outstanding", () => {
    const { result } = setup()
    act(() => {
      result.current.open("claim", "Saved", { authoring: "ok", detail: "failed" })
    })
    expect(result.current.authoringHeld).toBe(false)
    expect(result.current.notice("claim")).toBe("Out of date: the claim's details.")
    expect(result.current.notice("lifecycle")).toBeNull()
    act(() => {
      result.current.open("lifecycle", "Approved", { lifecycle: "ok", authoring: "failed", detail: "ok" })
    })
    expect(result.current.authoringHeld).toBe(true)
    expect(result.current.notice("lifecycle")).toBe("Out of date: the claim's editor and version.")
  })

  it("is satisfied by a later applied read of the same resource, and announces done once", () => {
    const { result, announce, rerender } = setup()
    act(() => {
      result.current.open("claim", "Saved", { authoring: "failed", detail: "failed" })
    })
    rerender({ scope: "a", applied: { ...NONE, authoring: 7 } })
    expect(result.current.authoringHeld).toBe(false)
    expect(result.current.notice("claim")).toBe("Out of date: the claim's details.")
    expect(announce).not.toHaveBeenCalled()
    rerender({ scope: "a", applied: { ...NONE, authoring: 7, detail: {} } })
    expect(result.current.notice("claim")).toBeNull()
    expect(announce).toHaveBeenCalledTimes(1)
    expect(announce).toHaveBeenCalledWith("Saved")
    // Later reads of either resource do not announce it again.
    rerender({ scope: "a", applied: { ...NONE, authoring: 8, detail: {} } })
    rerender({ scope: "a", applied: { ...NONE, authoring: 8, detail: {} } })
    expect(announce).toHaveBeenCalledTimes(1)
  })

  it("never counts a read that failed again (a value that goes back to null) as applied", () => {
    const { result, announce, rerender } = setup({ scope: "a", applied: { ...NONE, authoring: 3 } })
    act(() => {
      result.current.open("claim", "Saved", { authoring: "failed", detail: "ok" })
    })
    rerender({ scope: "a", applied: { ...NONE, authoring: null } })
    expect(result.current.authoringHeld).toBe(true)
    expect(announce).not.toHaveBeenCalled()
  })

  it("forgets every save when the record, perspective or user changes", () => {
    const { result, announce, rerender } = setup()
    act(() => {
      result.current.open("claim", "Saved", { authoring: "failed", detail: "ok" })
    })
    rerender({ scope: "b", applied: { ...NONE } })
    expect(result.current.authoringHeld).toBe(false)
    rerender({ scope: "b", applied: { ...NONE, authoring: 9 } })
    expect(announce).not.toHaveBeenCalled()
  })
})
