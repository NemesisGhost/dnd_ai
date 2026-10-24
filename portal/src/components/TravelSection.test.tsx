import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { SessionParticipant, SessionTravelEntry } from "../types/campaignSession"
import { TravelSection } from "./TravelSection"

const SESSION_TRAVEL = "/campaigns/c1/sessions/s1/travel"

const participant = (id: string, name: string, removed: string | null = null): SessionParticipant => ({
    session_participant_id: `p-${id}`,
    character_id: id,
    character_name: name,
    character_kind: "player_character",
    participation_role: "player_character",
    added_at: "2026-01-01T00:00:00Z",
    removed_at: removed,
})

const ENTRY: SessionTravelEntry = {
    event_id: "e1",
    world_time_id: "t1",
    world_time: "Year 1",
    note: "GM only: at dawn",
    legs: [
        {
            traveler: { entity_id: "m1", name: "Aldric" },
            from: { state: "named", entity_id: "l0", name: "Northmark" },
            to: { state: "named", entity_id: "l1", name: "Stonebridge" },
        },
    ],
}

afterEach(() => {
    vi.unstubAllGlobals()
})

interface Options {
    travel?: SessionTravelEntry[]
    canRecord?: boolean
    refreshFailed?: boolean
    refetch?: () => Promise<void>
}

function setup(options: Options = {}) {
    const refetch = vi.fn(options.refetch ?? (() => Promise.resolve()))
    const server = installMockServer()
    server.on("GET", "/campaigns/c1/parties", {
        body: {
            can_create: true,
            items: [
                { party_id: "p1", name: "The Company", description: null, lifecycle_status: "active", row_version: 1 },
            ],
        },
    })
    server.on("GET", "/campaigns/c1/parties/p1/members", {
        body: {
            party: { party_id: "p1", name: "The Company" },
            members: [
                { party_membership_id: "pm1", character_id: "m1", character_name: "Aldric", is_current: true },
                { party_membership_id: "pm2", character_id: "m9", character_name: "Outsider", is_current: true },
                { party_membership_id: "pm3", character_id: "m8", character_name: "Left", is_current: false },
            ],
        },
    })
    server.on("GET", "/campaigns/c1/clock", {
        body: { current: { world_time_id: "t1", display: "Year 1" }, row_version: 1, inherited: false, last_event_id: null },
    })
    server.on("GET", /\/campaigns\/c1\/world-times/, {
        body: {
            items: [
                {
                    world_time_id: "t0",
                    calendar_id: null,
                    year: null,
                    month_number: null,
                    day: null,
                    hour: null,
                    minute: null,
                    label: "Year 0",
                    precision: "narrative",
                    sort_key: 0,
                    display: "Year 0",
                },
            ],
            next_cursor: null,
        },
    })
    server.on("GET", "/campaigns/c1/calendars", { body: { calendars: [] } })
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
    server.on("POST", SESSION_TRAVEL, {
        body: {
            destination_location_id: "l1",
            session_id: "s1",
            changed: true,
            moved: ["m1"],
            already_there: [],
            event_id: "e1",
        },
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
                        sessionId="s1"
                        participants={[participant("m1", "Aldric"), participant("m2", "Mira"), participant("m3", "Gone", "x")]}
                        travel={options.travel ?? []}
                        refetch={refetch}
                        refreshFailed={options.refreshFailed}
                        canRecord={options.canRecord ?? true}
                        reason="This session has ended, so you can no longer record travel."
                    />
                ),
            },
        ],
    })
    return { server, refetch }
}

async function chooseDestination(form: HTMLElement) {
    fireEvent.focus(within(form).getByRole("combobox", { name: "Destination" }))
    fireEvent.click(await within(form).findByRole("option", { name: /Stonebridge/ }))
}

const submit = (form: HTMLElement) => fireEvent.click(within(form).getByRole("button", { name: "Record travel" }))

describe("TravelSection", () => {
    it("lists only the people who are taking part", async () => {
        setup()
        expect(await screen.findByRole("checkbox", { name: "Aldric" })).toBeInTheDocument()
        expect(screen.getByRole("checkbox", { name: "Mira" })).toBeInTheDocument()
        expect(screen.queryByRole("checkbox", { name: "Gone" })).not.toBeInTheDocument()
    })

    it("shows the effective campaign time and says an explicit time does not move it", async () => {
        setup()
        expect(await screen.findByText("Uses the campaign time: Year 1")).toBeInTheDocument()
        expect(screen.getByLabelText(/In-world time/)).toHaveAccessibleDescription(
            /Choosing a time does not change the campaign time/,
        )
        expect(screen.getByLabelText(/GM notes/)).toHaveAccessibleDescription(/Visible only to people who can edit canon/)
    })

    it("needs a destination and a traveler before it sends anything", async () => {
        const { server } = setup()
        const form = await screen.findByRole("form", { name: "Record travel" })
        submit(form)
        expect(await within(form).findByText(/Choose a destination and who is travelling/)).toBeInTheDocument()
        expect(server.callsTo("POST", SESSION_TRAVEL)).toHaveLength(0)
    })

    it("records through the session route without a note or time, along an offered route", async () => {
        const { server } = setup()
        const form = await screen.findByRole("form", { name: "Record travel" })
        await chooseDestination(form)
        fireEvent.click(within(form).getByRole("checkbox", { name: "Aldric" }))
        fireEvent.change(await within(form).findByRole("combobox", { name: /By route/ }), { target: { value: "r1" } })
        submit(form)
        await waitFor(() => expect(server.callsTo("POST", SESSION_TRAVEL)).toHaveLength(1))
        expect(server.callsTo("POST", SESSION_TRAVEL)[0]!.body).toEqual({
            destination_location_id: "l1",
            character_ids: ["m1"],
            party_id: null,
            route_id: "r1",
            world_time_id: null,
            note: null,
        })
        expect(server.callsTo("POST", "/campaigns/c1/travel")).toHaveLength(0)
    })

    it("sends the note and an explicit in-world time", async () => {
        const { server } = setup()
        const form = await screen.findByRole("form", { name: "Record travel" })
        await chooseDestination(form)
        fireEvent.click(within(form).getByRole("checkbox", { name: "Aldric" }))
        fireEvent.change(await within(form).findByRole("combobox", { name: /In-world time/ }), { target: { value: "t0" } })
        fireEvent.change(within(form).getByLabelText(/GM notes/), { target: { value: "  Set out at dawn  " } })
        submit(form)
        await waitFor(() => expect(server.callsTo("POST", SESSION_TRAVEL)).toHaveLength(1))
        expect(server.callsTo("POST", SESSION_TRAVEL)[0]!.body).toMatchObject({
            world_time_id: "t0",
            note: "Set out at dawn",
        })
    })

    it("previews the union of ticked characters and the party, marking those outside the session", async () => {
        const { server } = setup()
        const form = await screen.findByRole("form", { name: "Record travel" })
        expect(within(form).queryByRole("combobox", { name: /whole party/ })).toBeNull()
        await chooseDestination(form)
        fireEvent.click(within(form).getByRole("checkbox", { name: "Mira" }))
        fireEvent.click(within(form).getByRole("checkbox", { name: "Aldric" }))
        fireEvent.change(await within(form).findByRole("combobox", { name: "Add a party" }), { target: { value: "p1" } })
        const preview = await within(form).findByRole("list", { name: "These characters will move" })
        await waitFor(() => expect(within(preview).getAllByRole("listitem")).toHaveLength(3))
        const items = within(preview).getAllByRole("listitem").map((li) => li.textContent)
        expect(items).toEqual(["Aldric", "Mira", "Outsider (not in this session)"])
        expect(within(form).getByLabelText("Add a party")).toHaveAccessibleDescription(/Everyone ticked above/)
        expect(screen.queryByText(/Or a whole party/)).toBeNull()
        submit(form)
        await waitFor(() => expect(server.callsTo("POST", SESSION_TRAVEL)).toHaveLength(1))
        expect(server.callsTo("POST", SESSION_TRAVEL)[0]!.body).toMatchObject({
            character_ids: ["m2", "m1"],
            party_id: "p1",
        })
    })

    it("still works when the party's members cannot be listed", async () => {
        const { server } = setup()
        server.on("GET", "/campaigns/c1/parties/p1/members", { status: 403, body: { error: { code: "forbidden", message: "m", correlation_id: "c" } } })
        const form = await screen.findByRole("form", { name: "Record travel" })
        fireEvent.change(await within(form).findByRole("combobox", { name: "Add a party" }), { target: { value: "p1" } })
        expect(await within(form).findByText(/members could not be listed here/)).toBeInTheDocument()
        await chooseDestination(form)
        submit(form)
        await waitFor(() => expect(server.callsTo("POST", SESSION_TRAVEL)).toHaveLength(1))
    })

    it("refetches before announcing, clears only what was used, and keeps the destination", async () => {
        const order: string[] = []
        const { server, refetch } = setup({
            refetch: async () => {
                order.push("refetch")
            },
        })
        const form = await screen.findByRole("form", { name: "Record travel" })
        await chooseDestination(form)
        fireEvent.click(within(form).getByRole("checkbox", { name: "Aldric" }))
        fireEvent.change(within(form).getByLabelText(/GM notes/), { target: { value: "note" } })
        submit(form)
        await waitFor(() => expect(screen.getByTestId("authoring-announcer")).toHaveTextContent(/1 traveler arrived/))
        expect(refetch).toHaveBeenCalledTimes(1)
        expect(server.callsTo("POST", SESSION_TRAVEL)).toHaveLength(1)
        expect(within(form).getByRole("checkbox", { name: "Aldric" })).not.toBeChecked()
        expect(within(form).getByLabelText(/GM notes/)).toHaveValue("")
        expect(within(form).getByRole("combobox", { name: "Destination" })).toHaveValue("Stonebridge")
        expect(await screen.findByText(/1 traveler arrived and the journey was recorded/, { selector: "p[role=status]" })).toBeInTheDocument()
    })

    it("says nothing was recorded when everyone was already there, and does not refetch", async () => {
        const { server, refetch } = setup()
        server.on("POST", SESSION_TRAVEL, {
            body: { destination_location_id: "l1", session_id: "s1", changed: false, moved: [], already_there: ["m1"] },
        })
        const form = await screen.findByRole("form", { name: "Record travel" })
        await chooseDestination(form)
        fireEvent.click(within(form).getByRole("checkbox", { name: "Aldric" }))
        submit(form)
        expect(await screen.findByText("Everyone was already there. Nothing was recorded.", { selector: "p[role=status]" })).toBeInTheDocument()
        expect(refetch).not.toHaveBeenCalled()
        // Nothing was consumed, so the choice stays for adjusting.
        expect(within(form).getByRole("checkbox", { name: "Aldric" })).toBeChecked()
    })

    it("tells the user not to record again when the journey was saved but the refresh failed", async () => {
        setup({ refreshFailed: true })
        const form = await screen.findByRole("form", { name: "Record travel" })
        await chooseDestination(form)
        fireEvent.click(within(form).getByRole("checkbox", { name: "Aldric" }))
        submit(form)
        const status = await screen.findByText(/Do not record this journey again/, { selector: "p[role=status]" })
        expect(status).toHaveTextContent(/1 traveler arrived and the journey was recorded/)
    })

    it.each([
        ["route_mismatch", /does not join where the travelers are/],
        ["travel_time_invalid", /Choose a later in-world time.*Nothing was recorded/],
        ["clock_required", /Set the campaign time first/],
    ])("explains %s and keeps every field", async (errorCode, text) => {
        const { server } = setup()
        server.on("POST", SESSION_TRAVEL, {
            status: 409,
            body: { error: { code: errorCode, message: "m", correlation_id: "c" } },
        })
        const form = await screen.findByRole("form", { name: "Record travel" })
        await chooseDestination(form)
        fireEvent.click(within(form).getByRole("checkbox", { name: "Mira" }))
        fireEvent.change(within(form).getByLabelText(/GM notes/), { target: { value: "keep me" } })
        submit(form)
        expect(await screen.findByRole("alert")).toHaveTextContent(text)
        expect(within(form).getByRole("checkbox", { name: "Mira" })).toBeChecked()
        expect(within(form).getByLabelText(/GM notes/)).toHaveValue("keep me")
    })

    it.each(["session_not_in_progress", "session_not_active", "not_found"])(
        "reloads the session when the server says it changed (%s)",
        async (errorCode) => {
            const { server, refetch } = setup()
            server.on("POST", SESSION_TRAVEL, {
                status: errorCode === "not_found" ? 404 : 409,
                body: { error: { code: errorCode, message: "m", correlation_id: "c" } },
            })
            const form = await screen.findByRole("form", { name: "Record travel" })
            await chooseDestination(form)
            fireEvent.click(within(form).getByRole("checkbox", { name: "Mira" }))
            submit(form)
            expect(await screen.findByRole("alert")).toHaveTextContent(/This session has ended or changed; reloading it/)
            await waitFor(() => expect(refetch).toHaveBeenCalled())
            expect(within(form).getByRole("checkbox", { name: "Mira" })).toBeChecked()
        },
    )

    it("shows the history beneath the form, with its empty state", async () => {
        setup()
        expect(await screen.findByText("No travel recorded in this session yet.")).toBeInTheDocument()
    })

    it("lists recorded travel with names, time and the GM note", async () => {
        setup({ travel: [ENTRY] })
        const history = await screen.findByRole("list", { name: "Travel in this session" })
        expect(within(history).getByText("In-world: Year 1")).toBeInTheDocument()
        expect(within(history).getByText("Aldric: Northmark to Stonebridge")).toBeInTheDocument()
        expect(within(history).getByText("GM notes: GM only: at dawn")).toBeInTheDocument()
    })

    it("keeps the history readable without the form when recording is not offered", async () => {
        setup({ travel: [ENTRY], canRecord: false })
        expect(await screen.findByText("This session has ended, so you can no longer record travel.")).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Record travel" })).toBeNull()
        expect(screen.getByText("Aldric: Northmark to Stonebridge")).toBeInTheDocument()
    })
})
