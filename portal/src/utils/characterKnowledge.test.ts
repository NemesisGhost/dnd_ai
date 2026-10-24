import { describe, expect, it } from "vitest"
import type { KnowledgeDetail } from "../types/knowledge"
import { characterKnowledgeOf } from "./characterKnowledge"

const base: KnowledgeDetail = {
    knowledge_item_id: "k1",
    knowledge_type_code: "fact",
    statement: "A claim.",
    truth_status_code: null,
    sensitivity: null,
    awareness_level: null,
    confidence: null,
    willing_to_share: null,
}

describe("characterKnowledgeOf", () => {
    it("reports only the values the path's record holds", () => {
        const view = characterKnowledgeOf({
            ...base,
            character_knowledge: { path: "public", awareness_level: "aware", confidence: null, willing_to_share: null },
        })
        expect(view?.path).toBe("public")
        expect(view?.facts.map((fact) => fact.label)).toEqual(["Awareness"])
    })

    it("treats an explicit null as no knowledge path, even if the claim shows other fields", () => {
        expect(characterKnowledgeOf({ ...base, awareness_level: "aware", character_knowledge: null })).toBeNull()
    })

    it("falls back to the top-level fields only for a payload without the block", () => {
        expect(characterKnowledgeOf(base)).toBeNull()
        const legacy = characterKnowledgeOf({ ...base, confidence: 85 })
        expect(legacy?.path).toBeNull()
        expect(legacy?.facts).toEqual([{ key: "confidence", label: "Confidence", value: "85%" }])
    })
})
