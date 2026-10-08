import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { PrepareEncounterPage, PreparedEncounterPage } from "./EncounterPages"
import { EncounterList } from "../components/EncounterList"

const AUTH = "/campaigns/c1/authoring/encounters"
const BASE = "/campaigns/c1/encounters"

const OPTIONS = {
    action_kinds: [
        { value: "attack", label: "Attack" },
        { value: "dodge", label: "Dodge" },
    ],
    outcomes: [
        { value: "defeated", label: "Defeated" },
        { value: "escaped", label: "Escaped" },
    ],
    sides: [
        { value: "party", label: "Party" },
        { value: "ally", label: "Ally" },
        { value: "enemy", label: "Enemy" },
        { value: "neutral", label: "Neutral" },
    ],
    limits: { summary_max_length: 4000, initiative_min: -100, initiative_max: 1000, max_participants: 50 },
}

function encounter(overrides: object = {}) {
    return {
        encounter_id: "e1",
        session_id: "s1",
        status: "pending",
        can_prepare: true,
        summary: "Ambush",
        location_id: "l1",
        location_name: "Stonebridge",
        world_time_id: "t1",
        current_round: 0,
        resulting_event_id: null,
        rounds: [],
        participants: [
            {
                encounter_participant_id: "p1",
                participant_entity_id: "n1",
                name: "Aldric",
                entity_type_code: "player_character",
                side: "party",
                initiative: 14,
                outcome: null,
                current_hit_points: null,
                maximum_hit_points: null,
            },
            {
                encounter_participant_id: "p2",
                participant_entity_id: "n2",
                name: "Bryn",
                entity_type_code: "npc",
                side: "enemy",
                initiative: null,
                outcome: null,
                current_hit_points: 7,
                maximum_hit_points: 12,
            },
        ],
        ...overrides,
    }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(entry: string, view: object = encounter(), capabilities = ["canon.edit"]) {
    const server = installMockServer()
    server.on("GET", `${AUTH}/options`, { body: OPTIONS })
    server.on("GET", `${AUTH}/e1`, () => ({ body: view }))
    server.on("GET", /world\/search/, {
        body: {
            items: [
                { entity_id: "n2", category: "character", entity_type_code: "npc", name: "Bryn", summary: null, canon_status: "canon" },
                { entity_id: "l2", category: "location", entity_type_code: "settlement", name: "Northmark", summary: null },
            ],
            next_cursor: null,
        },
    })
    server.on("POST", `${BASE}/prepare`, { status: 201, body: encounter({ encounter_id: "e2", participants: [] }) })
    server.on("POST", new RegExp(`${BASE}/e1/`), { body: encounter() })
    renderAuthoringRoutes({
        initialEntry: entry,
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [
            { path: "/app/:campaignId/sessions/:sessionId/encounters/new", element: <PrepareEncounterPage /> },
            { path: "/app/:campaignId/sessions/:sessionId/encounters/:encounterId", element: <PreparedEncounterPage /> },
        ],
    })
    return server
}

describe("return links to the run page", () => {
    it("returns from the prepare page to Encounter preparation", async () => {
        setup("/app/c1/sessions/s1/encounters/new")
        expect(await screen.findByRole("link", { name: "Run the session" })).toHaveAttribute(
            "href",
            "/app/c1/sessions/s1/run?section=encounter-prep",
        )
    })

    it("returns from a pending encounter to Encounter preparation", async () => {
        setup("/app/c1/sessions/s1/encounters/e1")
        await screen.findByRole("heading", { level: 1, name: "Encounter" })
        expect(await screen.findByRole("link", { name: "Run the session" })).toHaveAttribute(
            "href",
            "/app/c1/sessions/s1/run?section=encounter-prep",
        )
    })

    it("returns from a started encounter to Encounters", async () => {
        setup("/app/c1/sessions/s1/encounters/e1", encounter({ status: "active", can_prepare: false }))
        await vi.waitFor(() =>
            expect(screen.getByRole("link", { name: "Run the session" })).toHaveAttribute(
                "href",
                "/app/c1/sessions/s1/run?section=encounters",
            ),
        )
    })
})

describe("PrepareEncounterPage", () => {
    it("prepares a pending encounter in the session", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/new")
        const form = await screen.findByRole("form", { name: "Prepare an encounter" })
        fireEvent.focus(within(form).getByRole("combobox", { name: /Where it happens/ }))
        fireEvent.click(await within(form).findByRole("option", { name: /Northmark/ }))
        fireEvent.change(within(form).getByRole("textbox", { name: /Summary/ }), { target: { value: "  Gate fight " } })
        fireEvent.click(within(form).getByRole("button", { name: "Prepare encounter" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/prepare`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/prepare`)[0]!.body).toEqual({
            session_id: "s1",
            location_id: "l2",
            summary: "Gate fight",
        })
    })

    it("refuses people without canon.edit", async () => {
        setup("/app/c1/sessions/s1/encounters/new", encounter(), [])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
    })
})

describe("PreparedEncounterPage", () => {
    it("shows the participants as compact rows with a side and no initiative", async () => {
        setup("/app/c1/sessions/s1/encounters/e1")
        const rows = (await screen.findAllByRole("listitem")).filter((li) => li.className.includes("encounter-roster__row"))
        expect(rows).toHaveLength(2)
        expect(within(rows[0]!).getByText("Aldric")).toBeInTheDocument()
        expect(within(rows[0]!).getByText("player character")).toBeInTheDocument()
        expect(within(rows[0]!).getByRole("combobox", { name: "Side of Aldric" })).toHaveValue("party")
        expect(within(rows[1]!).getByRole("combobox", { name: "Side of Bryn" })).toHaveValue("enemy")
        expect(within(rows[0]!).getByRole("button", { name: "Remove Aldric" })).toBeInTheDocument()
        expect(screen.queryByRole("textbox", { name: /Initiative/ })).not.toBeInTheDocument()
        expect(screen.queryByText(/initiative/i)).not.toBeInTheDocument()
    })

    it("adds a character with a side, sending no initiative", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        const form = await screen.findByRole("form", { name: "Add a participant" })
        fireEvent.focus(within(form).getByRole("combobox", { name: "Character" }))
        fireEvent.click(await within(form).findByRole("option", { name: /Bryn/ }))
        fireEvent.change(within(form).getByRole("combobox", { name: "Side" }), { target: { value: "ally" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add participant" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/e1/participants`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/e1/participants`)[0]!.body).toEqual({
            participant_entity_id: "n2",
            side: "ally",
        })
    })

    it("needs a character before adding", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        const form = await screen.findByRole("form", { name: "Add a participant" })
        fireEvent.click(within(form).getByRole("button", { name: "Add participant" }))
        expect(await screen.findByText(/Choose a character to add/)).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/e1/participants`)).toHaveLength(0)
    })

    it("keeps the add form's choice when adding fails, and clears it on success", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        let attempts = 0
        server.on("POST", `${BASE}/e1/participants`, () => {
            attempts += 1
            return attempts === 1
                ? { status: 409, body: { error: { code: "encounter_full", message: "m", correlation_id: "c" } } }
                : { body: encounter() }
        })
        const form = await screen.findByRole("form", { name: "Add a participant" })
        fireEvent.focus(within(form).getByRole("combobox", { name: "Character" }))
        fireEvent.click(await within(form).findByRole("option", { name: /Bryn/ }))
        fireEvent.click(within(form).getByRole("button", { name: "Add participant" }))
        await vi.waitFor(() => expect(attempts).toBe(1))
        await screen.findByRole("alert")
        expect(within(form).getByRole("combobox", { name: "Character" })).toHaveValue("Bryn")
        fireEvent.click(within(form).getByRole("button", { name: "Add participant" }))
        await vi.waitFor(() => expect(attempts).toBe(2))
        await vi.waitFor(() => expect(within(form).getByRole("combobox", { name: "Character" })).toHaveValue(""))
    })

    it("offers Save only for a participant whose side differs, and only that one", async () => {
        setup("/app/c1/sessions/s1/encounters/e1")
        const aldric = await screen.findByRole("form", { name: "Change Aldric" })
        const bryn = screen.getByRole("form", { name: "Change Bryn" })
        expect(screen.queryByRole("button", { name: /^Save (Aldric|Bryn)$/ })).not.toBeInTheDocument()
        fireEvent.change(within(aldric).getByRole("combobox"), { target: { value: "ally" } })
        expect(within(aldric).getByRole("button", { name: "Save Aldric" })).toBeInTheDocument()
        expect(within(aldric).getByText("Unsaved")).toBeInTheDocument()
        expect(within(bryn).queryByRole("button", { name: "Save Bryn" })).not.toBeInTheDocument()
        fireEvent.change(within(aldric).getByRole("combobox"), { target: { value: "party" } })
        expect(screen.queryByRole("button", { name: "Save Aldric" })).not.toBeInTheDocument()
    })

    it("saves only the changed participant's side, without initiative, then drops the Save button", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        const form = await screen.findByRole("form", { name: "Change Bryn" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Side of Bryn" }), { target: { value: "neutral" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save Bryn" }))
        await vi.waitFor(() => expect(server.callsTo("POST", /\/participants\/[^/]+\/update$/)).toHaveLength(1))
        const [call] = server.callsTo("POST", /\/participants\/[^/]+\/update$/)
        expect(call!.path).toBe(`${BASE}/e1/participants/p2/update`)
        expect(call!.body).toEqual({ side: "neutral" })
        await screen.findByText("Bryn updated")
        await vi.waitFor(() => expect(screen.queryByRole("button", { name: "Save Bryn" })).not.toBeInTheDocument())
    })

    it("keeps the draft and shows the error beside the row when an update fails", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        server.on("POST", `${BASE}/e1/participants/p1/update`, {
            status: 409,
            body: { error: { code: "encounter_not_pending", message: "m", correlation_id: "c" } },
        })
        const form = await screen.findByRole("form", { name: "Change Aldric" })
        fireEvent.change(within(form).getByRole("combobox"), { target: { value: "enemy" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save Aldric" }))
        const row = form.closest("li") as HTMLElement
        expect(await within(row).findByRole("alert")).toHaveTextContent(/already started or finished/)
        expect(within(row).getByRole("combobox")).toHaveValue("enemy")
        expect(within(row).getByRole("button", { name: "Save Aldric" })).toBeInTheDocument()
        const other = screen.getByRole("form", { name: "Change Bryn" }).closest("li") as HTMLElement
        expect(within(other).queryByRole("alert")).not.toBeInTheDocument()
    })

    it("keeps the draft when the write is stale", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        server.on("POST", `${BASE}/e1/participants/p1/update`, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        const form = await screen.findByRole("form", { name: "Change Aldric" })
        fireEvent.change(within(form).getByRole("combobox"), { target: { value: "ally" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save Aldric" }))
        const row = form.closest("li") as HTMLElement
        await within(row).findByRole("alert")
        expect(within(row).getByRole("combobox")).toHaveValue("ally")
    })

    it("prevents a second submission while a save is pending", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        let release: () => void = () => {}
        const gate = new Promise<void>((resolve) => {
            release = resolve
        })
        server.on("POST", `${BASE}/e1/participants/p1/update`, async () => {
            await gate
            return { body: encounter() }
        })
        const form = await screen.findByRole("form", { name: "Change Aldric" })
        fireEvent.change(within(form).getByRole("combobox"), { target: { value: "ally" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save Aldric" }))
        const saving = await within(form).findByRole("button", { name: "Save Aldric" })
        expect(saving).toBeDisabled()
        expect(saving).toHaveTextContent("Saving…")
        expect(screen.getByRole("button", { name: "Remove Bryn" })).toBeDisabled()
        fireEvent.click(saving)
        release()
        await screen.findByText("Aldric updated")
        expect(server.callsTo("POST", `${BASE}/e1/participants/p1/update`)).toHaveLength(1)
    })

    it("keeps another row's draft when a different participant is saved or removed", async () => {
        setup("/app/c1/sessions/s1/encounters/e1")
        const aldric = await screen.findByRole("form", { name: "Change Aldric" })
        const bryn = screen.getByRole("form", { name: "Change Bryn" })
        fireEvent.change(within(aldric).getByRole("combobox"), { target: { value: "ally" } })
        fireEvent.change(within(bryn).getByRole("combobox"), { target: { value: "neutral" } })
        fireEvent.click(within(bryn).getByRole("button", { name: "Save Bryn" }))
        await screen.findByText("Bryn updated")
        expect(within(aldric).getByRole("combobox")).toHaveValue("ally")
        expect(within(aldric).getByRole("button", { name: "Save Aldric" })).toBeInTheDocument()
    })

    it("removes a participant", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        fireEvent.click(await screen.findByRole("button", { name: "Remove Aldric" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/e1/participants/p1/remove`)).toHaveLength(1))
    })

    it("starts an encounter whose participants have no initiative", async () => {
        const server = setup(
            "/app/c1/sessions/s1/encounters/e1",
            encounter({
                participants: encounter().participants.map((p: object) => ({ ...p, initiative: null })),
            }),
        )
        fireEvent.click(await screen.findByRole("button", { name: "Start encounter" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/e1/start`)).toHaveLength(1))
    })

    it("saves the place and summary", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        const form = await screen.findByRole("form", { name: "Encounter details" })
        fireEvent.change(within(form).getByRole("textbox", { name: "Summary" }), { target: { value: "Changed" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save details" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/e1/update`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/e1/update`)[0]!.body).toEqual({
            location_id: "l1",
            summary: "Changed",
        })
    })

    it("is read-only once the encounter has started", async () => {
        setup("/app/c1/sessions/s1/encounters/e1", encounter({ status: "active", can_prepare: false }))
        expect(await screen.findByText(/Preparation is over/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Add a participant" })).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Remove Aldric" })).not.toBeInTheDocument()
        expect(screen.queryByText(/initiative/i)).not.toBeInTheDocument()
        expect(screen.getByText(/^party/)).toBeInTheDocument()
    })

    it("explains a refusal because it already started", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        server.on("POST", `${BASE}/e1/update`, {
            status: 409,
            body: { error: { code: "encounter_not_pending", message: "m", correlation_id: "c" } },
        })
        const form = await screen.findByRole("form", { name: "Encounter details" })
        fireEvent.click(within(form).getByRole("button", { name: "Save details" }))
        expect(await screen.findByText(/already started or finished/)).toBeInTheDocument()
    })
})

describe("EncounterList", () => {
    it("lists the session's encounters with a link to prepare another", async () => {
        installMockServer()
        renderAuthoringRoutes({
            initialEntry: "/app/c1/x",
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1" }],
            }),
            routes: [
                { path: "/app/:campaignId/x", element: (
                        <EncounterList
                            campaignId="c1"
                            sessionId="s1"
                            items={[
                                { encounter_id: "e1", status: "pending", summary: "Ambush", location_name: "Stonebridge", participant_count: 2 },
                            ]}
                            emptyText="No encounters yet."
                            prepareLink
                        />
                    ) },
            ],
        })
        expect(await screen.findByRole("link", { name: "Ambush" })).toHaveAttribute(
            "href",
            "/app/c1/sessions/s1/encounters/e1",
        )
        expect(screen.getByText(/pending, at Stonebridge, 2 participants/)).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Prepare an encounter" })).toHaveAttribute(
            "href",
            "/app/c1/sessions/s1/encounters/new",
        )
    })
})

describe("PreparedEncounterPage operation", () => {
    const active = (extra: object = {}) =>
        encounter({
            status: "active",
            can_prepare: false,
            current_round: 2,
            rounds: [
                {
                    round_number: 1,
                    turns: [
                        { turn_order: 0, actor_name: "Aldric", target_name: "Bryn", action_kind: "attack", hit: true, damage_amount: 5 },
                    ],
                },
            ],
            ...extra,
        })

    it("starts a prepared encounter", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        fireEvent.click(await screen.findByRole("button", { name: "Start encounter" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/e1/start`)).toHaveLength(1))
    })

    it("discards a prepared encounter only after confirming", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        fireEvent.click(await screen.findByRole("button", { name: "Discard encounter" }))
        const dialog = await screen.findByRole("dialog", { name: "Discard this encounter?" })
        expect(server.callsTo("POST", `${BASE}/e1/abort`)).toHaveLength(0)
        fireEvent.click(within(dialog).getByRole("button", { name: "Discard encounter" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/e1/abort`)).toHaveLength(1))
    })

    it("shows the round, the turns and the hit points of an active encounter", async () => {
        setup("/app/c1/sessions/s1/encounters/e1", active())
        expect(await screen.findByRole("heading", { name: "Round 2" })).toBeInTheDocument()
        expect(screen.getByText(/Aldric: attack at Bryn, hit, 5 damage/)).toBeInTheDocument()
        expect(screen.getByText(/7 of 12 hit points/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Add a participant" })).not.toBeInTheDocument()
    })

    it("records a turn with only what was entered", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1", active())
        const form = await screen.findByRole("form", { name: "Record a turn" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Who acts" }), { target: { value: "n1" } })
        fireEvent.change(within(form).getByRole("combobox", { name: /Target/ }), { target: { value: "n2" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "Result" }), { target: { value: "hit" } })
        fireEvent.change(within(form).getByRole("textbox", { name: /Damage/ }), { target: { value: "6" } })
        fireEvent.click(within(form).getByRole("button", { name: "Record turn" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/e1/turns`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/e1/turns`)[0]!.body).toEqual({
            actor_entity_id: "n1",
            action_kind: "attack",
            target_entity_id: "n2",
            hit: true,
            damage_amount: 6,
        })
    })

    it("needs an actor and a sensible damage and round", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1", active())
        const form = await screen.findByRole("form", { name: "Record a turn" })
        fireEvent.click(within(form).getByRole("button", { name: "Record turn" }))
        expect(await screen.findByText(/Choose who is taking the turn/)).toBeInTheDocument()
        fireEvent.change(within(form).getByRole("combobox", { name: "Who acts" }), { target: { value: "n1" } })
        fireEvent.change(within(form).getByRole("textbox", { name: /Damage/ }), { target: { value: "-3" } })
        fireEvent.click(within(form).getByRole("button", { name: "Record turn" }))
        expect(await screen.findByText(/Damage must be a whole number/)).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/e1/turns`)).toHaveLength(0)
    })

    it("ends the encounter with the outcomes that were chosen", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1", active())
        const form = await screen.findByRole("form", { name: "End the encounter" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Outcome for Bryn" }), { target: { value: "defeated" } })
        fireEvent.click(within(form).getByRole("button", { name: "End encounter" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/e1/end`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/e1/end`)[0]!.body).toEqual({
            outcomes: [{ participant_entity_id: "n2", outcome: "defeated" }],
        })
    })

    it("aborts an active encounter after confirming", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1", active())
        const form = await screen.findByRole("form", { name: "End the encounter" })
        fireEvent.click(within(form).getByRole("button", { name: "Abort encounter" }))
        const dialog = await screen.findByRole("dialog", { name: "Abort this encounter?" })
        fireEvent.click(within(dialog).getByRole("button", { name: "Abort encounter" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/e1/abort`)).toHaveLength(1))
    })

    it("shows a finished encounter as a record with outcomes", async () => {
        setup(
            "/app/c1/sessions/s1/encounters/e1",
            active({
                status: "completed",
                participants: [
                    { ...encounter().participants[1], outcome: "defeated" },
                ],
            }),
        )
        expect(await screen.findByText(/defeated/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Record a turn" })).not.toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "End the encounter" })).not.toBeInTheDocument()
    })
})
