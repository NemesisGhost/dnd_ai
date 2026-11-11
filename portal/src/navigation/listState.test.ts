import { describe, expect, it } from "vitest"
import { hasListContract, isValidListSearch } from "./listState"
import { ROUTE_METAS } from "./routeMeta"

describe("list state contracts", () => {
    it("declares a contract for list routes that can be a task's list, and none for anything else", () => {
        for (const route of [
            "characters.index",
            "characters.browse",
            "campaign.world",
            "review.queue",
            "itemDefinitions.list",
            "items.list",
            "parties.list",
            "quests.list",
            "sessions.list",
            "knowledge.list",
            "worlds.timelines",
        ]) {
            expect(hasListContract(route), route).toBe(true)
        }
        for (const meta of ROUTE_METAS) {
            if (hasListContract(meta.id)) expect(meta.kind, meta.id).toBe("list")
        }
        expect(hasListContract("parties.detail")).toBe(false)
        expect(hasListContract("constructor")).toBe(false)
        expect(hasListContract("__proto__")).toBe(false)
    })

    it.each([
        ["characters.browse", ""],
        ["characters.browse", "?type=player_character&q=sella&hidden=1&cursor=abc&cursor=def"],
        ["campaign.world", `?${Array.from({ length: 40 }, (_, i) => `cursor=c${i}`).join("&")}`],
        ["campaign.world", "?category=location&q=old%20mill"],
        ["review.queue", "?status=in_review&type=knowledge_item"],
        ["itemDefinitions.list", "?category=weapon&homebrew=1"],
        ["parties.list", ""],
        ["quests.list", "?"],
    ])("accepts what %s produces: %s", (route, search) => {
        expect(isValidListSearch(route, search)).toBe(true)
    })

    it.each([
        ["characters.browse", "?type=dragon"],
        ["characters.browse", "?character_id=ch1"],
        ["characters.browse", "?party_id=p1&character_id=ch1"],
        ["campaign.world", "?category=npcs"],
        ["campaign.world", "?returnTo=%2Fapp%2Fother%2Fhome"],
        ["campaign.world", "?campaign=other"],
        ["campaign.world", "?q=a&q=b"],
        ["campaign.world", "?hidden=true"],
        ["campaign.world", `?q=${"x".repeat(201)}`],
        ["campaign.world", "?q=%00"],
        ["campaign.world", "?cursor=has%20space"],
        ["campaign.world", "?__proto__=1"],
        ["campaign.world", "no-question-mark"],
        ["review.queue", "?status=bogus"],
        ["review.queue", "?type=%3Cb%3E"],
        ["itemDefinitions.list", "?homebrew=0"],
        ["items.list", "?page=2"],
        ["quests.list", "?character_id=ch1&party_id=p1"],
        ["knowledge.list", "?party_id=p1"],
        ["characters.index", "?type=npc"],
        ["parties.detail", ""],
        ["nope", ""],
    ])("rejects %s with %s", (route, search) => {
        expect(isValidListSearch(route, search)).toBe(false)
    })
})
