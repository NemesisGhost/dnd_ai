import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { AwardItemSection } from "./AwardItemSection"

afterEach(() => {
    vi.unstubAllGlobals()
})

const PARTICIPANTS = [
    {
        session_participant_id: "sp1",
        character_id: "n1",
        character_name: "Aldric",
        participation_role: "player_character" as const,
        added_at: "2026-01-01T00:00:00Z",
        removed_at: null,
    },
    {
        session_participant_id: "sp2",
        character_id: "n2",
        character_name: "Gone",
        participation_role: "npc" as const,
        added_at: "2026-01-01T00:00:00Z",
        removed_at: "2026-01-02T00:00:00Z",
    },
]

const ITEM = (id: string, name: string, overrides: object = {}) => ({
    item_instance_id: id,
    name,
    definition_name: "Longsword",
    category_label: "Weapon",
    canon_status: "canon",
    lifecycle_status: "active",
    holder_name: null,
    is_destroyed: false,
    ...overrides,
})

function setup(items: object[]) {
    const server = installMockServer()
    server.on("GET", "/campaigns/c1/authoring/items", { body: { items } })
    server.on("GET", "/campaigns/c1/authoring/items/i1", { body: { last_event_id: "e9" } })
    server.on("POST", "/campaigns/c1/items/i1/award", { body: { changed: true } })
    renderAuthoringRoutes({
        initialEntry: "/app/c1/run",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1" }],
        }),
        routes: [
            {
                path: "/app/:campaignId/run",
                element: <AwardItemSection campaignId="c1" participants={PARTICIPANTS} />,
            },
        ],
    })
    return server
}

describe("AwardItemSection", () => {
    it("offers only published, unplaced, intact items", async () => {
        setup([
            ITEM("i1", "Free Sword"),
            ITEM("i2", "Carried", { holder_name: "Bryn" }),
            ITEM("i3", "Draft", { canon_status: "draft" }),
            ITEM("i4", "Broken", { is_destroyed: true }),
        ])
        const select = await screen.findByRole("combobox", { name: "Item" })
        const options = within(select).getAllByRole("option").map((o) => o.textContent)
        expect(options).toEqual(["Choose an item", "Free Sword (Longsword)"])
        const who = within(screen.getByRole("combobox", { name: "Award to" }))
            .getAllByRole("option")
            .map((o) => o.textContent)
        expect(who).toEqual(["Choose who receives it", "Aldric"])
    })

    it("reads the item's token just before awarding it", async () => {
        const server = setup([ITEM("i1", "Free Sword")])
        fireEvent.change(await screen.findByRole("combobox", { name: "Item" }), { target: { value: "i1" } })
        fireEvent.change(screen.getByRole("combobox", { name: "Award to" }), { target: { value: "n1" } })
        fireEvent.click(screen.getByRole("button", { name: "Award item" }))
        await vi.waitFor(() => expect(server.callsTo("POST", "/campaigns/c1/items/i1/award")).toHaveLength(1))
        expect(server.callsTo("POST", "/campaigns/c1/items/i1/award")[0]!.body).toEqual({
            expected_last_event_id: "e9",
            holder_entity_id: "n1",
        })
    })

    it("needs both choices", async () => {
        const server = setup([ITEM("i1", "Free Sword")])
        await screen.findByRole("combobox", { name: "Item" })
        fireEvent.click(screen.getByRole("button", { name: "Award item" }))
        expect(await screen.findByText(/Choose an item and who receives it/)).toBeInTheDocument()
        expect(server.callsTo("POST", "/campaigns/c1/items/i1/award")).toHaveLength(0)
    })

    it("says when nothing is waiting", async () => {
        setup([ITEM("i2", "Carried", { holder_name: "Bryn" })])
        expect(await screen.findByText(/No published item is waiting/)).toBeInTheDocument()
    })

    describe("an award whose answer was lost", () => {
        const AWARD = "/campaigns/c1/items/i1/award"
        const TOKEN = "/campaigns/c1/authoring/items/i1"

        // The server applies the first award, so the item's token moves on, but the answer never arrives.
        function lostAnswer() {
            const server = setup([ITEM("i1", "Free Sword")])
            let token = "e9"
            let posts = 0
            server.on("GET", TOKEN, () => ({ body: { last_event_id: token } }))
            server.on("POST", AWARD, () => {
                posts += 1
                if (posts === 1) {
                    token = "e10"
                    return { networkError: true }
                }
                return { body: { changed: true } }
            })
            return server
        }

        async function award() {
            fireEvent.change(await screen.findByRole("combobox", { name: "Item" }), { target: { value: "i1" } })
            fireEvent.change(screen.getByRole("combobox", { name: "Award to" }), { target: { value: "n1" } })
            fireEvent.click(screen.getByRole("button", { name: "Award item" }))
            await screen.findByRole("alert")
        }

        it("Retry sends the same token, target, body and key without reading a new token", async () => {
            const server = lostAnswer()
            await award()
            fireEvent.click(screen.getByRole("button", { name: "Retry" }))
            await vi.waitFor(() => expect(server.callsTo("POST", AWARD)).toHaveLength(2))
            const [first, second] = server.callsTo("POST", AWARD)
            expect(first!.body).toEqual({ expected_last_event_id: "e9", holder_entity_id: "n1" })
            expect(second!.body).toEqual(first!.body)
            expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
            expect(server.callsTo("GET", TOKEN)).toHaveLength(1)
        })

        it("pressing Award again with the same choices sends the same request", async () => {
            const server = lostAnswer()
            await award()
            fireEvent.click(screen.getByRole("button", { name: "Award item" }))
            await vi.waitFor(() => expect(server.callsTo("POST", AWARD)).toHaveLength(2))
            const [first, second] = server.callsTo("POST", AWARD)
            expect(second!.body).toEqual(first!.body)
            expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
            expect(server.callsTo("GET", TOKEN)).toHaveLength(1)
        })
    })
})

