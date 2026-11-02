import { screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { CAMPAIGN_ONLY_RECORD_AUTHORING } from "../../test/recordAuthoring"
import { setupQuestWorkspace } from "../../test/questWorkspaceHarness"

afterEach(() => {
    vi.unstubAllGlobals()
})

// A quest is a definition (shared world canon) and progress (this campaign's state). The campaign
// GM with no world role is covered in App.scopedRoles.test.tsx (it needs the full session shell).

const published = {
    authoring: CAMPAIGN_ONLY_RECORD_AUTHORING,
    quest_id: "q1",
    name: "The Lost Amulet",
    status_code: "active",
    stages: [
        {
            quest_stage_id: "s1",
            name: "Opening",
            description: null,
            sequence_number: 1,
            stage_type: "sequential",
            objectives: [],
        },
    ],
}

describe("Quest page for a world Editor", () => {
    it("opens the workspace, which reads the definition", async () => {
        const { server } = setupQuestWorkspace({ section: "details" })
        server.on("GET", "/campaigns/c1/quests/q1", { body: published })
        expect(await screen.findByRole("heading", { level: 1, name: "The Lost Amulet" })).toBeInTheDocument()
        expect(server.calls.some((c) => /\/authoring\/quests\/q1$/.test(c.path))).toBe(true)
    })
})
