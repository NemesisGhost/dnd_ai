import { describe, expect, it } from "vitest"
import { characterKindLabel, characterKindOfTypeCode } from "./characterKind"

describe("characterKind", () => {
    it("labels each kind in text", () => {
        expect(characterKindLabel("npc")).toBe("NPC")
        expect(characterKindLabel("player_character")).toBe("Player character")
        expect(characterKindLabel("character")).toBe("Character")
    })

    it("maps an entity type code, treating anything else as a bare character", () => {
        expect(characterKindOfTypeCode("npc")).toBe("npc")
        expect(characterKindOfTypeCode("player_character")).toBe("player_character")
        expect(characterKindOfTypeCode("character")).toBe("character")
        expect(characterKindOfTypeCode("location")).toBe("character")
    })
})
