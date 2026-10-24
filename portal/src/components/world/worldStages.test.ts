import { describe, expect, it } from "vitest"
import {
    LEGACY_SECTION_ALIASES,
    WORLD_STAGE_LABELS,
    defaultWorldSection,
    isWorkspaceCategory,
    playBlockedText,
    worldGuidance,
    worldKindOf,
    worldSectionsInStage,
    worldSectionsOf,
    worldStagesOf,
} from "./worldStages"
import type { WorldKind, WorldSection } from "./worldStages"

const keys = (kind: WorldKind): WorldSection[] => worldSectionsOf(kind).map((s) => s.key)

describe("worldKindOf", () => {
    it("tells the kinds of place apart by the entity type the lifecycle read reports", () => {
        expect(worldKindOf("location", "dungeon")).toBe("dungeon")
        expect(worldKindOf("location", "dungeon_area")).toBe("area")
        expect(worldKindOf("location", "settlement")).toBe("place")
        expect(worldKindOf("location", null)).toBe("place")
    })

    it("tells NPCs from player characters, and does not guess when the type is unknown", () => {
        expect(worldKindOf("character", "npc")).toBe("npc")
        expect(worldKindOf("character", "player_character")).toBe("pc")
        expect(worldKindOf("character", null)).toBe("character")
        expect(worldKindOf("character", "character")).toBe("character")
    })

    it("maps organizations and religions straight from their category", () => {
        expect(worldKindOf("organization", "business")).toBe("organization")
        expect(worldKindOf("religion", null)).toBe("religion")
    })
})

describe("workspace categories", () => {
    it("cover only the lifecycle-managed World categories that are not items or events", () => {
        expect(["location", "organization", "religion", "character"].every(isWorkspaceCategory)).toBe(true)
        expect(isWorkspaceCategory("item")).toBe(false)
        expect(isWorkspaceCategory("event")).toBe(false)
        expect(isWorkspaceCategory("relationship")).toBe(false)
    })
})

describe("stage labels", () => {
    it("name the work, never the words stage or phase", () => {
        for (const label of Object.values(WORLD_STAGE_LABELS)) {
            expect(label).not.toMatch(/stage|phase/i)
        }
    })
})

describe("sections by kind", () => {
    it("gives every kind the same review and publication sections", () => {
        for (const kind of ["place", "dungeon", "area", "organization", "religion", "npc", "pc", "character"] as const) {
            expect(keys(kind)).toEqual(expect.arrayContaining(["details", "sources", "relationships", "review", "publication"]))
        }
    })

    it("gives a dungeon Areas and Connections, in that order, and no other kind", () => {
        expect(keys("dungeon")).toEqual([
            "details",
            "areas",
            "connections",
            "sources",
            "relationships",
            "review",
            "publication",
        ])
        expect(keys("dungeon")).not.toContain("structure")
        for (const kind of ["place", "area", "organization", "religion", "npc", "pc", "character"] as const) {
            expect(keys(kind)).not.toContain("areas")
            expect(keys(kind)).not.toContain("connections")
        }
    })

    it("maps the old Structure address to Areas", () => {
        expect(LEGACY_SECTION_ALIASES).toEqual({ structure: "areas" })
    })

    it("offers Use in play only for the kinds the server lets you run", () => {
        expect(worldStagesOf("place")).toEqual(["prepare", "publish"])
        expect(worldStagesOf("dungeon")).toEqual(["prepare", "publish"])
        expect(worldStagesOf("religion")).toEqual(["prepare", "publish"])
        expect(worldSectionsInStage("area", "play").map((s) => s.key)).toEqual(["area-now"])
        expect(worldSectionsInStage("organization", "play").map((s) => s.key)).toEqual(["members"])
        expect(worldSectionsInStage("npc", "play").map((s) => s.key)).toEqual(["run", "inventory"])
        expect(worldSectionsInStage("pc", "play").map((s) => s.key)).toEqual(["player", "inventory"])
        expect(worldSectionsInStage("character", "play").map((s) => s.key)).toEqual(["inventory"])
    })

    it("keeps runtime sections out of kinds that cannot use them", () => {
        expect(keys("pc")).not.toContain("run")
        expect(keys("npc")).not.toContain("player")
        expect(keys("organization")).not.toContain("area-now")
        expect(keys("place")).not.toContain("area-now")
    })

    it("lists stages in order and each section under exactly one stage", () => {
        const stages = worldStagesOf("npc")
        expect(stages).toEqual(["prepare", "publish", "play"])
        const all = stages.flatMap((stage) => worldSectionsInStage("npc", stage).map((s) => s.key))
        expect(all.sort()).toEqual(keys("npc").sort())
    })
})

describe("defaultWorldSection", () => {
    const at = (canon_status: string, lifecycle_status = "active") => defaultWorldSection({ canon_status, lifecycle_status })

    it("opens the details when the status is unknown or the record is being authored", () => {
        expect(defaultWorldSection(null)).toBe("details")
        expect(at("draft")).toBe("details")
        expect(at("rejected")).toBe("details")
        expect(at("canon")).toBe("details")
    })

    it("opens Review for a record waiting for a decision", () => {
        expect(at("proposed")).toBe("review")
        expect(at("approved")).toBe("review")
    })

    it("opens Publication for an archived or replaced record, whatever its canon status", () => {
        expect(at("canon", "archived")).toBe("publication")
        expect(at("draft", "archived")).toBe("publication")
        expect(at("superseded")).toBe("publication")
    })
})

describe("worldGuidance", () => {
    const guide = (canon_status: string, available_actions: string[], lifecycle_status = "active") =>
        worldGuidance({ canon_status, lifecycle_status, available_actions })

    it("names only a step the server actually offers", () => {
        expect(guide("draft", ["submit_for_review"])).toEqual({ text: "Submit for review", section: "review" })
        expect(guide("proposed", ["approve", "reject", "return_to_draft"])).toEqual({ text: "Approve it", section: "review" })
        expect(guide("approved", ["publish", "return_to_draft"])).toEqual({ text: "Publish it", section: "review" })
        expect(guide("rejected", ["return_to_draft"])).toEqual({
            text: "Return it to draft to rework it",
            section: "publication",
        })
        expect(guide("canon", ["archive", "supersede"], "active")).toBeNull()
    })

    it("offers nothing when the person is not offered the step", () => {
        expect(guide("proposed", [])).toBeNull()
        expect(guide("draft", [])).toBeNull()
    })

    it("offers Restore for an archived record and nothing for a replaced one", () => {
        expect(guide("canon", ["restore"], "archived")).toEqual({ text: "Restore it", section: "publication" })
        expect(guide("canon", [], "archived")).toBeNull()
        expect(guide("superseded", ["archive"])).toBeNull()
    })
})

describe("playBlockedText", () => {
    it("explains why recording what happens is not offered yet", () => {
        expect(playBlockedText({ canon_status: "draft", lifecycle_status: "active" }, "area")).toMatch(/not published yet/)
        expect(playBlockedText({ canon_status: "proposed", lifecycle_status: "active" }, "area")).toMatch(/not published yet/)
        expect(playBlockedText({ canon_status: "canon", lifecycle_status: "archived" }, "area")).toMatch(/archived/)
        expect(playBlockedText({ canon_status: "superseded", lifecycle_status: "active" }, "organization")).toMatch(/replaced/)
    })

    it("says nothing for a published, active record or when the status is unknown", () => {
        expect(playBlockedText({ canon_status: "canon", lifecycle_status: "active" }, "area")).toBeNull()
        expect(playBlockedText(null, "area")).toBeNull()
    })
})
