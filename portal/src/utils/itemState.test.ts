import { describe, expect, it } from "vitest"
import { conditionText, hasRecordedState, isPlaced, leavesText, ownerName, placementOf } from "./itemState"

const person = { entity_id: "n1", name: "Aldric", entity_type_code: "npc" }
const place = { entity_id: "l1", name: "Stonebridge", entity_type_code: "settlement" }
const chest = { entity_id: "c1", name: "Oak chest", entity_type_code: "item_instance" }

describe("item state wording", () => {
    const blank = {
        last_event_id: null as string | null,
        holder: null,
        container: null,
        location: null,
        owner: null,
        attuned_to: null,
        condition_percentage: null,
        quantity: 1,
        is_equipped: false,
        is_destroyed: false,
    }

    it("treats an item with nothing but the read model's defaults as having no recorded state", () => {
        expect(hasRecordedState(blank)).toBe(false)
    })

    it("counts a last event as recorded activity even when the item was left unplaced", () => {
        expect(hasRecordedState({ ...blank, last_event_id: "e5" })).toBe(true)
    })

    it("counts any fact that can exist only as a record, whatever the last-event token says", () => {
        expect(hasRecordedState({ ...blank, holder: person })).toBe(true)
        expect(hasRecordedState({ ...blank, location: place })).toBe(true)
        expect(hasRecordedState({ ...blank, owner: person })).toBe(true)
        expect(hasRecordedState({ ...blank, condition_percentage: 100 })).toBe(true)
        expect(hasRecordedState({ ...blank, quantity: 3 })).toBe(true)
        expect(hasRecordedState({ ...blank, is_destroyed: true })).toBe(true)
    })

    it("does not turn a missing condition into a number", () => {
        expect(conditionText(null)).toBe("No damage recorded")
        expect(conditionText(100)).toBe("100%")
        expect(conditionText(0)).toBe("0%")
    })

    it("names where an item is", () => {
        expect(placementOf({ holder: person, container: null, location: null })).toEqual({
            kind: "carried",
            text: "Carried by Aldric",
        })
        expect(placementOf({ holder: null, container: chest, location: null }).text).toBe("Inside Oak chest")
        expect(placementOf({ holder: null, container: null, location: place }).text).toBe("Lying at Stonebridge")
        expect(placementOf({ holder: null, container: null, location: null }).kind).toBe("unplaced")
        expect(isPlaced({ holder: null, container: null, location: place })).toBe(true)
        expect(isPlaced({ holder: null, container: null, location: null })).toBe(false)
    })

    it("says what taking an item out of its place means", () => {
        expect(leavesText({ holder: person, container: null, location: null })).toBe("Aldric will no longer carry it.")
        expect(leavesText({ holder: null, container: null, location: place })).toBe(
            "It will no longer lie at Stonebridge.",
        )
        expect(leavesText({ holder: null, container: chest, location: null })).toBe("It will be taken out of Oak chest.")
        expect(leavesText({ holder: null, container: null, location: null })).toBeNull()
    })

    it("never invents an owner", () => {
        expect(ownerName(null)).toBe("No owner recorded")
        expect(ownerName(person)).toBe("Aldric")
    })
})
