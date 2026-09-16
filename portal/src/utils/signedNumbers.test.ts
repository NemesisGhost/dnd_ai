import {
    describe,
    expect,
    it,
} from "vitest"
import formatSignedNumber from "./signedNumbers"

describe("formatSignedNumber", () => {
    it("returns a fallback string for null", () => {
        expect(formatSignedNumber(null)).toBe("Not available")
    })

    it("prefixes positive values with a plus sign", () => {
        expect(formatSignedNumber(5)).toBe("+5")
        expect(formatSignedNumber(1)).toBe("+1")
    })

    it("does not prefix zero", () => {
        expect(formatSignedNumber(0)).toBe("0")
    })

    it("does not add an extra sign for negative values", () => {
        expect(formatSignedNumber(-5)).toBe("-5")
        expect(formatSignedNumber(-1)).toBe("-1")
    })
})
