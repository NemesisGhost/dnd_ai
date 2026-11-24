import { describe, expect, it } from "vitest"
import {
    confirmFromRoles,
    describeChange,
    draftAfterSave,
    isDirty,
    knownRoles,
    ledgerText,
    mayHaveBeenSent,
    saveSentence,
    stagedChanges,
} from "./systemRoleStaging"
import type { LedgerStep } from "./systemRoleStaging"

describe("stagedChanges", () => {
    it("is empty when the draft matches the baseline, whatever the order", () => {
        expect(stagedChanges(["player", "gm"], ["gm", "player"])).toEqual([])
    })

    it("lists grants first, then removals, each in option order", () => {
        expect(stagedChanges(["admin", "player"], ["gm", "observer"])).toEqual([
            { code: "gm", action: "add" },
            { code: "observer", action: "add" },
            { code: "admin", action: "remove" },
            { code: "player", action: "remove" },
        ])
    })

    it("sends the signed-in account's own Administrator removal last", () => {
        expect(stagedChanges(["admin", "player"], ["observer"], true)).toEqual([
            { code: "observer", action: "add" },
            { code: "player", action: "remove" },
            { code: "admin", action: "remove" },
        ])
    })

    it("does not move an Administrator removal for another account", () => {
        expect(stagedChanges(["admin", "player"], ["observer"], false).map((c) => c.code)).toEqual([
            "observer",
            "admin",
            "player",
        ])
    })

    it("ignores role codes it does not know", () => {
        expect(stagedChanges(["legacy"], ["legacy", "player"])).toEqual([{ code: "player", action: "add" }])
    })
})

describe("isDirty and describeChange", () => {
    it("reports a difference only", () => {
        expect(isDirty(["player"], ["player"])).toBe(false)
        expect(isDirty(["player"], [])).toBe(true)
    })

    it("names a change with the option label", () => {
        expect(describeChange({ code: "gm", action: "add" })).toBe("Add Game master")
        expect(describeChange({ code: "player", action: "remove" })).toBe("Remove Player")
    })

    it("keeps known roles in option order", () => {
        expect(knownRoles(["observer", "legacy", "admin"])).toEqual(["admin", "observer"])
    })
})

describe("ledger helpers", () => {
    const step = (code: "gm" | "player", action: "add" | "remove", result: LedgerStep["result"]): LedgerStep => ({
        change: { code, action },
        result,
    })

    it("words each result without ever implying the changes were applied together", () => {
        expect(ledgerText(step("gm", "add", "saved"))).toBe("Game master added")
        expect(ledgerText(step("player", "remove", "already"))).toBe("Already did not have Player")
        expect(ledgerText(step("player", "add", "already"))).toBe("Already had Player")
        expect(ledgerText(step("gm", "add", "not_sent"))).toBe("Add Game master: not sent.")
        expect(ledgerText({ ...step("gm", "remove", "saved"), strandedWorlds: 2 })).toBe(
            "Game master removed. 2 world(s) this account owns now have no manageable Owner.",
        )
    })

    it("counts already-so and confirmed as saved in the one sentence", () => {
        expect(
            saveSentence([
                step("gm", "add", "saved"),
                step("player", "remove", "already"),
                step("gm", "add", "refused"),
                step("gm", "add", "not_confirmed"),
                step("gm", "add", "not_sent"),
                step("gm", "add", "confirmed"),
            ]),
        ).toBe("3 of 6 changes saved. 1 refused. 1 could not be confirmed. 1 not sent.")
    })

    it("confirms an unsettled step only when the current roles show it, and drops only refused ones from the draft", () => {
        const ledger = [
            step("gm", "add", "not_confirmed"),
            step("player", "remove", "not_sent"),
            step("gm", "add", "refused"),
        ]
        const settled = confirmFromRoles(ledger, ["player", "gm"])
        expect(settled.map((s) => s.result)).toEqual(["confirmed", "not_sent", "refused"])
        // The draft is the current roles plus every intended change that was not refused.
        expect(draftAfterSave(["player"], [step("gm", "add", "refused")])).toEqual(["player"])
        expect(draftAfterSave(["player"], [step("gm", "add", "not_sent")])).toEqual(["gm", "player"])
        expect(mayHaveBeenSent([step("gm", "add", "refused"), step("gm", "add", "not_sent")])).toBe(false)
        expect(mayHaveBeenSent([step("gm", "add", "not_confirmed")])).toBe(true)
    })
})
