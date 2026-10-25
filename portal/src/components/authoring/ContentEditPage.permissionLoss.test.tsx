import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import { ContentEditPage } from "./ContentEditPage"
import type { ContentEditConfig, EditableView } from "./ContentEditPage"
import { TextField } from "./fields"

// Losing the right to edit (or to read) the record while its edit form is open: the form goes, the
// server's private content goes with it, nothing more is sent, and only what the person themselves
// typed is shown back (utils/retainedChanges).

interface ThingView extends EditableView {
    name: string
    secret: string
}
interface ThingValues {
    name: string
    secret: string
}

const SECRET = "The vault key is under the third flagstone."

const view = (over: object = {}): ThingView => ({
    row_version: 3,
    canon_status: "draft",
    available_actions: ["update"],
    blocked_actions: [],
    name: "Founders Hall",
    secret: SECRET,
    ...over,
})

const config: ContentEditConfig<ThingView, { ok: true }, ThingValues, ThingValues> = {
    noun: "thing",
    heading: "Edit thing",
    entityParam: "thingId",
    breadcrumbLabel: "Things",
    worldPath: (c) => `/app/${c}/things`,
    detailPath: (c, id) => `/app/${c}/things/${id}`,
    viewPath: (c, id) => `/campaigns/${c}/authoring/things/${id}`,
    optionsPath: (c) => `/campaigns/${c}/authoring/things/options`,
    name: (v) => v.name,
    valuesFromView: (v) => ({ name: v.name, secret: v.secret }),
    same: (a, b) => a.name === b.name && a.secret === b.secret,
    validate: () => [],
    toBody: (values) => values,
    update: async () => undefined,
    renderFields: ({ values, setValues }) => (
        <>
            <TextField id="thing-name" label="Name" value={values.name} onChange={(name) => setValues({ ...values, name })} />
            <TextField
                id="thing-secret"
                label="Secret"
                value={values.secret}
                onChange={(secret) => setValues({ ...values, secret })}
            />
        </>
    ),
    summarize: (values) => <p>{values.name}</p>,
    canonWarning: "",
    saved: "Saved",
}

// The shell posts through the config's `update`; here it posts for real so the mock server answers.
const posting: typeof config = {
    ...config,
    update: async (campaignId, entityId, body) => {
        const { apiRequest } = await import("../../api/http")
        return apiRequest("POST", `/campaigns/${campaignId}/authoring/things/${entityId}/update`, { body })
    },
}

function setup() {
    const server = installMockServer()
    server.on("GET", "/campaigns/c1/authoring/things/t1", () => ({ body: current }))
    server.on("GET", "/campaigns/c1/authoring/things/options", { body: { ok: true } })
    let current: ThingView | { status: number } = view()
    const rendered = renderAuthoringRoutes({
        initialEntry: "/app/c1/things/t1/edit",
        bootstrap: bootstrapWith(),
        routes: [
            { path: "/app/:campaignId/things/:thingId/edit", element: <ContentEditPage config={posting} /> },
            { path: "/app/:campaignId/things/:thingId", element: <p>Thing page</p> },
        ],
    })
    return { server, setCurrent: (next: ThingView) => (current = next), ...rendered }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

const DENIED = {
    status: 403,
    body: { error: { code: "world_authority_required", message: "m", correlation_id: "c" } },
}

describe("ContentEditPage when the right to edit is lost", () => {
    it("on a refused save, drops the form and shows back only what was typed", async () => {
        const { server } = setup()
        server.on("POST", "/campaigns/c1/authoring/things/t1/update", DENIED)
        const name = await screen.findByLabelText("Name")
        fireEvent.change(name, { target: { value: "Founders' Hall" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))

        const panel = await screen.findByRole("region", { name: "Permission lost" })
        expect(panel).toHaveTextContent("You no longer have permission to edit this thing")
        expect(panel).toHaveTextContent("Founders' Hall")
        // The Save button that had focus is gone: focus is on the explanation, not the page body.
        expect(within(panel).getByRole("heading", { name: /no longer have permission/ })).toHaveFocus()
        // The record the server sent in its private read is not preserved as an "unsaved draft".
        expect(screen.queryByText(new RegExp(SECRET))).toBeNull()
        expect(screen.queryByDisplayValue(SECRET)).toBeNull()
        expect(screen.queryByRole("button", { name: "Save" })).toBeNull()
        // Exactly one write was ever attempted.
        await waitFor(() => expect(server.callsTo("POST", "/campaigns/c1/authoring/things/t1/update")).toHaveLength(1))
    })

    it("keeps nothing at all when the person typed nothing before the save was refused", async () => {
        const { server } = setup()
        server.on("POST", "/campaigns/c1/authoring/things/t1/update", DENIED)
        await screen.findByLabelText("Name")
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        const panel = await screen.findByRole("region", { name: "Permission lost" })
        expect(panel).not.toHaveTextContent(SECRET)
        expect(panel).not.toHaveTextContent("Founders Hall")
    })

    it("when the read itself is refused while editing, shows what was typed and nothing the server sent", async () => {
        const { server } = setup()
        server.on("POST", "/campaigns/c1/authoring/things/t1/update", {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        const name = await screen.findByLabelText("Name")
        fireEvent.change(name, { target: { value: "Renamed hall" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        // Someone changed the record, and by the time the latest version is requested the person's
        // world role has ended: the read is refused.
        const loadLatest = await screen.findByRole("button", { name: /Load latest/ })
        server.on("GET", "/campaigns/c1/authoring/things/t1", DENIED)
        fireEvent.click(loadLatest)
        const panel = await screen.findByRole("region", { name: "Permission lost" })
        expect(panel).toHaveTextContent("Renamed hall")
        expect(screen.queryByText(new RegExp(SECRET))).toBeNull()
        expect(screen.queryByDisplayValue(SECRET)).toBeNull()
    })

    it("a record that was never readable is the plain unavailable message", async () => {
        const server = installMockServer()
        server.on("GET", "/campaigns/c1/authoring/things/t1", DENIED)
        server.on("GET", "/campaigns/c1/authoring/things/options", { body: { ok: true } })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/things/t1/edit",
            bootstrap: bootstrapWith(),
            routes: [{ path: "/app/:campaignId/things/:thingId/edit", element: <ContentEditPage config={posting} /> }],
        })
        expect(await screen.findByText(/does not exist, or you do not have access to it/)).toBeInTheDocument()
        expect(screen.queryByRole("region", { name: "Permission lost" })).toBeNull()
    })
})
