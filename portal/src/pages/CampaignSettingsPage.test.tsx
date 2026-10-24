import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import type { SessionBootstrap } from "../types/bootstrap"
import { CampaignSettingsPage } from "./CampaignSettingsPage"

afterEach(() => {
    vi.unstubAllGlobals()
})

const SETTINGS = "/campaigns/c1/settings"
const UPDATE = "/campaigns/c1/update"
const ARCHIVE = "/campaigns/c1/archive"

const settings = (extra: Record<string, unknown> = {}) => ({
    campaign_id: "c1",
    name: "The Hollow Road",
    description: null,
    lifecycle_status: "active",
    row_version: 3,
    world: { world_id: "w1", name: "Mundivita" },
    timeline: { timeline_id: "t1", name: "Primary" },
    ruleset_version: { ruleset_version_id: "r1", ruleset_display_name: "D&D 2024", version_label: "1" },
    available_actions: ["update", "archive"],
    blocked_actions: [],
    ...extra,
})

const bootstrap = (): SessionBootstrap =>
    bootstrapWith({
        campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["access.manage"] }],
    })

// Handlers are registered before the page mounts, because it reads as soon as it renders.
function setup(register: (server: MockServer) => void, onRefresh?: () => Promise<SessionBootstrap>) {
    const server = installMockServer()
    register(server)
    renderAuthoringRoutes({
        initialEntry: "/app/c1/settings",
        bootstrap: bootstrap(),
        onRefresh,
        routes: [
            { path: "/app/:campaignId/settings", element: <CampaignSettingsPage /> },
            { path: "/campaigns", element: <h1>Campaigns stub</h1> },
            { path: "/app/:campaignId/home", element: <h1>Home stub</h1> },
        ],
    })
    return server
}

const rename = (name: string) => fireEvent.change(screen.getByLabelText(/Campaign name/), { target: { value: name } })
const save = () => fireEvent.click(screen.getByRole("button", { name: "Save" }))

// A bootstrap refresh that fails once and then works.
function flakyRefresh() {
    let reads = 0
    return vi.fn(async () => {
        reads += 1
        if (reads === 1) throw new Error("boom")
        return bootstrap()
    })
}

describe("campaign settings: saves, refreshes and read states", () => {
    it("explains a confirmed save whose menu refresh failed, and retries only the read", async () => {
        const onRefresh = flakyRefresh()
        let current = settings()
        const server = setup((s) => {
            s.on("GET", SETTINGS, () => ({ body: current }))
            s.on("POST", UPDATE, () => {
                current = settings({ name: "Renamed", row_version: 4 })
                return { body: { campaign_id: "c1", row_version: 4 } }
            })
        }, onRefresh)
        await screen.findByLabelText(/Campaign name/)
        rename("Renamed")
        save()
        const notice = await screen.findByRole("status")
        expect(notice).toHaveTextContent("Saved. The latest campaign name in menus and lists could not be loaded")
        expect(notice).not.toHaveTextContent("boom")
        // The settings themselves reloaded, so the form shows the new version and stays usable.
        expect(await screen.findByDisplayValue("Renamed")).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Save" })).toBeEnabled()
        expect(screen.queryByText(/not available/)).toBeNull()

        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        await waitFor(() => expect(screen.queryByRole("status")).toBeNull())
        expect(onRefresh).toHaveBeenCalledTimes(2)
        expect(server.callsTo("POST", UPDATE)).toHaveLength(1)
    })

    it("holds another save while the settings re-read failed, then retries with a read only", async () => {
        let current = settings()
        let failRead = false
        const server = setup((s) => {
            s.on("GET", SETTINGS, () => (failRead ? { status: 500, body: {} } : { body: current }))
            s.on("POST", UPDATE, () => {
                current = settings({ name: "Renamed", row_version: 4 })
                failRead = true
                return { body: { campaign_id: "c1", row_version: 4 } }
            })
        })
        await screen.findByLabelText(/Campaign name/)
        rename("Renamed")
        save()
        expect(await screen.findByRole("status")).toHaveTextContent(
            "Saved. The latest campaign settings could not be loaded",
        )
        // What was typed is still there, and a version-checked save is held.
        expect(screen.getByLabelText(/Campaign name/)).toHaveValue("Renamed")
        expect(screen.getByRole("button", { name: "Save" })).toBeDisabled()
        expect(screen.queryByRole("button", { name: "Retry" })).toBeNull()

        failRead = false
        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        await waitFor(() => expect(screen.queryByRole("status")).toBeNull())
        expect(screen.getByRole("button", { name: "Save" })).toBeEnabled()
        // One write; then the first read, the failed read and the successful read: the retry only read.
        expect(server.callsTo("POST", UPDATE)).toHaveLength(1)
        expect(server.callsTo("GET", SETTINGS)).toHaveLength(3)
    })

    it("keeps the input and retries an unconfirmed save with the same key and body", async () => {
        let attempts = 0
        const server = setup((s) => {
            s.on("GET", SETTINGS, { body: settings() })
            s.on("POST", UPDATE, () => {
                attempts += 1
                return attempts === 1 ? { networkError: true } : { body: { campaign_id: "c1", row_version: 4 } }
            })
        })
        await screen.findByLabelText(/Campaign name/)
        rename("Renamed")
        save()
        const alert = await screen.findByRole("alert")
        expect(alert).toHaveTextContent("cannot tell whether this was saved")
        expect(screen.getByLabelText(/Campaign name/)).toHaveValue("Renamed")
        fireEvent.click(screen.getByRole("button", { name: "Retry" }))
        await waitFor(() => expect(server.callsTo("POST", UPDATE)).toHaveLength(2))
        const [first, second] = server.callsTo("POST", UPDATE)
        expect(second!.body).toEqual(first!.body)
        expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
    })

    it("gives edited input after an unconfirmed save a new key", async () => {
        const server = setup((s) => {
            s.on("GET", SETTINGS, { body: settings() })
            s.on("POST", UPDATE, { networkError: true })
        })
        await screen.findByLabelText(/Campaign name/)
        rename("Renamed")
        save()
        await screen.findByRole("alert")
        rename("Renamed again")
        save()
        await waitFor(() => expect(server.callsTo("POST", UPDATE)).toHaveLength(2))
        const [first, second] = server.callsTo("POST", UPDATE)
        expect(second!.headers["Idempotency-Key"]).not.toBe(first!.headers["Idempotency-Key"])
    })

    it("keeps the draft on a stale-version conflict until the person loads the latest", async () => {
        let current = settings()
        setup((s) => {
            s.on("GET", SETTINGS, () => ({ body: current }))
            s.on("POST", UPDATE, () => {
                current = settings({ name: "Someone else", row_version: 4 })
                return { status: 409, body: { error: { code: "stale_write", message: "m", correlation_id: "c" } } }
            })
        })
        await screen.findByLabelText(/Campaign name/)
        rename("My draft")
        save()
        fireEvent.click(await screen.findByRole("button", { name: "Load latest version" }))
        // The form is rebuilt on the latest version; the draft waits beside it.
        await waitFor(() => expect(screen.getByLabelText(/Campaign name/)).toHaveValue("Someone else"))
        fireEvent.click(screen.getByRole("button", { name: "Re-apply my changes" }))
        expect(screen.getByLabelText(/Campaign name/)).toHaveValue("My draft")
    })

    it("stays on the page when the campaign was archived but the list did not refresh, and leaves on retry", async () => {
        const onRefresh = flakyRefresh()
        const server = setup((s) => {
            s.on("GET", SETTINGS, { body: settings() })
            s.on("POST", ARCHIVE, { body: { campaign_id: "c1", row_version: 4, lifecycle_status: "archived" } })
        }, onRefresh)
        await screen.findByLabelText(/Campaign name/)
        fireEvent.click(screen.getByRole("button", { name: "Archive campaign" }))
        // The confirm button in the dialog is the last control with this name.
        const buttons = await screen.findAllByRole("button", { name: "Archive campaign" })
        fireEvent.click(buttons[buttons.length - 1]!)
        const notice = await screen.findByRole("status")
        expect(notice).toHaveTextContent("Campaign archived. The latest campaign list could not be loaded")
        expect(screen.queryByRole("heading", { name: "Campaigns stub" })).toBeNull()
        // Changing an archived campaign's settings is not offered.
        expect(screen.getByRole("button", { name: "Save" })).toBeDisabled()

        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        expect(await screen.findByRole("heading", { name: "Campaigns stub" })).toBeInTheDocument()
        expect(server.callsTo("POST", ARCHIVE)).toHaveLength(1)
    })

    it.each([403, 404])("shows no settings and says they are unavailable when the read answers %i", async (status) => {
        setup((s) => {
            s.on("GET", SETTINGS, { status, body: { error: { code: "x", message: "m", correlation_id: "c" } } })
        })
        expect(await screen.findByRole("alert")).toHaveTextContent("The campaign settings are not available.")
        expect(screen.queryByLabelText(/Campaign name/)).toBeNull()
        expect(screen.queryByRole("button", { name: "Try again" })).toBeNull()
    })

    it("offers a retry that only reads when the first load fails recoverably", async () => {
        let fail = true
        const server = setup((s) => {
            s.on("GET", SETTINGS, () => (fail ? { status: 500, body: {} } : { body: settings() }))
        })
        expect(await screen.findByRole("alert")).toHaveTextContent("The campaign settings could not be loaded.")
        fail = false
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        expect(await screen.findByLabelText(/Campaign name/)).toHaveValue("The Hollow Road")
        expect(server.callsTo("POST", /./)).toHaveLength(0)
    })
})

describe("campaign settings: edits after a confirmed save whose re-read failed", () => {
    // The server holds version 4 ("Renamed") but the re-read after the save fails until `failRead` clears.
    function afterConfirmedSave() {
        let current = settings()
        const state = { failRead: false }
        const server = setup((s) => {
            s.on("GET", SETTINGS, () => (state.failRead ? { status: 500, body: {} } : { body: current }))
            s.on("POST", UPDATE, () => {
                current = settings({ name: "Renamed", row_version: 4 })
                state.failRead = true
                return { body: { campaign_id: "c1", row_version: 4 } }
            })
            s.on("POST", ARCHIVE, { body: { campaign_id: "c1", row_version: 5, lifecycle_status: "archived" } })
        })
        return { server, state }
    }

    async function saveRenamed() {
        await screen.findByLabelText(/Campaign name/)
        rename("Renamed")
        save()
        await screen.findByRole("status")
    }

    it("keeps what was typed after the save when the latest version is loaded", async () => {
        const { server, state } = afterConfirmedSave()
        await saveRenamed()
        rename("Typed after the save")
        state.failRead = false
        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        await waitFor(() => expect(screen.queryByRole("status")).toBeNull())
        // The form is the same one: the draft was not replaced by the loaded name.
        expect(screen.getByLabelText(/Campaign name/)).toHaveValue("Typed after the save")
        save()
        await waitFor(() => expect(server.callsTo("POST", UPDATE)).toHaveLength(2))
        expect(server.callsTo("POST", UPDATE)[1]!.body).toMatchObject({
            expected_row_version: 4,
            name: "Typed after the save",
        })
    })

    it("treats the saved values as saved, but guards navigation for anything typed after them", async () => {
        const { state } = afterConfirmedSave()
        await saveRenamed()
        void state
        // Nothing typed since the save: leaving is not discarding anything.
        fireEvent.click(screen.getByRole("link", { name: "Back to Campaign Home" }))
        expect(await screen.findByRole("heading", { name: "Home stub" })).toBeInTheDocument()
    })

    it("holds navigation behind the discard dialog when a draft was typed after the save", async () => {
        afterConfirmedSave()
        await saveRenamed()
        rename("Typed after the save")
        fireEvent.click(screen.getByRole("link", { name: "Back to Campaign Home" }))
        expect(await screen.findByRole("button", { name: "Keep editing" })).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: "Home stub" })).toBeNull()
        fireEvent.click(screen.getByRole("button", { name: "Keep editing" }))
        expect(screen.getByLabelText(/Campaign name/)).toHaveValue("Typed after the save")
    })

    it("cannot archive with the obsolete version until the latest settings load", async () => {
        const { server, state } = afterConfirmedSave()
        await saveRenamed()
        expect(screen.getByRole("button", { name: "Archive campaign" })).toBeDisabled()
        expect(server.callsTo("POST", ARCHIVE)).toHaveLength(0)
        state.failRead = false
        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        await waitFor(() => expect(screen.getByRole("button", { name: "Archive campaign" })).toBeEnabled())
        fireEvent.click(screen.getByRole("button", { name: "Archive campaign" }))
        const buttons = await screen.findAllByRole("button", { name: "Archive campaign" })
        fireEvent.click(buttons[buttons.length - 1]!)
        await waitFor(() => expect(server.callsTo("POST", ARCHIVE)).toHaveLength(1))
        expect(server.callsTo("POST", ARCHIVE)[0]!.body).toMatchObject({ expected_row_version: 4 })
    })
})
