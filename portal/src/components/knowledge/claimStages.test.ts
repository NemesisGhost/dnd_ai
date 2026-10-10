import { describe, expect, it } from "vitest"
import type { EntityLifecycleView } from "../../types/entityLifecycle"
import {
    CLAIM_SECTIONS,
    CLAIM_STAGES,
    claimGuidance,
    claimSectionsOf,
    claimStageOf,
    defaultClaimSection,
    parseClaimSection,
} from "./claimStages"

const lifecycle = (extra: Partial<EntityLifecycleView> = {}): EntityLifecycleView => ({
    entity_id: "k1",
    entity_type_code: "knowledge_item",
    canonical_name: "x",
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 1,
    lifecycle_managed: true,
    superseded_by: null,
    available_actions: [],
    blocked_actions: [],
    ...extra,
})

describe("claim stages", () => {
    it("groups the sections under the three stages in order", () => {
        expect(CLAIM_STAGES.map((s) => s.label)).toEqual(["Prepare", "Review & publish", "Use in play"])
        expect(claimSectionsOf("prepare").map((s) => s.key)).toEqual(["claim", "sources"])
        expect(claimSectionsOf("review").map((s) => s.key)).toEqual(["review", "publication"])
        expect(claimSectionsOf("use").map((s) => s.key)).toEqual(["who-knows", "character"])
        expect(CLAIM_SECTIONS).toHaveLength(6)
        expect(claimStageOf("publication")).toBe("review")
    })

    it("accepts only known section keys", () => {
        expect(parseClaimSection("who-knows")).toBe("who-knows")
        expect(parseClaimSection("bogus")).toBeNull()
        expect(parseClaimSection("")).toBeNull()
        expect(parseClaimSection(null)).toBeNull()
    })

    it.each([
        ["draft", "active", "claim"],
        ["rejected", "active", "claim"],
        ["proposed", "active", "review"],
        ["approved", "active", "review"],
        ["canon", "active", "who-knows"],
        ["superseded", "active", "who-knows"],
        ["deprecated", "active", "claim"],
        ["draft", "archived", "publication"],
        ["canon", "archived", "publication"],
    ])("opens a %s / %s claim at %s", (canon, lifecycleStatus, expected) => {
        expect(defaultClaimSection(lifecycle({ canon_status: canon, lifecycle_status: lifecycleStatus }))).toBe(expected)
    })

    it("opens the claim when the lifecycle is not known", () => {
        expect(defaultClaimSection(null)).toBe("claim")
    })
})

describe("claim guidance", () => {
    const section = (text: string, key: string) => ({ text, target: { kind: "section", section: key } })

    it.each([
        [{ canon_status: "canon", lifecycle_status: "archived", available_actions: ["restore"] }, section("Restore it to use it in play", "publication")],
        [{ canon_status: "draft", lifecycle_status: "archived", available_actions: ["restore"] }, section("Restore it, then continue review", "publication")],
        [{ canon_status: "approved", available_actions: ["publish", "return_to_draft"] }, section("Publish as canon", "publication")],
        [{ canon_status: "proposed", available_actions: ["approve", "return_to_draft", "reject"] }, section("Approve", "review")],
        [{ canon_status: "draft", available_actions: ["submit_for_review", "archive"] }, section("Submit for review", "publication")],
        [{ canon_status: "rejected", available_actions: ["return_to_draft", "archive"] }, section("Return it to draft to rework it", "publication")],
        [{ canon_status: "canon", available_actions: ["supersede", "archive"] }, section("Record who knows it", "who-knows")],
    ])("guides %j", (view, expected) => {
        expect(claimGuidance(lifecycle(view))).toEqual(expected)
    })

    it("blames the subject, not the claim, when an approved claim's subject is not published (D1)", () => {
        const guidance = claimGuidance(
            lifecycle({
                canon_status: "approved",
                available_actions: ["return_to_draft"],
                blocked_actions: [{ action: "publish", reason: "reference_not_published" }],
            }),
        )
        expect(guidance).toEqual({ text: "Publish its subject first", target: { kind: "subject" } })
    })

    it("does not blame the subject for any other blocker", () => {
        expect(
            claimGuidance(
                lifecycle({
                    canon_status: "approved",
                    available_actions: ["return_to_draft"],
                    blocked_actions: [{ action: "publish", reason: "quest_definition_incomplete" }],
                }),
            ),
        ).toBeNull()
    })

    it("points a superseded claim at its replacement, and archive alone is not a next step (D2)", () => {
        expect(
            claimGuidance(
                lifecycle({
                    canon_status: "superseded",
                    available_actions: ["archive"],
                    superseded_by: { entity_id: "k2", canonical_name: "The newer claim" },
                }),
            ),
        ).toEqual({ text: "Replaced by The newer claim", target: { kind: "replacement", entityId: "k2" } })
    })

    it("claims nothing when the person has no step", () => {
        expect(claimGuidance(lifecycle({ canon_status: "draft", available_actions: [] }))).toBeNull()
        expect(claimGuidance(lifecycle({ canon_status: "proposed", available_actions: [] }))).toBeNull()
        expect(claimGuidance(lifecycle({ canon_status: "draft", lifecycle_status: "archived", available_actions: [] }))).toBeNull()
        expect(claimGuidance(lifecycle({ canon_status: "deprecated", available_actions: [] }))).toBeNull()
    })
})
