import { describe, expect, it, vi } from "vitest"
import { LabelRegistry, MAX_LABEL_LENGTH, labelKey } from "./labelRegistry"

describe("labelKey", () => {
    it("is the route and its parameters, independent of parameter order", () => {
        expect(labelKey("parties.detail", { campaignId: "c1", partyId: "p1" })).toBe(
            labelKey("parties.detail", { partyId: "p1", campaignId: "c1" }),
        )
        expect(labelKey("parties.detail", { campaignId: "c1", partyId: "p1" })).not.toBe(
            labelKey("parties.detail", { campaignId: "c1", partyId: "p2" }),
        )
        expect(labelKey("parties.detail", { campaignId: "c1", partyId: "p1" })).not.toBe(
            labelKey("parties.edit", { campaignId: "c1", partyId: "p1" }),
        )
    })
})

describe("LabelRegistry", () => {
    it("holds a registered label and notifies subscribers once per change", () => {
        const registry = new LabelRegistry()
        const listener = vi.fn()
        registry.subscribe(listener)
        expect(registry.register("k", "Lantern Company")).toBe(true)
        expect(registry.labelFor("k")).toBe("Lantern Company")
        expect(listener).toHaveBeenCalledTimes(1)
        // The same label again changes nothing and renders nothing.
        expect(registry.register("k", "Lantern Company")).toBe(true)
        expect(listener).toHaveBeenCalledTimes(1)
    })

    it("rejects non-strings and blank names, and cleans control characters and length", () => {
        const registry = new LabelRegistry()
        expect(registry.register("a", undefined)).toBe(false)
        expect(registry.register("b", 42)).toBe(false)
        expect(registry.register("c", "   \t\n ")).toBe(false)
        expect(registry.register("d", "Two\u0000  lines\nhere")).toBe(true)
        expect(registry.labelFor("d")).toBe("Two lines here")
        expect(registry.register("e", "x".repeat(MAX_LABEL_LENGTH + 50))).toBe(true)
        expect(registry.labelFor("e")).toHaveLength(MAX_LABEL_LENGTH)
        expect(registry.labelFor("a")).toBeUndefined()
    })

    it("forgets one label", () => {
        const registry = new LabelRegistry()
        registry.register("a", "A")
        registry.register("b", "B")
        registry.forget("a")
        expect(registry.labelFor("a")).toBeUndefined()
        expect(registry.labelFor("b")).toBe("B")
    })

    it("once closed holds nothing and ignores every later write", () => {
        const registry = new LabelRegistry()
        registry.register("a", "A")
        registry.close()
        expect(registry.labelFor("a")).toBeUndefined()
        expect(registry.register("a", "A again")).toBe(false)
        expect(registry.labelFor("a")).toBeUndefined()
        expect(registry.open).toBe(false)
    })

    it("a StrictMode-style close then activate of the current registry accepts writes again", () => {
        const registry = new LabelRegistry()
        registry.close()
        registry.activate()
        expect(registry.register("a", "A")).toBe(true)
    })
})
