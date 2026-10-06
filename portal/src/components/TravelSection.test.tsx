import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { SessionParticipant } from "../types/campaignSession"
import { TravelSection } from "./TravelSection"

const participant = (id: string, name: string, removed: string | null = null): SessionParticipant => ({
    session_participant_id: `p-${id}`,
    character_id: id,
    character_name: name,
    participation_role: "player_character",
    added_at: "2026-01-01T00:00:00Z",
    removed_at: removed,
})

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup() {
    const server = installMockServer()
    server.on("GET", /\/parties/, {
        body: {
            can_create: true,
            items: [
                { party_id: "p1", name: "The Company", description: null, lifecycle_status: "active", row_version: 1 },
            ],
        },
    })
    server.on("GET", /authoring\/routes\?location_id=/, {
        body: {
            items: [
                {
                    relationship_id: "r1",
                    description: null,
                    origin: { entity_id: "l0", name: "Northmark" },
                    destination: { entity_id: "l1", name: "Stonebridge" },
                },
            ],
        },
    })
    server.on("GET", /world\/search/, {
        body: {
            items: [
                { entity_id: "l1", category: "location", entity_type_code: "settlement", name: "Stonebridge", summary: null },
            ],
            next_cursor: null,
        },
    })
    server.on("POST", "/campaigns/c1/travel", {
        body: { destination_location_id: "l1", changed: true, moved: ["m1"], already_there: [], event_id: "e1" },
    })
    renderAuthoringRoutes({
        initialEntry: "/app/c1/travel",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] }],
        }),
        routes: [
            {
                path: "/app/:campaignId/travel",
                element: (
                    <TravelSection
                        campaignId="c1"
                        participants={[participant("m1", "Aldric"), participant("m2", "Mira"), participant("m3", "Gone", "x")]}
                    />
                ),
            },
        ],
    })
    return server
}

describe("TravelSection", () => {
    it("lists only the people who are taking part", async () => {
        setup()
        expect(await screen.findByRole("checkbox", { name: "Aldric" })).toBeInTheDocument()
        expect(screen.getByRole("checkbox", { name: "Mira" })).toBeInTheDocument()
        expect(screen.queryByRole("checkbox", { name: "Gone" })).not.toBeInTheDocument()
    })

    it("needs a destination and a traveler before it sends anything", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Record travel" })
        fireEvent.click(within(form).getByRole("button", { name: "Record travel" }))
        expect(await within(form).findByText(/Choose a destination and who is travelling/)).toBeInTheDocument()
        expect(server.callsTo("POST", "/campaigns/c1/travel")).toHaveLength(0)
    })

    it("records travel for the chosen travelers along an offered route", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Record travel" })
        fireEvent.focus(within(form).getByRole("combobox", { name: "Destination" }))
        fireEvent.click(await within(form).findByRole("option", { name: /Stonebridge/ }))
        fireEvent.click(within(form).getByRole("checkbox", { name: "Aldric" }))
        fireEvent.change(await within(form).findByRole("combobox", { name: /By route/ }), { target: { value: "r1" } })
        fireEvent.click(within(form).getByRole("button", { name: "Record travel" }))
        await vi.waitFor(() => expect(server.callsTo("POST", "/campaigns/c1/travel")).toHaveLength(1))
        expect(server.callsTo("POST", "/campaigns/c1/travel")[0]!.body).toEqual({
            destination_location_id: "l1",
            character_ids: ["m1"],
            party_id: null,
            route_id: "r1",
        })
    })

    it("sends a whole party without naming travelers", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Record travel" })
        fireEvent.focus(within(form).getByRole("combobox", { name: "Destination" }))
        fireEvent.click(await within(form).findByRole("option", { name: /Stonebridge/ }))
        fireEvent.change(await within(form).findByRole("combobox", { name: "Or a whole party" }), {
            target: { value: "p1" },
        })
        fireEvent.click(within(form).getByRole("button", { name: "Record travel" }))
        await vi.waitFor(() => expect(server.callsTo("POST", "/campaigns/c1/travel")).toHaveLength(1))
        expect(server.callsTo("POST", "/campaigns/c1/travel")[0]!.body).toMatchObject({
            character_ids: [],
            party_id: "p1",
        })
    })

    it("explains a refused journey", async () => {
        const server = setup()
        server.on("POST", "/campaigns/c1/travel", {
            status: 409,
            body: { error: { code: "route_mismatch", message: "m", correlation_id: "c" } },
        })
        const form = await screen.findByRole("form", { name: "Record travel" })
        fireEvent.focus(within(form).getByRole("combobox", { name: "Destination" }))
        fireEvent.click(await within(form).findByRole("option", { name: /Stonebridge/ }))
        fireEvent.click(within(form).getByRole("checkbox", { name: "Mira" }))
        fireEvent.click(within(form).getByRole("button", { name: "Record travel" }))
        expect(await screen.findByRole("alert")).toHaveTextContent(/does not join where the travelers are/)
    })
})
