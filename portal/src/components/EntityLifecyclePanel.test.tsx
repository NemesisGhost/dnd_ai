import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { EntityLifecyclePanel } from "./EntityLifecyclePanel"

const BASE = "/campaigns/mundivita/entities/e1/lifecycle"

const view = (over: object = {}) => ({
    entity_id: "e1",
    entity_type_code: "location",
    canonical_name: "Sunken Archive",
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 3,
    lifecycle_managed: true,
    superseded_by: null,
    available_actions: ["submit_for_review", "archive", "delete_draft"],
    blocked_actions: [{ action: "restore", reason: "entity_not_archived" }],
    ...over,
})

const campaign = (capabilities: string[]) => ({
    ...sessionBootstrapFixture.campaigns[0]!,
    campaign_id: "mundivita",
    capabilities,
})

function setup(opts: { caps?: string[]; initial?: object } = {}) {
    const server = installMockServer()
    let current = view(opts.initial)
    server.on("GET", BASE, () => ({ body: current }))
    const changed = { count: 0 }
    const rendered = renderAuthoringRoutes({
        initialEntry: "/app/mundivita/world/location/e1",
        routes: [
            {
                path: "/app/:campaignId/world/location/:entityId",
                element: (
                    <EntityLifecyclePanel
                        campaignId="mundivita"
                        entityId="e1"
                        onChanged={() => {
                            changed.count += 1
                        }}
                    />
                ),
            },
            { path: "/app/:campaignId/world", element: <p>World list</p> },
        ],
        bootstrap: bootstrapWith({ campaigns: [campaign(opts.caps ?? ["canon.edit", "campaign.view"])] }),
    })
    return { server, changed, setCurrent: (v: object) => (current = view(v)), ...rendered }
}

describe("EntityLifecyclePanel", () => {
    it("sends no request and renders nothing for a member without canon.edit", async () => {
        const { server } = setup({ caps: ["campaign.view"] })
        await new Promise((r) => setTimeout(r, 30))
        expect(server.calls).toHaveLength(0)
        expect(screen.queryByRole("heading", { name: "Lifecycle" })).not.toBeInTheDocument()
    })

    it("renders nothing for a record the server says is not lifecycle-managed", async () => {
        const { server } = setup({ initial: { lifecycle_managed: false, available_actions: [] } })
        await waitFor(() => expect(server.callsTo("GET", BASE)).toHaveLength(1))
        expect(screen.queryByRole("heading", { name: "Lifecycle" })).not.toBeInTheDocument()
    })

    it("shows the status and exactly the actions the server offers, explaining blocked ones", async () => {
        setup()
        await screen.findByRole("heading", { name: "Lifecycle" })
        expect(screen.getByRole("button", { name: "Submit for review" })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Archive" })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Delete draft" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Publish as canon" })).not.toBeInTheDocument()
        expect(screen.getByRole("list", { name: "Unavailable lifecycle actions" })).toHaveTextContent(
            "Restore unavailable: the record is not archived.",
        )
    })

    it("submits for review immediately, refetches, notifies the page, and announces", async () => {
        const { server, changed, setCurrent } = setup()
        server.on("POST", `${BASE}/submit-for-review`, () => {
            setCurrent({ canon_status: "proposed", row_version: 4, available_actions: ["return_to_draft", "approve"] })
            return { body: { entity_id: "e1", canon_status: "proposed", lifecycle_status: "active", row_version: 4 } }
        })
        fireEvent.click(await screen.findByRole("button", { name: "Submit for review" }))
        await screen.findByRole("button", { name: "Approve" })
        expect(server.callsTo("POST", `${BASE}/submit-for-review`)[0]!.body).toEqual({ expected_row_version: 3 })
        expect(screen.queryByRole("button", { name: "Submit for review" })).not.toBeInTheDocument()
        expect(changed.count).toBe(1)
        expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Submitted for review")
    })

    it("archives through a confirmation with an optional reason", async () => {
        const { server, setCurrent } = setup()
        server.on("POST", `${BASE}/archive`, () => {
            setCurrent({ lifecycle_status: "archived", row_version: 4, available_actions: ["restore"] })
            return { body: { entity_id: "e1", canon_status: "draft", lifecycle_status: "archived", row_version: 4 } }
        })
        fireEvent.click(await screen.findByRole("button", { name: "Archive" }))
        const dialog = screen.getByRole("dialog", { name: "Archive this record?", hidden: true })
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason/ }), { target: { value: "obsolete" } })
        fireEvent.click(within(dialog).getByRole("button", { name: "Archive" }))
        await screen.findByRole("button", { name: "Restore" })
        expect(server.callsTo("POST", `${BASE}/archive`)[0]!.body).toEqual({
            expected_row_version: 3,
            reason: "obsolete",
        })
    })

    it("requires a reason to restore and sends none until one is given", async () => {
        const { server } = setup({
            initial: { lifecycle_status: "archived", available_actions: ["restore"], blocked_actions: [] },
        })
        server.on("POST", `${BASE}/restore`, {
            body: { entity_id: "e1", canon_status: "draft", lifecycle_status: "active", row_version: 4 },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Restore" }))
        const dialog = screen.getByRole("dialog", { name: "Restore this record?", hidden: true })
        fireEvent.click(within(dialog).getByRole("button", { name: "Restore" }))
        expect(server.callsTo("POST", `${BASE}/restore`)).toHaveLength(0)
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason/ }), { target: { value: "needed again" } })
        fireEvent.click(within(dialog).getByRole("button", { name: "Restore" }))
        await waitFor(() => expect(server.callsTo("POST", `${BASE}/restore`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/restore`)[0]!.body).toEqual({
            expected_row_version: 3,
            reason: "needed again",
        })
    })

    it("deletes a draft with a required reason and returns to the World list", async () => {
        const { server } = setup()
        server.on("POST", `${BASE}/delete-draft`, { body: { entity_id: "e1", deleted: true } })
        fireEvent.click(await screen.findByRole("button", { name: "Delete draft" }))
        const dialog = screen.getByRole("dialog", { name: "Delete this draft?", hidden: true })
        expect(dialog).toHaveTextContent("cannot be undone")
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason/ }), { target: { value: "test fixture" } })
        fireEvent.click(within(dialog).getByRole("button", { name: "Delete draft" }))
        await screen.findByText("World list")
    })

    it("supersedes with a replacement chosen from server candidates", async () => {
        const { server, setCurrent } = setup({
            initial: { canon_status: "canon", available_actions: ["supersede", "archive"], blocked_actions: [] },
        })
        server.on("GET", /replacement-candidates/, {
            body: {
                items: [{ entity_id: "e2", canonical_name: "New Archive", canon_status: "canon", row_version: 7 }],
                next_cursor: null,
            },
        })
        server.on("POST", `${BASE}/supersede`, () => {
            setCurrent({ canon_status: "superseded", row_version: 4, available_actions: ["archive"] })
            return { body: { entity_id: "e1", canon_status: "superseded", lifecycle_status: "active", row_version: 4 } }
        })
        fireEvent.click(await screen.findByRole("button", { name: "Supersede…" }))
        const dialog = screen.getByRole("dialog", { name: "Replace Sunken Archive?", hidden: true })
        const confirm = within(dialog).getByRole("button", { name: "Supersede" })
        expect(confirm).toBeDisabled()
        fireEvent.click(await within(dialog).findByRole("radio", { name: "New Archive" }))
        fireEvent.click(confirm)
        await waitFor(() => expect(server.callsTo("POST", `${BASE}/supersede`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/supersede`)[0]!.body).toEqual({
            expected_row_version: 3,
            replacement_entity_id: "e2",
            replacement_expected_row_version: 7,
        })
        await waitFor(() => expect(screen.queryByRole("button", { name: "Supersede…" })).not.toBeInTheDocument())
    })

    it("explains an empty candidate list", async () => {
        const { server } = setup({
            initial: { canon_status: "canon", available_actions: ["supersede"], blocked_actions: [] },
        })
        server.on("GET", /replacement-candidates/, { body: { items: [], next_cursor: null } })
        fireEvent.click(await screen.findByRole("button", { name: "Supersede…" }))
        expect(await screen.findByText(/No eligible replacements/)).toBeInTheDocument()
    })

    it("keeps the dialog open on a stale write and offers to load the latest version", async () => {
        const { server } = setup()
        server.on("POST", `${BASE}/archive`, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Archive" }))
        const dialog = screen.getByRole("dialog", { name: "Archive this record?", hidden: true })
        fireEvent.click(within(dialog).getByRole("button", { name: "Archive" }))
        expect(await within(dialog).findByText(/Someone else changed this record/)).toBeInTheDocument()
        fireEvent.click(within(dialog).getByRole("button", { name: "Load latest version" }))
        await waitFor(() => expect(server.callsTo("GET", BASE).length).toBeGreaterThan(1))
    })

    it("shows the replacement for a superseded record", async () => {
        setup({
            initial: {
                canon_status: "superseded",
                superseded_by: { entity_id: "e2", canonical_name: "New Archive" },
                available_actions: [],
                blocked_actions: [],
            },
        })
        expect(await screen.findByText("Replaced by New Archive.")).toBeInTheDocument()
        expect(screen.getByText("No lifecycle actions are available right now.")).toBeInTheDocument()
    })
})
