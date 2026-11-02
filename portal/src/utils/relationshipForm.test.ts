import { describe, expect, it } from "vitest"
import { counterparts, readerCounterpartNames, readerRoleSentence, roleSummary } from "./relationshipForm"

const editor = [
    { entity_id: "a", name: "Aria", role_label: "Child" },
    { entity_id: "b", name: "Ser Bran", role_label: "Parent" },
]
const reader = (rows: Array<[string, string, boolean]>) =>
    rows.map(([name, role_label, is_self]) => ({ name, role_label, is_self }))

describe("editor summaries keep their wording", () => {
    it("names the opened record 'This record' by default", () => {
        expect(roleSummary(editor, "a")).toBe("This record: Child · Ser Bran: Parent")
        expect(counterparts(editor, "a")).toBe("Ser Bran")
        expect(counterparts([editor[0]!], "a")).toBe("Aria (this record)")
    })

    it("accepts another self label", () => {
        expect(roleSummary(editor, "a", "This character")).toBe("This character: Child · Ser Bran: Parent")
        expect(counterparts([editor[0]!], "a", "this character")).toBe("Aria (this character)")
    })
})

describe("readerRoleSentence", () => {
    it("reads an asymmetric relationship from the viewed character's side", () => {
        const people = reader([
            ["Ser Bran", "Parent", false],
            ["Aria", "Child", true],
        ])
        expect(readerRoleSentence(people, false)).toBe("Aria is Child · Ser Bran is Parent")
    })

    it("reads the same relationship from the other participant's side", () => {
        const people = reader([
            ["Ser Bran", "Parent", true],
            ["Aria", "Child", false],
        ])
        expect(readerRoleSentence(people, false)).toBe("Ser Bran is Parent · Aria is Child")
    })

    it("says 'Both are' for a symmetric type whose participants share a role", () => {
        const people = reader([
            ["Aria", "Ally", true],
            ["Ser Bran", "Ally", false],
        ])
        expect(readerRoleSentence(people, true)).toBe("Both are Ally")
    })

    it("names each role when a symmetric type's roles differ", () => {
        const people = reader([
            ["Aria", "Subject", true],
            ["Ser Bran", "Object", false],
        ])
        expect(readerRoleSentence(people, true)).toBe("Aria is Subject · Ser Bran is Object")
    })

    it("lists every participant of a multi-party relationship, the viewed character first", () => {
        const people = reader([
            ["Guild", "Other", false],
            ["Aria", "Subject", true],
            ["Keep", "Object", false],
        ])
        expect(readerRoleSentence(people, false)).toBe("Aria is Subject · Guild is Other · Keep is Object")
        const allies = reader([
            ["Aria", "Ally", true],
            ["Bran", "Ally", false],
            ["Cora", "Ally", false],
        ])
        expect(readerRoleSentence(allies, true)).toBe("All are Ally")
    })
})

describe("readerCounterpartNames", () => {
    it("joins the other participants", () => {
        const people = reader([
            ["Aria", "Ally", true],
            ["Bran", "Ally", false],
            ["Cora", "Ally", false],
        ])
        expect(readerCounterpartNames(people)).toBe("Bran and Cora")
    })

    it("names a self-relationship once", () => {
        expect(readerCounterpartNames(reader([["Aria", "Subject", true]]))).toBe("Aria (this character)")
    })
})
