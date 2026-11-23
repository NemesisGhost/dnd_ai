import { act, renderHook } from "@testing-library/react"
import type { PropsWithChildren } from "react"
import { describe, expect, it, vi } from "vitest"
import { AnnouncerContext } from "../components/authoring/announcer"
import { reportOutcome, useKnowledgeSaveReads } from "./useKnowledgeSaveReads"

interface Props {
  scope: string
  applied: { authoring: unknown; detail: unknown; lifecycle: unknown }
  closed: { authoring: boolean; lifecycle: boolean }
}

const NONE = { authoring: null, detail: null, lifecycle: null }
const OPEN = { authoring: false, lifecycle: false }
const props = (over: Partial<Props> = {}): Props => ({ scope: "a", applied: { ...NONE }, closed: OPEN, ...over })

function setup(initial: Props = props()) {
  const announce = vi.fn()
  const wrapper = ({ children }: PropsWithChildren) => (
    <AnnouncerContext.Provider value={{ announce }}>{children}</AnnouncerContext.Provider>
  )
  const rendered = renderHook((p: Props) => useKnowledgeSaveReads(p), { initialProps: initial, wrapper })
  return { announce, ...rendered }
}

const SAVED_BUT = "Saved, but the latest data could not be loaded."

describe("useKnowledgeSaveReads", () => {
  it("reports ok, announces a complete claim save once and tracks nothing", () => {
    const { result, announce } = setup()
    let outcome = ""
    act(() => {
      outcome = result.current.open("claim", "Saved", { authoring: "ok", detail: "ok" }, "a")
    })
    expect(outcome).toBe("ok")
    expect(result.current.authoringHeld).toBe(false)
    expect(result.current.notice("claim")).toBeNull()
    expect(announce).toHaveBeenCalledTimes(1)
    expect(announce).toHaveBeenCalledWith("Saved")
  })

  it("announces a complete lifecycle step once: the shared panel leaves that to the page (R2)", () => {
    const { result, announce } = setup()
    act(() => {
      expect(result.current.open("lifecycle", "Approved", { lifecycle: "ok", authoring: "ok", detail: "ok" }, "a")).toBe("ok")
    })
    expect(announce.mock.calls).toEqual([["Approved"]])
  })

  it("a lifecycle step says saved-but only for a failed read, once, and done once on recovery (R2)", () => {
    const { result, announce, rerender } = setup()
    act(() => {
      result.current.open("lifecycle", "Approved", { lifecycle: "ok", authoring: "superseded", detail: "ok" }, "a")
    })
    expect(announce).not.toHaveBeenCalled()
    act(() => result.current.observe({ authoring: "failed" }, "a"))
    expect(announce.mock.calls).toEqual([[SAVED_BUT]])
    rerender(props({ applied: { ...NONE, authoring: 4 } }))
    expect(announce.mock.calls).toEqual([[SAVED_BUT], ["Approved"]])
  })

  it("a lifecycle step whose authoring read is refused is done once, without saved-but (R2)", () => {
    const { result, announce, rerender } = setup(props({ closed: { authoring: true, lifecycle: false } }))
    act(() => {
      result.current.open("lifecycle", "Approved", { lifecycle: "ok", authoring: "failed", detail: "ok" }, "a")
    })
    rerender(props({ closed: { authoring: true, lifecycle: false } }))
    expect(announce.mock.calls).toEqual([["Approved"]])
  })

  it("holds only for the authoring read, and names only what is outstanding", () => {
    const { result } = setup()
    act(() => {
      result.current.open("claim", "Saved", { authoring: "ok", detail: "failed" }, "a")
    })
    expect(result.current.authoringHeld).toBe(false)
    expect(result.current.notice("claim")).toBe("Out of date: the claim's details.")
    expect(result.current.outstanding("claim")).toEqual(["detail"])
    expect(result.current.notice("lifecycle")).toBeNull()
    act(() => {
      result.current.open("lifecycle", "Approved", { lifecycle: "ok", authoring: "failed", detail: "ok" }, "a")
    })
    expect(result.current.authoringHeld).toBe(true)
    expect(result.current.notice("lifecycle")).toBe("Out of date: the claim's editor and version.")
  })

  it("says saved-but once for a claim save with a read to read again, and done once when it recovers", () => {
    const { result, announce, rerender } = setup()
    act(() => {
      result.current.open("claim", "Saved", { authoring: "failed", detail: "failed" }, "a")
    })
    expect(announce.mock.calls).toEqual([[SAVED_BUT]])
    rerender(props({ applied: { ...NONE, authoring: 7 } }))
    expect(result.current.authoringHeld).toBe(false)
    expect(result.current.notice("claim")).toBe("Out of date: the claim's details.")
    rerender(props({ applied: { ...NONE, authoring: 7, detail: {} } }))
    expect(result.current.notice("claim")).toBeNull()
    expect(announce.mock.calls).toEqual([[SAVED_BUT], ["Saved"]])
    // Later reads of either resource do not announce it again.
    rerender(props({ applied: { ...NONE, authoring: 8, detail: {} } }))
    rerender(props({ applied: { ...NONE, authoring: 8, detail: {} } }))
    expect(announce).toHaveBeenCalledTimes(2)
  })

  it("never counts a read that failed again (a value that goes back to null) as applied", () => {
    const { result, announce, rerender } = setup(props({ applied: { ...NONE, authoring: 3 } }))
    act(() => {
      result.current.open("claim", "Saved", { authoring: "failed", detail: "ok" }, "a")
    })
    rerender(props({ applied: { ...NONE, authoring: null } }))
    expect(result.current.authoringHeld).toBe(true)
    expect(announce).toHaveBeenCalledTimes(1)
  })

  it("treats a superseded read as pending: no notice, still held, resolved by the newer read's answer", () => {
    const { result, announce, rerender } = setup()
    act(() => {
      result.current.open("claim", "Saved", { authoring: "superseded", detail: "ok" }, "a")
    })
    expect(result.current.notice("claim")).toBeNull()
    expect(result.current.authoringHeld).toBe(true)
    expect(announce).not.toHaveBeenCalled()
    // The newer read failed: now it is outstanding.
    act(() => result.current.observe({ authoring: "failed" }, "a"))
    expect(result.current.notice("claim")).toBe("Out of date: the claim's editor and version.")
    // ... and the next one answered.
    act(() => result.current.observe({ authoring: "ok" }, "a"))
    rerender(props())
    expect(announce.mock.calls).toEqual([[SAVED_BUT], ["Saved"]])
  })

  it("a pending read is satisfied by the newer read being applied", () => {
    const { result, announce, rerender } = setup()
    act(() => {
      result.current.open("claim", "Saved", { authoring: "ok", detail: "superseded" }, "a")
    })
    rerender(props({ applied: { ...NONE, detail: {} } }))
    expect(result.current.notice("claim")).toBeNull()
    expect(announce.mock.calls).toEqual([["Saved"]])
  })

  it("a refusal is a result: it resolves the save, names nothing, and the write is announced once", () => {
    const { result, announce, rerender } = setup()
    act(() => {
      result.current.open("claim", "Saved", { authoring: "failed", detail: "ok" }, "a")
    })
    rerender(props({ closed: { authoring: true, lifecycle: false } }))
    expect(result.current.notice("claim")).toBeNull()
    expect(result.current.authoringHeld).toBe(false)
    expect(announce.mock.calls).toEqual([[SAVED_BUT], ["Saved"]])
  })

  it("a refusal known at the time of the save announces done without saying saved-but", () => {
    const { result, announce } = setup(props({ closed: { authoring: true, lifecycle: false } }))
    act(() => {
      expect(result.current.open("claim", "Saved", { authoring: "failed", detail: "ok" }, "a")).toBe("ok")
    })
    expect(announce.mock.calls).toEqual([["Saved"]])
  })

  it("a refused detail replaces the page: nothing is tracked, a save or a step is announced once", () => {
    const { result, announce } = setup()
    act(() => {
      expect(result.current.open("claim", "Saved", { authoring: "failed", detail: "closed" }, "a")).toBe("ok")
    })
    expect(result.current.authoringHeld).toBe(false)
    expect(result.current.notice("claim")).toBeNull()
    expect(announce.mock.calls).toEqual([["Saved"]])
    act(() => {
      expect(result.current.open("lifecycle", "Approved", { authoring: "ok", detail: "closed" }, "a")).toBe("ok")
    })
    expect(announce.mock.calls).toEqual([["Saved"], ["Approved"]])
  })

  it("forgets every save when the record, perspective or user changes (B18)", () => {
    const { result, announce, rerender } = setup()
    act(() => {
      result.current.open("claim", "Saved", { authoring: "failed", detail: "ok" }, "a")
    })
    announce.mockClear()
    rerender(props({ scope: "b" }))
    expect(result.current.authoringHeld).toBe(false)
    rerender(props({ scope: "b", applied: { ...NONE, authoring: 9 } }))
    expect(announce).not.toHaveBeenCalled()
  })

  it("ignores a save or a read that started under another scope (B16, B18)", () => {
    const { result, announce, rerender } = setup()
    rerender(props({ scope: "b" }))
    act(() => {
      // Confirmed under "a", answered after the page moved to "b": reported, but nothing is recorded or announced.
      expect(result.current.open("claim", "Saved", { authoring: "ok", detail: "ok" }, "a")).toBe("ok")
      expect(result.current.open("claim", "Saved", { authoring: "failed", detail: "ok" }, "a")).toBe("failed")
      result.current.observe({ authoring: "ok" }, "a")
    })
    expect(result.current.authoringHeld).toBe(false)
    expect(announce).not.toHaveBeenCalled()
  })

  it("announces nothing once the page has unmounted", () => {
    const { result, announce, unmount } = setup()
    const open = result.current.open
    unmount()
    expect(open("claim", "Saved", { authoring: "ok", detail: "ok" }, "a")).toBe("ok")
    expect(announce).not.toHaveBeenCalled()
  })

  it("reportOutcome: failed beats superseded beats ok; a refusal is not a failure", () => {
    expect(reportOutcome({ authoring: "ok", detail: "closed" })).toBe("ok")
    expect(reportOutcome({ authoring: "superseded", detail: "ok" })).toBe("superseded")
    expect(reportOutcome({ authoring: "superseded", detail: "failed" })).toBe("failed")
  })
})
