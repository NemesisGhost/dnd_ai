import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { MockResponse, MockServer } from "../test/authoringHarness"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { ItemDefinitionFormPage, ItemDefinitionsPage } from "./ItemDefinitionPages"

// The definitions list and the category options back one page: each failed read has a recovery, the
// options are never shown as an empty successful catalog, and the closed answers keep their order.

const BASE = "/campaigns/c1/authoring/item-definitions"
const err = (status: number): MockResponse => ({
    status,
    body: { error: { code: "x", message: "m", correlation_id: "c" } },
})
const BROKEN = err(500)
const FORBIDDEN = err(403)
const MISSING = err(404)

const OPTIONS: MockResponse = {
    body: {
        categories: [
            { value: "weapon", label: "Weapon" },
            { value: "potion", label: "Potion" },
        ],
        rarities: [{ value: "common", label: "Common" }],
        canon_states: [{ value: "draft", label: "Draft" }],
        limits: { name_max_length: 200, description_max_length: 4000 },
    },
}
const LIST: MockResponse = {
    body: {
        items: [
            {
                item_definition_id: "d1",
                code: "moonblade",
                name: "Moonblade",
                category: "weapon",
                category_label: "Weapon",
                description: null,
                rarity: "rare",
                requires_attunement: false,
                weight: null,
                base_cost_gp: null,
                canon_status: "canon",
                row_version: 1,
                is_homebrew: true,
                can_edit: true,
            },
        ],
    },
}

let server: MockServer
let optionsAnswer: MockResponse
let listAnswer: MockResponse

beforeEach(() => {
    optionsAnswer = OPTIONS
    listAnswer = LIST
    server = installMockServer()
    server.on("GET", `${BASE}/options`, () => optionsAnswer)
    server.on("GET", BASE, () => listAnswer)
})

afterEach(() => {
    vi.unstubAllGlobals()
})

function open(entry = "/app/c1/item-definitions") {
    return renderAuthoringRoutes({
        initialEntry: entry,
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] }],
        }),
        routes: [
            { path: "/app/:campaignId/item-definitions", element: <ItemDefinitionsPage /> },
            { path: "/app/:campaignId/item-definitions/new", element: <ItemDefinitionFormPage /> },
        ],
    })
}

const reads = (path: string) => server.callsTo("GET", path).length
const nonGet = () => server.calls.filter((call) => call.method !== "GET")
const CATEGORY_FAILED = "The category filter could not be loaded."
const LIST_FAILED = "The list of item definitions could not be loaded."
const retry = () => screen.getByRole("button", { name: /Try again|Loading…/ })

describe("item definitions: list and category options", () => {
    it("recovers a failed list alone and reads only the list again", async () => {
        listAnswer = BROKEN
        open()
        await screen.findByText(LIST_FAILED)
        const [listReads, optionReads] = [reads(BASE), reads(`${BASE}/options`)]
        listAnswer = LIST
        fireEvent.click(retry())
        expect(await screen.findByText(/Moonblade \(Weapon/)).toBeInTheDocument()
        expect(screen.getByRole("combobox", { name: "Category" })).toBeInTheDocument()
        expect(reads(BASE)).toBe(listReads + 1)
        expect(reads(`${BASE}/options`)).toBe(optionReads)
        expect(nonGet()).toEqual([])
    })

    it("keeps a usable list and says the categories are missing, never an empty catalog", async () => {
        optionsAnswer = BROKEN
        open()
        expect(await screen.findByText(/Moonblade \(Weapon/)).toBeInTheDocument()
        expect(await screen.findByText(CATEGORY_FAILED)).toBeInTheDocument()
        expect(screen.queryByRole("combobox", { name: "Category" })).toBeNull()
        const [listReads, optionReads] = [reads(BASE), reads(`${BASE}/options`)]
        optionsAnswer = OPTIONS
        fireEvent.click(retry())
        const select = await screen.findByRole("combobox", { name: "Category" })
        expect(select).toHaveTextContent("Potion")
        expect(screen.queryByText(CATEGORY_FAILED)).toBeNull()
        expect(reads(BASE)).toBe(listReads)
        expect(reads(`${BASE}/options`)).toBe(optionReads + 1)
        expect(nonGet()).toEqual([])
    })

    it("recovers both reads failing together, through a partial recovery", async () => {
        listAnswer = BROKEN
        optionsAnswer = BROKEN
        open()
        await screen.findByText(LIST_FAILED)
        listAnswer = LIST
        fireEvent.click(retry())
        // The list is back, the options are not: the failure moves to the control that needs them.
        expect(await screen.findByText(CATEGORY_FAILED)).toBeInTheDocument()
        expect(screen.getByText(/Moonblade \(Weapon/)).toBeInTheDocument()
        optionsAnswer = OPTIONS
        fireEvent.click(retry())
        expect(await screen.findByRole("combobox", { name: "Category" })).toBeInTheDocument()
        expect(nonGet()).toEqual([])
    })

    it("retries only the reads that failed", async () => {
        listAnswer = BROKEN
        optionsAnswer = BROKEN
        open()
        await screen.findByText(LIST_FAILED)
        const [listReads, optionReads] = [reads(BASE), reads(`${BASE}/options`)]
        fireEvent.click(retry())
        await waitFor(() => expect(reads(BASE)).toBe(listReads + 1))
        expect(reads(`${BASE}/options`)).toBe(optionReads + 1)
    })

    it("does not offer a retry for refused or missing options", async () => {
        optionsAnswer = FORBIDDEN
        open()
        expect(await screen.findByText("You do not have access to the category filter.")).toBeInTheDocument()
        expect(screen.getByText(/Moonblade \(Weapon/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull()
        expect(screen.queryByRole("combobox", { name: "Category" })).toBeNull()
    })

    it("answers a 404 before a 403 before a failure when the list and options disagree", async () => {
        listAnswer = BROKEN
        optionsAnswer = MISSING
        open()
        expect(
            await screen.findByText("The list of item definitions is not available, or you can no longer access it."),
        ).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull()
    })

    it("hands focus to the heading after a used retry replaces the button", async () => {
        listAnswer = BROKEN
        open()
        await screen.findByText(LIST_FAILED)
        listAnswer = LIST
        retry().focus()
        fireEvent.click(retry())
        await screen.findByText(/Moonblade \(Weapon/)
        await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Item definitions" })).toHaveFocus())
    })
})

describe("item definition form: options and the definition", () => {
    it("recovers a failed options read on the new-definition form", async () => {
        optionsAnswer = BROKEN
        open("/app/c1/item-definitions/new")
        await screen.findByText("The form could not be loaded.")
        optionsAnswer = OPTIONS
        fireEvent.click(retry())
        expect(await screen.findByRole("form", { name: "Item definition" })).toBeInTheDocument()
        expect(screen.getByRole("combobox", { name: /Category/ })).toHaveTextContent("Weapon")
        expect(nonGet()).toEqual([])
    })
})
