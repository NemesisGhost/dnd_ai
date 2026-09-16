import { describe, expect, it } from "vitest"
import type { CampaignQuestListItem } from "../types/quest"
import { sortQuests } from "./questSorting"

const quests: CampaignQuestListItem[] = [
    { quest_id: "q-2", name: "Banish the Wraith", status_code: "active" },
    { quest_id: "q-1", name: "Assemble the Council", status_code: null },
    { quest_id: "q-3", name: "Chart the Vale", status_code: "completed" },
]

describe("sortQuests", () => {
    it("sorts by name ascending", () => {
        expect(sortQuests(quests, "name", "asc").map((q) => q.name)).toEqual([
            "Assemble the Council",
            "Banish the Wraith",
            "Chart the Vale",
        ])
    })

    it("sorts by name descending", () => {
        expect(sortQuests(quests, "name", "desc").map((q) => q.name)).toEqual([
            "Chart the Vale",
            "Banish the Wraith",
            "Assemble the Council",
        ])
    })

    it("sorts by status ascending, with null status always last", () => {
        expect(
            sortQuests(quests, "status", "asc").map((q) => q.quest_id),
        ).toEqual(["q-2", "q-3", "q-1"])
    })

    it("sorts by status descending, with null status still last", () => {
        expect(
            sortQuests(quests, "status", "desc").map((q) => q.quest_id),
        ).toEqual(["q-3", "q-2", "q-1"])
    })

    it("does not mutate the input array", () => {
        const original = [...quests]
        sortQuests(quests, "name", "desc")
        expect(quests).toEqual(original)
    })

    it("returns an empty array unchanged", () => {
        expect(sortQuests([], "name", "asc")).toEqual([])
    })
})
