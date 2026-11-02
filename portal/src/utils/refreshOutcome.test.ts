import { describe, expect, it } from "vitest"
import { bootstrapRefreshOutcome, combineRefetchOutcomes } from "./refreshOutcome"

describe("combineRefetchOutcomes", () => {
    it("is ok only when every read was applied", () => {
        expect(combineRefetchOutcomes(["ok", "ok"])).toBe("ok")
        expect(combineRefetchOutcomes([])).toBe("ok")
    })

    it("is failed when any read failed, even beside a superseded one", () => {
        expect(combineRefetchOutcomes(["ok", "failed"])).toBe("failed")
        expect(combineRefetchOutcomes(["superseded", "failed", "ok"])).toBe("failed")
    })

    it("is superseded when a newer read will answer and none failed", () => {
        expect(combineRefetchOutcomes(["ok", "superseded"])).toBe("superseded")
    })
})

describe("bootstrapRefreshOutcome", () => {
    it("maps applied, ended-session and rejected reads", async () => {
        expect(await bootstrapRefreshOutcome(async () => true)).toBe("ok")
        expect(await bootstrapRefreshOutcome(async () => false)).toBe("superseded")
        expect(await bootstrapRefreshOutcome(async () => Promise.reject(new Error("x")))).toBe("failed")
    })
})
