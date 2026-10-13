import { describe, expect, it } from "vitest"
import { recordPath, reviewTarget } from "./reviewTarget"
import type { ReviewRowIdentity } from "./reviewTarget"

const row = (over: Partial<ReviewRowIdentity> = {}): ReviewRowIdentity => ({
    entity_id: "e1",
    entity_type_code: "settlement",
    category: "location",
    canon_status: "proposed",
    lifecycle_status: "active",
    ...over,
})

describe("reviewTarget", () => {
    it("opens a World record in its workspace at the section where it is decided", () => {
        const target = reviewTarget("c1", row())
        expect(target).toEqual({ path: "/app/c1/world/location/e1?section=review", action: "Review", carriesReturn: true })
        expect(reviewTarget("c1", row({ canon_status: "approved" }))?.path).toBe("/app/c1/world/location/e1?section=review")
    })

    it.each([
        ["location", "dungeon"],
        ["location", "dungeon_area"],
        ["organization", "business"],
        ["religion", "religion"],
        ["character", "npc"],
        ["character", "player_character"],
    ])("sends a %s (%s) to the World workspace", (category, type) => {
        expect(reviewTarget("c1", row({ category, entity_type_code: type }))?.path).toBe(
            `/app/c1/world/${category}/e1?section=review`,
        )
    })

    it("opens a draft at its details and a rejected or archived record at Publication", () => {
        expect(reviewTarget("c1", row({ canon_status: "draft" }))).toMatchObject({
            path: "/app/c1/world/location/e1?section=details",
            action: "Open",
        })
        expect(reviewTarget("c1", row({ canon_status: "rejected" }))?.path).toBe("/app/c1/world/location/e1?section=publication")
        expect(reviewTarget("c1", row({ canon_status: "canon", lifecycle_status: "archived" }))?.path).toBe(
            "/app/c1/world/location/e1?section=publication",
        )
        expect(reviewTarget("c1", row({ canon_status: "superseded" }))?.path).toBe("/app/c1/world/location/e1?section=publication")
    })

    it("sends an item to its own workspace, which has no review section", () => {
        const item = { category: "item", entity_type_code: "item_instance" }
        expect(reviewTarget("c1", row(item))).toEqual({
            path: "/app/c1/items/e1?section=publication",
            action: "Review",
            carriesReturn: false,
        })
        expect(reviewTarget("c1", row({ ...item, canon_status: "draft" }))?.path).toBe("/app/c1/items/e1?section=details")
    })

    it("sends a knowledge claim to the sections the claim page already has", () => {
        const claim = { category: null, entity_type_code: "knowledge_item" }
        expect(reviewTarget("c1", row(claim))?.path).toBe("/app/c1/knowledge/e1?section=review")
        expect(reviewTarget("c1", row({ ...claim, canon_status: "draft" }))?.path).toBe("/app/c1/knowledge/e1?section=claim")
        expect(reviewTarget("c1", row({ ...claim, canon_status: "rejected" }))?.path).toBe(
            "/app/c1/knowledge/e1?section=publication",
        )
    })

    it("sends a quest to its edit page, which has no sections", () => {
        const quest = { category: null, entity_type_code: "quest" }
        expect(reviewTarget("c1", row(quest))).toEqual({
            path: "/app/c1/quests/e1/edit",
            action: "Review",
            carriesReturn: false,
        })
    })

    it("gives a record with no page of its own no target at all", () => {
        expect(reviewTarget("c1", row({ category: null, entity_type_code: "something_new" }))).toBeNull()
        expect(reviewTarget("c1", row({ category: "event", entity_type_code: "event" }))).toBeNull()
    })

    it("encodes identifiers", () => {
        expect(reviewTarget("c 1", row({ entity_id: "a/b" }))?.path).toBe("/app/c%201/world/location/a%2Fb?section=review")
    })
})

describe("recordPath", () => {
    it("leads the history page back to the record, including ones with no World page", () => {
        expect(recordPath("c1", "e1", "settlement", "location")).toBe("/app/c1/world/location/e1")
        expect(recordPath("c1", "e1", "quest", "record")).toBe("/app/c1/quests/e1/edit")
        expect(recordPath("c1", "e1", "knowledge_item", "record")).toBe("/app/c1/knowledge/e1")
        expect(recordPath("c1", "e1", "something_new", "record")).toBeNull()
    })
})
