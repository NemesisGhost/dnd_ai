import { describe, expect, it } from "vitest"
import { defaultItemSection, itemGuidance, itemSectionsOf, itemStageOf, parseItemSection } from "./itemStages"

const base = {
    canon_status: "canon",
    lifecycle_status: "active",
    available_actions: [] as string[],
    is_destroyed: false,
    holder: null,
    container: null,
    location: null,
    last_event_id: null,
}

describe("item stages", () => {
    it("assigns every section to a stage and parses only known sections", () => {
        expect(itemStageOf("sources")).toBe("prepare")
        expect(itemStageOf("publication")).toBe("publish")
        expect(itemStageOf("condition")).toBe("play")
        expect(itemSectionsOf("play").map((s) => s.key)).toEqual(["move", "equipment", "condition"])
        expect(parseItemSection("move")).toBe("move")
        expect(parseItemSection("who-knows")).toBeNull()
        expect(parseItemSection(null)).toBeNull()
    })

    it.each([
        [null, "details"],
        [{ canon_status: "draft", lifecycle_status: "active" }, "details"],
        [{ canon_status: "rejected", lifecycle_status: "active" }, "details"],
        [{ canon_status: "proposed", lifecycle_status: "active" }, "publication"],
        [{ canon_status: "approved", lifecycle_status: "active" }, "publication"],
        [{ canon_status: "superseded", lifecycle_status: "active" }, "publication"],
        [{ canon_status: "canon", lifecycle_status: "active" }, "move"],
        [{ canon_status: "canon", lifecycle_status: "archived" }, "publication"],
    ])("opens %j on %s", (status, section) => {
        expect(defaultItemSection(status)).toBe(section)
    })

    it("derives the next step only from the actions the server offers", () => {
        expect(itemGuidance({ ...base, canon_status: "draft", available_actions: ["submit_for_review"] })?.text).toBe(
            "Submit for review",
        )
        expect(itemGuidance({ ...base, canon_status: "draft", available_actions: [] })).toBeNull()
        expect(itemGuidance({ ...base, canon_status: "approved", available_actions: ["publish"] })?.section).toBe(
            "publication",
        )
        expect(
            itemGuidance({ ...base, canon_status: "rejected", available_actions: ["return_to_draft"] })?.text,
        ).toBe("Return it to draft to rework it")
        expect(itemGuidance({ ...base, lifecycle_status: "archived", available_actions: ["restore"] })?.text).toBe(
            "Restore it",
        )
        expect(itemGuidance({ ...base, canon_status: "superseded" })).toBeNull()
    })

    it("points a published, unplaced item to Give or place, and nothing otherwise", () => {
        expect(itemGuidance(base)).toEqual({ text: "Give it to someone or place it", section: "move" })
        expect(itemGuidance({ ...base, is_destroyed: true })).toBeNull()
        expect(
            itemGuidance({ ...base, holder: { entity_id: "n", name: "A", entity_type_code: "npc" } as never }),
        ).toBeNull()
    })
})
