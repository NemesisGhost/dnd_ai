import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { SessionParticipant, SessionTravelEntry } from "../types/campaignSession"
import type { RefetchOutcome } from "../hooks/useAuthoringResource"
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

// A roster row as GET .../parties/{id}/members sends it. `left_at` is the stored end (null = no
// recorded leave time, which is what the unchanged travel command moves); `period_status` is the
// server's classification at the campaign clock.
const row = (
    id: string,
    name: string,
    status: "in_effect" | "not_started" | "ended" | "clock_unset",
    leftAt: string | null,
) => ({
    party_membership_id: `pm-${id}`,
    character_id: id,
    character_name: name,
    joined_at: "Year 0",
    left_at: leftAt,
    joined_reason: null,
    left_reason: null,
    is_current: status === "in_effect",
    period_status: status,
})

const DEFAULT_MEMBERS = [
    row("m1", "Aldric", "in_effect", null),
    row("m9", "Outsider", "in_effect", null),
    row("m8", "Left", "ended", "Year 0"),
]

interface Options {
    members?: ReturnType<typeof row>[]
    clockUnset?: boolean
    travel?: SessionTravelEntry[]
    canRecord?: boolean
    refreshFailed?: boolean
    refetch?: () => Promise<RefetchOutcome>
}

function setup(options: Options = {}) {
    const refetch = vi.fn(options.refetch ?? (() => Promise.resolve<RefetchOutcome>("ok")))
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
            as_of: options.clockUnset ? null : "Year 1",
            clock_unset: options.clockUnset === true,
            members: options.members ?? DEFAULT_MEMBERS,
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
        const preview = await within(form).findByRole("list", { name: "Travel candidates" })
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

    // The unchanged command (`commands/travel.py`) moves a party's memberships with no recorded end
    // (`effective_to_world_time_id IS NULL`) on the timeline, whatever the campaign time. The
    // preview follows the stored end, not `is_current`/`period_status`.
    describe("party preview matches the travel command's membership filter", () => {
        // An always-eligible actor (open-ended, in effect) sent in the same response as the actor
        // under test. Once the control is listed the response has been applied, so an absent actor
        // is absent because of the filter, not because the list had not loaded yet.
        const CONTROL = row("m7", "Control", "in_effect", null)
        const CONTROL_TEXT = "Control (not in this session)"

        async function previewFor(options: Options, tick: string[] = []) {
            const { server } = setup({ ...options, members: [CONTROL, ...(options.members ?? [])] })
            const form = await screen.findByRole("form", { name: "Record travel" })
            for (const name of tick) fireEvent.click(within(form).getByRole("checkbox", { name }))
            fireEvent.change(await within(form).findByRole("combobox", { name: "Add a party" }), { target: { value: "p1" } })
            const preview = await within(form).findByRole("list", { name: "Travel candidates" })
            await within(preview).findByText(CONTROL_TEXT)
            expect(within(form).queryByText("No one selected yet.")).toBeNull()
            const names = within(preview).getAllByRole("listitem").map((li) => li.textContent)
            return { server, form, names }
        }

        it("includes a future open-ended membership and says it starts later", async () => {
            const { names } = await previewFor({ members: [row("m5", "Later", "not_started", null)] })
            expect(names).toEqual([CONTROL_TEXT, "Later (not in this session) (party membership starts later)"])
        })

        it("excludes a finite membership that is in effect at the campaign time", async () => {
            const { names } = await previewFor({ members: [row("m5", "Finite", "in_effect", "Year 9")] })
            expect(names).toEqual([CONTROL_TEXT])
        })

        it("excludes an ended finite membership", async () => {
            const { names } = await previewFor({ members: [row("m5", "Gone", "ended", "Year 0")] })
            expect(names).toEqual([CONTROL_TEXT])
        })

        it("includes an ordinary current open-ended membership", async () => {
            const { names } = await previewFor({ members: [row("m1", "Aldric", "in_effect", null)] })
            expect(names).toEqual([CONTROL_TEXT, "Aldric"])
        })

        it("lists a ticked character who is also an open-ended party member once", async () => {
            const { names } = await previewFor({ members: [row("m1", "Aldric", "in_effect", null)] }, ["Aldric"])
            expect(names.filter((n) => n === "Aldric")).toHaveLength(1)
            expect(names).toHaveLength(2)
        })

        it("still includes open-ended memberships when the campaign has no clock", async () => {
            const { names } = await previewFor({
                clockUnset: true,
                members: [row("m1", "Aldric", "clock_unset", null), row("m8", "Left", "clock_unset", "Year 0")].map((m) => m),
            })
            expect(names).toEqual([CONTROL_TEXT, "Aldric"])
        })

        it("calls the set candidates, not a definitive mover list, and issues no command", async () => {
            const { server, form } = await previewFor({})
            expect(within(form).getByText("Travel candidates")).toBeInTheDocument()
            expect(within(form).queryByText(/will move/)).toBeNull()
            expect(within(form).getByText(/Candidates are the ticked characters and the party.s open-ended memberships/)).toBeInTheDocument()
            expect(within(form).getByText(/validates travelers and skips anyone already at the destination/)).toBeInTheDocument()
            expect(within(form).getByText(/not evaluated at the campaign time or the travel time/)).toBeInTheDocument()
            expect(within(form).getByLabelText("Add a party")).toHaveAccessibleDescription(/no recorded leave time/)
            expect(server.callsTo("POST", /./)).toHaveLength(0)
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
                return "ok"
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

    it("tells the user not to record again when the journey was saved but the session read failed", async () => {
        const { server, refetch } = setup({ refreshFailed: true, refetch: async () => "failed" })
        const form = await screen.findByRole("form", { name: "Record travel" })
        await chooseDestination(form)
        fireEvent.click(within(form).getByRole("checkbox", { name: "Aldric" }))
        submit(form)
        expect(await screen.findByText(/1 traveler arrived and the journey was recorded\. The latest travel history could not be loaded/)).toBeInTheDocument()
        expect(screen.getByText(/Do not record this journey again/)).toBeInTheDocument()
        // Saved is not done: nothing is announced as completed, and the write is sent once.
        expect(screen.getByTestId("authoring-announcer")).not.toHaveTextContent(/arrived/)
        expect(server.callsTo("POST", SESSION_TRAVEL)).toHaveLength(1)
        expect(refetch).toHaveBeenCalledTimes(1)
    })

    it("offers a read-only Load latest when the session read was superseded, and announces once it works", async () => {
        let outcome: RefetchOutcome = "superseded"
        const { server, refetch } = setup({ refetch: async () => outcome })
        const form = await screen.findByRole("form", { name: "Record travel" })
        await chooseDestination(form)
        fireEvent.click(within(form).getByRole("checkbox", { name: "Aldric" }))
        submit(form)
        // A superseded read says nothing about the history: not a completed refresh.
        const load = await screen.findByRole("button", { name: "Load latest" })
        expect(screen.getByTestId("authoring-announcer")).not.toHaveTextContent(/1 traveler arrived/)
        outcome = "ok"
        fireEvent.click(load)
        await waitFor(() => expect(screen.getByTestId("authoring-announcer")).toHaveTextContent(/1 traveler arrived/))
        expect(screen.queryByRole("button", { name: "Load latest" })).toBeNull()
        expect(refetch).toHaveBeenCalledTimes(2)
        expect(server.callsTo("POST", SESSION_TRAVEL)).toHaveLength(1)
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
