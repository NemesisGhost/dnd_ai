import { describe, expect, it } from "vitest"
import {
    DESCRIPTION_MAX,
    NAME_MAX,
    REASON_MAX,
    fieldForErrorCode,
    validateDescription,
    validateLabel,
    validateName,
    validateReason,
    validateRulesetSelection,
} from "./authoringValidation"

describe("authoring validation mirrors", () => {
    it("requires a trimmed name of at most 200 characters", () => {
        expect(validateName("   ")).toBe("Name is required.")
        expect(validateName("x".repeat(NAME_MAX + 1))).toMatch(/200 characters/)
        expect(validateName("  ok  ")).toBeNull()
        expect(validateName("", "Timeline name")).toBe("Timeline name is required.")
    })

    it("bounds descriptions", () => {
        expect(validateDescription("")).toBeNull()
        expect(validateDescription("x".repeat(DESCRIPTION_MAX))).toBeNull()
        expect(validateDescription("x".repeat(DESCRIPTION_MAX + 1))).toMatch(/4000/)
    })

    it("requires a reason only when asked and bounds it", () => {
        expect(validateReason("  ", true)).toBe("A reason is required.")
        expect(validateReason("", false)).toBeNull()
        expect(validateReason("x".repeat(REASON_MAX + 1), false)).toMatch(/1000/)
    })

    it("requires a bounded label", () => {
        expect(validateLabel(" ")).toBe("A label is required.")
        expect(validateLabel("x".repeat(201))).toMatch(/200/)
        expect(validateLabel("The Fall")).toBeNull()
    })

    it("validates the ruleset selection", () => {
        expect(validateRulesetSelection([], "")).toMatch(/at least one/)
        expect(validateRulesetSelection(["a"], "b")).toMatch(/default ruleset/)
        expect(
            validateRulesetSelection(Array.from({ length: 11 }, (_, i) => `r${i}`), "r0"),
        ).toMatch(/at most 10/)
        expect(validateRulesetSelection(["a", "b"], "b")).toBeNull()
    })

    it("maps stable domain codes to fields", () => {
        expect(fieldForErrorCode("ruleset_not_available")).toBe("rulesets")
        expect(fieldForErrorCode("branch_point_invalid")).toBe("branch-point")
        expect(fieldForErrorCode("supersession_target_invalid")).toBe("replacement")
        expect(fieldForErrorCode("stale_write")).toBeNull()
        expect(fieldForErrorCode(null)).toBeNull()
    })
})
