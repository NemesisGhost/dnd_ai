import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { ProvenancePage } from "../pages/ProvenancePage"
import { EntitySourcesSection } from "./EntitySourcesSection"

const PROVENANCE = "/campaigns/c1/entities/e1/provenance"
const SOURCES = "/campaigns/c1/sources"

const link = (overrides: object = {}) => ({
    source_id: "s1",
    source_type_label: "Session notes",
    title: "Session 3 notes",
    reference: "The inn scene",
    attached_at: "2026-01-02T10:00:00Z",
    attached_by_name: "Gina",
    detached_at: null,
    detached_by_name: null,
    is_attached: true,
    ...overrides,
})

function provenance(overrides: object = {}) {
    return {
        entity_id: "e1",
        name: "Stonebridge",
        entity_type_code: "settlement",
        canon_status: "canon",
        lifecycle_status: "active",
        created_at: "2026-01-01T09:00:00Z",
        created_by_name: "Gina",
        origin: {
            source_id: "o1",
            source_type: "gm_entry",
            source_type_label: "GM entry",
            title: "GM entry",
            reference: null,
            created_by_name: "Gina",
            attached_count: 0,
        },
        links: [link()],
        transitions: [
            { label: "Published as canon", previous_status: "approved", new_status: "canon", actor_name: "Gina", recorded_at: "2026-01-01T10:00:00Z" },
        ],
        superseded_by: null,
        supersedes: [],
        ...overrides,
    }
}

const LIST = {
    items: [
        { source_id: "s1", source_type: "session_notes", source_type_label: "Session notes", title: "Session 3 notes", reference: null, created_by_name: null, attached_count: 1 },
        { source_id: "s2", source_type: "published_reference", source_type_label: "Published reference", title: "Core book", reference: null, created_by_name: null, attached_count: 0 },
    ],
    source_types: [
        { value: "published_reference", label: "Published reference" },
        { value: "session_notes", label: "Session notes" },
    ],
    limits: { title_max_length: 500, reference_max_length: 2000 },
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function render(element: React.ReactElement, path = "/app/c1/x", route = "/app/:campaignId/x", capabilities = ["canon.edit"]) {
    const server = installMockServer()
    server.on("GET", PROVENANCE, () => ({ body: provenance() }))
    server.on("GET", SOURCES, { body: LIST })
    server.on("POST", SOURCES, { status: 201, body: { ...LIST.items[1], source_id: "s3", title: "New one" } })
    server.on("POST", /sources\/(attach|detach)$/, { body: provenance() })
    renderAuthoringRoutes({
        initialEntry: path,
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [{ path: route, element }],
    })
    return server
}

describe("EntitySourcesSection", () => {
    it("shows where the record came from and the sources attached now", async () => {
        render(<EntitySourcesSection campaignId="c1" entityId="e1" category="location" />)
        expect(await screen.findByText(/Session 3 notes \(Session notes\): The inn scene/)).toBeInTheDocument()
        expect(screen.getByText("GM entry")).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "View provenance" })).toHaveAttribute(
            "href",
            "/app/c1/world/location/e1/provenance",
        )
    })

    it("detaches a source", async () => {
        const server = render(<EntitySourcesSection campaignId="c1" entityId="e1" />)
        fireEvent.click(await screen.findByRole("button", { name: "Detach Session 3 notes" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${PROVENANCE.replace("provenance", "sources/detach")}`)).toHaveLength(1))
        expect(server.callsTo("POST", PROVENANCE.replace("provenance", "sources/detach"))[0]!.body).toEqual({
            source_id: "s1",
        })
    })

    it("attaches an existing source that is not already attached", async () => {
        const server = render(<EntitySourcesSection campaignId="c1" entityId="e1" />)
        const form = await screen.findByRole("form", { name: "Attach an existing source" })
        const options = within(form).getAllByRole("option").map((o) => o.textContent)
        expect(options).toEqual(["Choose a source", "Core book (Published reference)"])
        fireEvent.change(within(form).getByRole("combobox", { name: "Source" }), { target: { value: "s2" } })
        fireEvent.click(within(form).getByRole("button", { name: "Attach source" }))
        await vi.waitFor(() => expect(server.callsTo("POST", PROVENANCE.replace("provenance", "sources/attach"))).toHaveLength(1))
        expect(server.callsTo("POST", PROVENANCE.replace("provenance", "sources/attach"))[0]!.body).toEqual({
            source_id: "s2",
        })
    })

    it("writes a new source and attaches it", async () => {
        const server = render(<EntitySourcesSection campaignId="c1" entityId="e1" />)
        const form = await screen.findByRole("form", { name: "Write a new source" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Type of source" }), { target: { value: "published_reference" } })
        fireEvent.change(within(form).getByRole("textbox", { name: "Title" }), { target: { value: "  New one " } })
        fireEvent.change(within(form).getByRole("textbox", { name: /Reference/ }), { target: { value: "p. 9" } })
        fireEvent.click(within(form).getByRole("button", { name: "Write and attach source" }))
        await vi.waitFor(() => expect(server.callsTo("POST", SOURCES)).toHaveLength(1))
        expect(server.callsTo("POST", SOURCES)[0]!.body).toEqual({
            source_type: "published_reference",
            title: "New one",
            reference: "p. 9",
        })
        await vi.waitFor(() =>
            expect(server.callsTo("POST", PROVENANCE.replace("provenance", "sources/attach"))).toHaveLength(1),
        )
        expect(server.callsTo("POST", PROVENANCE.replace("provenance", "sources/attach"))[0]!.body).toEqual({
            source_id: "s3",
        })
    })

    it("needs a type and title for a new source", async () => {
        const server = render(<EntitySourcesSection campaignId="c1" entityId="e1" />)
        const form = await screen.findByRole("form", { name: "Write a new source" })
        fireEvent.click(within(form).getByRole("button", { name: "Write and attach source" }))
        expect(await screen.findByText(/Choose a type and enter a title/)).toBeInTheDocument()
        expect(server.callsTo("POST", SOURCES)).toHaveLength(0)
    })

    it("shows nothing when the provenance read is refused", async () => {
        const server = installMockServer()
        server.on("GET", PROVENANCE, { status: 403, body: { error: { code: "forbidden", message: "m", correlation_id: "c" } } })
        server.on("GET", SOURCES, { status: 403, body: { error: { code: "forbidden", message: "m", correlation_id: "c" } } })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/x",
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1" }],
            }),
            routes: [{ path: "/app/:campaignId/x", element: <EntitySourcesSection campaignId="c1" entityId="e1" /> }],
        })
        await new Promise((resolve) => setTimeout(resolve, 50))
        expect(screen.queryByRole("heading", { name: "Sources" })).not.toBeInTheDocument()
    })
})

describe("ProvenancePage", () => {
    const renderPage = (view: object = provenance(), capabilities = ["canon.edit"]) => {
        const server = installMockServer()
        server.on("GET", PROVENANCE, { body: view })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/world/location/e1/provenance",
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
            }),
            routes: [{ path: "/app/:campaignId/world/:category/:entityId/provenance", element: <ProvenancePage /> }],
        })
        return server
    }

    it("shows the creator, sources, detached sources and the history", async () => {
        renderPage(
            provenance({
                links: [link(), link({ source_id: "s9", title: "Old book", is_attached: false, detached_at: "2026-02-01T10:00:00Z", detached_by_name: "Gina" })],
                superseded_by: { entity_id: "e2", name: "New Town" },
                supersedes: [{ entity_id: "e0", name: "Old Town" }],
            }),
        )
        expect(await screen.findByRole("heading", { name: "Provenance" })).toBeInTheDocument()
        expect(screen.getByText(/Session 3 notes \(Session notes\): The inn scene/)).toBeInTheDocument()
        expect(screen.getByRole("heading", { name: "Sources detached" })).toBeInTheDocument()
        expect(screen.getByText(/Old book \(Session notes\)\. Attached/)).toBeInTheDocument()
        expect(screen.getByText(/Published as canon \(approved to canon\)/)).toBeInTheDocument()
        expect(screen.getByText("Superseded by New Town.")).toBeInTheDocument()
        expect(screen.getByText("Replaces Old Town.")).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Stonebridge" })).toHaveAttribute(
            "href",
            "/app/c1/world/location/e1",
        )
    })

    it("refuses people without canon.edit", async () => {
        renderPage(provenance(), [])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
    })
})
