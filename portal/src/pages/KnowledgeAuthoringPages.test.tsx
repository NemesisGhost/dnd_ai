import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { TEST_CSRF, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CreateKnowledgePage, EditKnowledgePage } from "./KnowledgeAuthoringPages"

const OPTIONS = {
    can_create: true,
    knowledge_types: [
        { value: "secret", label: "Secret" },
        { value: "rumor", label: "Rumor" },
    ],
    truth_statuses: [
        { value: "true", label: "True" },
        { value: "false", label: "False" },
    ],
    sensitivities: [
        { value: "public", label: "Public" },
        { value: "secret", label: "Secret" },
    ],
    limits: { statement_max_length: 4000, change_note_max_length: 1000 },
}

const VIEW = {
    knowledge_item_id: "k1",
    statement: "The duke is a vampire.",
    knowledge_type: "secret",
    truth_status: "true",
    sensitivity: "secret",
    subject: { entity_id: "l1", name: "Keep", canon_status: "canon", lifecycle_status: "active" },
    in_use: false,
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 3,
    available_actions: ["update"],
    blocked_actions: [],
    field_locks: [],
}

const OPTIONS_PATH = "/campaigns/c1/authoring/knowledge/options"
const CREATE_PATH = "/campaigns/c1/authoring/knowledge"
const VIEW_PATH = "/campaigns/c1/authoring/knowledge/k1"
const UPDATE_PATH = "/campaigns/c1/authoring/knowledge/k1/update"

function mockSubjects(server: ReturnType<typeof installMockServer>) {
    server.on("GET", /\/authoring\/knowledge\/subject-options/, {
        body: {
            items: [{ entity_id: "l2", name: "Harbor", kind: "settlement", canon_status: "canon" }],
            next_cursor: null,
        },
    })
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CreateKnowledgePage", () => {
    function setup() {
        const server = installMockServer()
        server.on("GET", OPTIONS_PATH, { body: OPTIONS })
        mockSubjects(server)
        const rendered = renderAuthoringRoutes({
            initialEntry: "/app/c1/knowledge/new",
            routes: [
                { path: "/app/:campaignId/knowledge/new", element: <CreateKnowledgePage /> },
                { path: "/app/:campaignId/knowledge/:knowledgeItemId", element: <p>Knowledge detail page</p> },
                { path: "/app/:campaignId/knowledge", element: <p>Knowledge list page</p> },
            ],
        })
        return { server, ...rendered }
    }

    it("offers the server's choices and says it writes the claim only", async () => {
        setup()
        const type = await screen.findByRole("combobox", { name: /Type/ })
        expect(within(type).getAllByRole("option").map((o) => o.textContent)).toEqual([
            "Choose a type",
            "Secret",
            "Rumor",
        ])
        expect(screen.getByText(/who knows it is recorded separately/)).toBeInTheDocument()
    })

    it("requires a statement, type, truth, and sensitivity before sending anything", async () => {
        const { server } = setup()
        await screen.findByRole("combobox", { name: /Type/ })
        fireEvent.click(screen.getByRole("button", { name: "Create claim" }))
        const summary = await screen.findByRole("alert")
        for (const message of [
            "Statement is required.",
            "Choose a type.",
            "Choose whether the claim is true.",
            "Choose a sensitivity.",
        ]) {
            expect(summary).toHaveTextContent(message)
        }
        expect(server.callsTo("POST", CREATE_PATH)).toHaveLength(0)
    })

    it("creates a draft and replaces history with the claim detail", async () => {
        const { server, router } = setup()
        server.on("POST", CREATE_PATH, { status: 201, body: { ...VIEW, changed: true } })
        await screen.findByRole("combobox", { name: /Type/ })
        fireEvent.change(screen.getByRole("textbox", { name: /Statement/ }), {
            target: { value: " The duke is a vampire. " },
        })
        fireEvent.change(screen.getByRole("combobox", { name: /Type/ }), { target: { value: "rumor" } })
        fireEvent.change(screen.getByRole("combobox", { name: /Truth/ }), { target: { value: "false" } })
        fireEvent.change(screen.getByRole("combobox", { name: /Sensitivity/ }), {
            target: { value: "public" },
        })
        fireEvent.focus(screen.getByRole("combobox", { name: "Subject" }))
        fireEvent.click(await screen.findByRole("option", { name: /Harbor/ }))
        fireEvent.click(screen.getByRole("button", { name: "Create claim" }))

        await screen.findByText("Knowledge detail page")
        const [call] = server.callsTo("POST", CREATE_PATH)
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.body).toEqual({
            statement: "The duke is a vampire.",
            knowledge_type: "rumor",
            truth_status: "false",
            sensitivity: "public",
            subject_entity_id: "l2",
        })
        expect(router.state.historyAction).toBe("REPLACE")
        expect(router.state.location.pathname).toBe("/app/c1/knowledge/k1")
    })

    it("maps a refused subject onto its field and keeps the input", async () => {
        const { server } = setup()
        server.on("POST", CREATE_PATH, {
            status: 400,
            body: { error: { code: "knowledge_subject_invalid", message: "m", correlation_id: "c" } },
        })
        await screen.findByRole("combobox", { name: /Type/ })
        fireEvent.change(screen.getByRole("textbox", { name: /Statement/ }), { target: { value: "A claim." } })
        fireEvent.change(screen.getByRole("combobox", { name: /Type/ }), { target: { value: "secret" } })
        fireEvent.change(screen.getByRole("combobox", { name: /Truth/ }), { target: { value: "true" } })
        fireEvent.change(screen.getByRole("combobox", { name: /Sensitivity/ }), {
            target: { value: "secret" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Create claim" }))
        await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("subject is not valid"))
        expect(screen.getByRole("textbox", { name: /Statement/ })).toHaveValue("A claim.")
    })

    it("explains a refused options read", async () => {
        const server = installMockServer()
        server.on("GET", OPTIONS_PATH, { status: 403 })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/knowledge/new",
            routes: [{ path: "/app/:campaignId/knowledge/new", element: <CreateKnowledgePage /> }],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent("do not have permission")
    })
})

describe("EditKnowledgePage", () => {
    function setup(initial: object = VIEW) {
        const server = installMockServer()
        let current: object = initial
        server.on("GET", VIEW_PATH, () => ({ body: current }))
        server.on("GET", OPTIONS_PATH, { body: OPTIONS })
        mockSubjects(server)
        const rendered = renderAuthoringRoutes({
            initialEntry: "/app/c1/knowledge/k1/edit",
            routes: [
                { path: "/app/:campaignId/knowledge/:knowledgeItemId/edit", element: <EditKnowledgePage /> },
                { path: "/app/:campaignId/knowledge/:knowledgeItemId", element: <p>Knowledge detail page</p> },
            ],
        })
        return { server, setCurrent: (next: object) => (current = next), ...rendered }
    }

    it("pre-fills the claim", async () => {
        setup()
        await screen.findByRole("textbox", { name: /Statement/ })
        expect(screen.getByRole("textbox", { name: /Statement/ })).toHaveValue("The duke is a vampire.")
        expect(screen.getByRole("combobox", { name: /Type/ })).toHaveValue("secret")
        expect(screen.getByRole("combobox", { name: /Truth/ })).toHaveValue("true")
        expect(screen.getByRole("combobox", { name: "Subject" })).toHaveValue("Keep")
    })

    it("saves against the loaded version", async () => {
        const { server } = setup()
        server.on("POST", UPDATE_PATH, { body: { ...VIEW, row_version: 4 } })
        await screen.findByRole("textbox", { name: /Statement/ })
        fireEvent.change(screen.getByRole("combobox", { name: /Truth/ }), { target: { value: "false" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        await screen.findByText("Knowledge detail page")
        expect(server.callsTo("POST", UPDATE_PATH)[0]!.body).toEqual({
            expected_row_version: 3,
            statement: "The duke is a vampire.",
            knowledge_type: "secret",
            truth_status: "false",
            sensitivity: "secret",
            subject_entity_id: "l1",
            change_note: null,
        })
    })

    it("freezes statement, type, and subject once someone knows the claim", async () => {
        setup({ ...VIEW, in_use: true, field_locks: ["statement", "knowledge_type", "subject"] })
        await screen.findByRole("textbox", { name: /Statement/ })
        expect(screen.getByRole("textbox", { name: /Statement/ })).toBeDisabled()
        expect(screen.getByRole("combobox", { name: /Type/ })).toBeDisabled()
        expect(screen.getByRole("combobox", { name: "Subject" })).toBeDisabled()
        expect(screen.getByRole("combobox", { name: /Truth/ })).toBeEnabled()
        expect(screen.getByRole("combobox", { name: /Sensitivity/ })).toBeEnabled()
    })

    it("keeps the user's values across a stale write", async () => {
        const { server, setCurrent } = setup()
        server.on("POST", UPDATE_PATH, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        await screen.findByRole("textbox", { name: /Statement/ })
        fireEvent.change(screen.getByRole("textbox", { name: /Statement/ }), { target: { value: "Mine" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("Someone else changed this record")
        setCurrent({ ...VIEW, statement: "Theirs", row_version: 6 })
        fireEvent.click(screen.getByRole("button", { name: "Load latest version" }))
        await waitFor(() =>
            expect(screen.getByRole("textbox", { name: /Statement/ })).toHaveValue("Theirs"),
        )
        expect(screen.getByRole("region", { name: "Your unsaved changes" })).toHaveTextContent("Mine")
    })

    it("shows the non-disclosing state for a missing claim", async () => {
        const server = installMockServer()
        server.on("GET", VIEW_PATH, { status: 404 })
        server.on("GET", OPTIONS_PATH, { body: OPTIONS })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/knowledge/k1/edit",
            routes: [
                { path: "/app/:campaignId/knowledge/:knowledgeItemId/edit", element: <EditKnowledgePage /> },
            ],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent(
            "This knowledge claim does not exist, or you do not have access to it.",
        )
    })
})
