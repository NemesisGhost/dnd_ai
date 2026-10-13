import { describe, expect, it } from "vitest"
import {
    defaultQuestSection,
    questEditBlockedText,
    questGuidance,
    questPhasesOf,
    questPlayBlockedText,
    questSectionsInPhase,
    questSectionsOf,
} from "./questPhases"

const status = (canon_status: string, lifecycle_status = "active") => ({ canon_status, lifecycle_status })

describe("questSectionsOf", () => {
    it("groups the sections into three workflow phases, in order", () => {
        const sections = questSectionsOf({ canPreview: false })
        expect(questPhasesOf(sections)).toEqual(["prepare", "publish", "play"])
        expect(questSectionsInPhase(sections, "prepare").map((s) => s.key)).toEqual([
            "details",
            "structure",
            "dependencies",
            "outcomes",
            "participants",
            "sources",
        ])
        expect(questSectionsInPhase(sections, "publish").map((s) => s.key)).toEqual(["review", "publication"])
        expect(questSectionsInPhase(sections, "play").map((s) => s.key)).toEqual(["progress"])
    })

    it("offers the member preview only to people who may preview a member", () => {
        expect(questSectionsOf({ canPreview: false }).some((s) => s.key === "preview")).toBe(false)
        const keys = questSectionsInPhase(questSectionsOf({ canPreview: true }), "play").map((s) => s.key)
        expect(keys).toEqual(["progress", "preview"])
    })

    it("never calls a workflow phase a stage, and never names a status", () => {
        for (const section of questSectionsOf({ canPreview: true })) {
            expect(section.label).not.toMatch(/phase/i)
        }
    })
})

describe("defaultQuestSection", () => {
    it("follows the lifecycle: where the next real step is done", () => {
        expect(defaultQuestSection(null)).toBe("details")
        expect(defaultQuestSection(status("draft"))).toBe("details")
        expect(defaultQuestSection(status("rejected"))).toBe("details")
        expect(defaultQuestSection(status("proposed"))).toBe("review")
        expect(defaultQuestSection(status("approved"))).toBe("review")
        expect(defaultQuestSection(status("canon"))).toBe("progress")
        expect(defaultQuestSection(status("superseded"))).toBe("publication")
        expect(defaultQuestSection(status("canon", "archived"))).toBe("publication")
        expect(defaultQuestSection(status("draft", "archived"))).toBe("publication")
    })
})

describe("questGuidance", () => {
    const view = (canon_status: string, available_actions: string[], over: object = {}) => ({
        ...status(canon_status),
        available_actions,
        superseded_by: null,
        ...over,
    })
    const draft = { canEdit: true, hasObjective: true }

    it("points at the step that is actually available, never at an action", () => {
        expect(questGuidance(view("draft", ["submit_for_review"]), draft)).toEqual({
            text: "Submit for review",
            target: { kind: "section", section: "publication" },
        })
        expect(questGuidance(view("proposed", ["approve", "reject"]), draft)?.text).toBe("Approve it")
        expect(questGuidance(view("approved", ["publish"]), draft)).toEqual({
            text: "Publish it",
            target: { kind: "section", section: "review" },
        })
        expect(questGuidance(view("rejected", ["return_to_draft"]), draft)?.text).toBe(
            "Return it to draft to rework it",
        )
        expect(questGuidance(view("canon", ["supersede"]), draft)).toEqual({
            text: "Run it",
            target: { kind: "section", section: "progress" },
        })
    })

    it("asks for stages and objectives while a draft has none, and only to someone who can add them", () => {
        const empty = { canEdit: true, hasObjective: false }
        expect(questGuidance(view("draft", ["submit_for_review"]), empty)).toEqual({
            text: "Add stages and objectives",
            target: { kind: "section", section: "structure" },
        })
        expect(questGuidance(view("draft", ["submit_for_review"]), { canEdit: false, hasObjective: false })?.text).toBe(
            "Submit for review",
        )
    })

    it("offers nothing when the server offers no step", () => {
        expect(questGuidance(view("proposed", []), draft)).toBeNull()
        expect(questGuidance(view("approved", []), draft)).toBeNull()
        expect(questGuidance(view("rejected", []), draft)).toBeNull()
        expect(questGuidance({ ...view("draft", []), lifecycle_status: "archived" }, draft)).toBeNull()
    })

    it("leads an archived quest to Restore, and a replaced one to its replacement", () => {
        expect(questGuidance({ ...view("canon", ["restore"]), lifecycle_status: "archived" }, draft)).toEqual({
            text: "Restore it",
            target: { kind: "section", section: "publication" },
        })
        expect(
            questGuidance(
                view("superseded", [], { superseded_by: { entity_id: "q2", canonical_name: "The Better Quest" } }),
                draft,
            ),
        ).toEqual({
            text: "Replaced by The Better Quest",
            target: { kind: "replacement", entityId: "q2" },
        })
        expect(questGuidance(view("superseded", []), draft)).toBeNull()
    })
})

describe("questPlayBlockedText", () => {
    it("is silent only for a published, active quest, and for an unknown status", () => {
        expect(questPlayBlockedText(status("canon"))).toBeNull()
        expect(questPlayBlockedText(null)).toBeNull()
    })

    it("explains every other state without promising a status", () => {
        expect(questPlayBlockedText(status("draft"))).toMatch(/not published yet/)
        expect(questPlayBlockedText(status("proposed"))).toMatch(/not published yet/)
        expect(questPlayBlockedText(status("approved"))).toMatch(/not published yet/)
        expect(questPlayBlockedText(status("rejected"))).toMatch(/not published yet/)
        expect(questPlayBlockedText(status("superseded"))).toMatch(/replaced/)
        expect(questPlayBlockedText(status("canon", "archived"))).toMatch(/archived/)
    })
})

describe("questEditBlockedText", () => {
    it("names the step a person can actually take", () => {
        expect(questEditBlockedText(status("proposed"))).toMatch(/Return it to draft/)
        expect(questEditBlockedText(status("approved"))).toMatch(/Return it to draft/)
        expect(questEditBlockedText(status("rejected"))).toMatch(/Return it to draft/)
        expect(questEditBlockedText(status("canon", "archived"))).toMatch(/Restore it/)
        expect(questEditBlockedText(status("superseded"))).toMatch(/replacement/)
        // Never advises a step that is not offered for an archived or replaced quest.
        expect(questEditBlockedText(status("canon", "archived"))).not.toMatch(/draft/)
        expect(questEditBlockedText(status("superseded"))).not.toMatch(/Return it to draft/)
    })
})
