import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { Link } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { MockResponse } from "../test/authoringHarness"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { ItemDefinitionFormPage } from "./ItemDefinitionPages"

// B1-2: saving an existing item definition keeps the form mounted, shows a visible saved status,
// announces once, and keeps every other outcome distinct. The write is never repeated by a read.

const BASE = "/campaigns/c1/authoring/item-definitions"

const OPTIONS = {
    categories: [
        { value: "weapon", label: "Weapon" },
        { value: "potion", label: "Potion" },
    ],
    rarities: [{ value: "common", label: "Common" }, { value: "rare", label: "Rare" }],
    canon_states: [{ value: "draft", label: "Draft" }, { value: "canon", label: "Canon" }],
    limits: { name_max_length: 200, description_max_length: 4000 },
}

function definition(overrides: object = {}) {
    return {
        item_definition_id: "d1",
        code: "moonblade",
        name: "Moonblade",
        category: "weapon",
        category_label: "Weapon",
        description: "Glows",
        rarity: "rare",
        requires_attunement: true,
        weight: 3,
        base_cost_gp: 1200.5,
        canon_status: "draft",
        row_version: 2,
        is_homebrew: true,
        can_edit: true,
        ...overrides,
    }
}

const err = (status: number, code = "x"): MockResponse => ({
    status,
    body: { error: { code, message: "m", correlation_id: "c" } },
})

afterEach(() => {
    vi.unstubAllGlobals()
})

// A server whose definition is whatever `state.current` holds; a save moves it forward.
function setup(options: { post?: (n: number) => MockResponse | Promise<MockResponse> } = {}) {
    const server = installMockServer()
    const state = {
        current: definition() as Record<string, unknown>,
        get: undefined as MockResponse | undefined,
        posts: 0,
    }
    server.on("GET", `${BASE}/options`, { body: OPTIONS })
    server.on("GET", `${BASE}/d1`, () => state.get ?? { body: state.current })
    server.on("GET", `${BASE}/d2`, { body: definition({ item_definition_id: "d2", name: "Sunblade" }) })
    server.on("POST", `${BASE}/d1/update`, async (call) => {
        state.posts += 1
        const answer = options.post?.(state.posts)
        const resolved = answer === undefined ? undefined : await answer
        if (resolved !== undefined) return resolved
        const body = call.body as Record<string, unknown>
        state.current = {
            ...state.current,
            ...body,
            description: body.description,
            requires_attunement: body.requires_attunement,
            canon_status: body.canon_status,
            row_version: (state.current.row_version as number) + 1,
        }
        return { body: state.current }
    })
    server.on("POST", `${BASE}/d2/update`, { body: definition({ item_definition_id: "d2", row_version: 3 }) })
    renderAuthoringRoutes({
        initialEntry: "/app/c1/item-definitions/d1",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] }],
        }),
        routes: [
            {
                path: "/app/:campaignId/item-definitions/:definitionId",
                element: (
                    <>
                        <Link to="/app/c1/item-definitions/d2">Go to Sunblade</Link>
                        <ItemDefinitionFormPage />
                    </>
                ),
            },
        ],
    })
    return { server, state }
}

// Every announcement the shared live region makes, in order.
function watchAnnouncements(): string[] {
    const spoken: string[] = []
    const region = screen.getByTestId("authoring-announcer")
    new MutationObserver(() => {
        const text = region.textContent?.trim() ?? ""
        if (text !== "") spoken.push(text)
    }).observe(region, { childList: true, subtree: true, characterData: true })
    return spoken
}

const updates = (server: ReturnType<typeof setup>["server"]) => server.callsTo("POST", `${BASE}/d1/update`)
const formEl = () => screen.getByRole("form", { name: "Item definition" })
const field = (name: RegExp) => within(formEl()).getByRole("textbox", { name })
const saveButton = () => within(formEl()).getByRole("button", { name: "Save item definition" })
const save = () => fireEvent.click(saveButton())
const SAVED = "Item definition saved."

async function open() {
    await screen.findByRole("form", { name: "Item definition" })
}

describe("item definition save: success", () => {
    it("shows a persistent saved status, announces once, keeps the same inputs and moves the version on", async () => {
        const { server } = setup()
        await open()
        const spoken = watchAnnouncements()
        const nameInput = field(/Name/)
        const form = formEl()
        nameInput.focus()
        fireEvent.change(nameInput, { target: { value: "Moonblade II" } })
        save()
        const notice = await screen.findByText(SAVED)
        expect(notice.closest("[aria-live], [role=status], [role=alert]")).toBeNull()
        await waitFor(() => expect(spoken.filter((s) => s === "Item definition saved")).toHaveLength(1))
        // The same DOM nodes: nothing was remounted, so focus and scroll are untouched.
        expect(formEl()).toBe(form)
        expect(field(/Name/)).toBe(nameInput)
        expect(nameInput).toHaveValue("Moonblade II")
        expect(nameInput).toHaveFocus()
        expect(updates(server)).toHaveLength(1)
        expect(updates(server)[0]!.body).toMatchObject({ expected_row_version: 2, name: "Moonblade II" })

        // The next save is against the version just read.
        fireEvent.change(nameInput, { target: { value: "Moonblade III" } })
        expect(screen.queryByText(SAVED)).toBeNull()
        save()
        await waitFor(() => expect(updates(server)).toHaveLength(2))
        expect(updates(server)[1]!.body).toMatchObject({ expected_row_version: 3, name: "Moonblade III" })
        await screen.findByText(SAVED)
        expect(spoken.filter((s) => s === "Item definition saved")).toHaveLength(2)
    })

    it("keeps input typed while the save is pending, and says it is not saved yet", async () => {
        let release: (() => void) | undefined
        const gate = new Promise<void>((resolve) => {
            release = resolve
        })
        setup({ post: async () => { await gate; return undefined as unknown as MockResponse } })
        await open()
        fireEvent.change(field(/Name/), { target: { value: "Sent name" } })
        save()
        // Typed after the request left, before the answer.
        fireEvent.change(within(formEl()).getByRole("textbox", { name: /Description/ }), {
            target: { value: "Typed during the save" },
        })
        await act(async () => release?.())
        await screen.findByText(SAVED)
        expect(screen.getByText("Your newer changes are not saved yet.")).toBeInTheDocument()
        expect(within(formEl()).getByRole("textbox", { name: /Description/ })).toHaveValue("Typed during the save")
        expect(field(/Name/)).toHaveValue("Sent name")
    })
})

describe("item definition save: submission guards", () => {
    it("ignores a second click, Enter and form submit while pending, and keeps focus on Save", async () => {
        let release: (() => void) | undefined
        const gate = new Promise<void>((resolve) => {
            release = resolve
        })
        const { server } = setup({ post: async () => { await gate; return undefined as unknown as MockResponse } })
        await open()
        fireEvent.change(field(/Name/), { target: { value: "Once" } })
        saveButton().focus()
        save()
        await waitFor(() => expect(saveButton()).toHaveAttribute("aria-disabled", "true"))
        expect(saveButton()).not.toBeDisabled()
        expect(saveButton()).toHaveFocus()
        save()
        fireEvent.submit(formEl())
        fireEvent.keyDown(field(/Name/), { key: "Enter" })
        await act(async () => release?.())
        await screen.findByText(SAVED)
        expect(updates(server)).toHaveLength(1)
    })
})

describe("item definition save: confirmed write, failed read", () => {
    it("keeps the form, holds saving, reads without writing, then announces once", async () => {
        const { server, state } = setup()
        await open()
        const spoken = watchAnnouncements()
        const nameInput = field(/Name/)
        fireEvent.change(nameInput, { target: { value: "Moonblade II" } })
        state.get = err(500)
        save()
        expect(await screen.findByText(/Item definition saved\. The latest/)).toBeInTheDocument()
        expect(screen.getAllByText(/could not be loaded/)).toHaveLength(2)
        // The form and the person's values are still there; the read did not replace it with a terminal.
        expect(field(/Name/)).toBe(nameInput)
        expect(nameInput).toHaveValue("Moonblade II")
        expect(saveButton()).toHaveAttribute("aria-disabled", "true")
        expect(screen.getByText("Load the latest version before saving again.")).toBeInTheDocument()
        expect(spoken).not.toContain("Item definition saved")

        // Held: Save and Enter send nothing.
        save()
        fireEvent.submit(formEl())
        expect(updates(server)).toHaveLength(1)

        state.get = undefined
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        await waitFor(() => expect(spoken.filter((s) => s === "Item definition saved")).toHaveLength(1))
        await screen.findByText(SAVED)
        expect(screen.queryAllByText(/could not be loaded/)).toHaveLength(0)
        expect(saveButton()).toHaveAttribute("aria-disabled", "false")
        expect(updates(server)).toHaveLength(1)
        expect(field(/Name/)).toBe(nameInput)

        // A later save is its own episode against the new version.
        fireEvent.change(nameInput, { target: { value: "Moonblade III" } })
        save()
        await waitFor(() => expect(updates(server)).toHaveLength(2))
        expect(updates(server)[1]!.body).toMatchObject({ expected_row_version: 3 })
        await waitFor(() => expect(spoken.filter((s) => s === "Item definition saved")).toHaveLength(2))
    })

    it("removes the form when the read after a save is refused or the record is gone", async () => {
        for (const status of [403, 404]) {
            const { state } = setup()
            await open()
            fireEvent.change(field(/Name/), { target: { value: "Changed" } })
            state.get = err(status)
            save()
            await waitFor(() => expect(screen.queryByRole("form", { name: "Item definition" })).toBeNull())
            expect(screen.queryByDisplayValue("Changed")).toBeNull()
            vi.unstubAllGlobals()
            document.body.innerHTML = ""
        }
    })
})

describe("item definition save: other outcomes", () => {
    it("does not claim a save for an unknown outcome, and retries the same key, body and version", async () => {
        const { server } = setup({ post: (n) => (n === 1 ? { networkError: true } : (undefined as unknown as MockResponse)) })
        await open()
        const spoken = watchAnnouncements()
        fireEvent.change(field(/Name/), { target: { value: "Maybe saved" } })
        save()
        expect(await screen.findByText(/cannot tell whether this was saved/)).toBeInTheDocument()
        expect(screen.queryByText(SAVED)).toBeNull()
        expect(spoken).not.toContain("Item definition saved")
        fireEvent.click(screen.getByRole("button", { name: "Retry" }))
        await screen.findByText(SAVED)
        const [first, second] = updates(server)
        expect(second!.body).toEqual(first!.body)
        expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
        expect((second!.body as { expected_row_version: number }).expected_row_version).toBe(2)
    })

    it("keeps input on a client validation problem and sends nothing", async () => {
        const { server } = setup()
        await open()
        fireEvent.change(field(/Weight/), { target: { value: "heavy" } })
        fireEvent.change(field(/Name/), { target: { value: "Kept" } })
        save()
        expect(await screen.findByText(/Enter a number such as/)).toBeInTheDocument()
        expect(field(/Name/)).toHaveValue("Kept")
        expect(updates(server)).toHaveLength(0)
        expect(screen.queryByText(SAVED)).toBeNull()
    })

    it("keeps input on a server validation refusal and shows no saved status", async () => {
        const { server } = setup({ post: () => err(422, "validation_error") })
        await open()
        fireEvent.change(field(/Name/), { target: { value: "Rejected" } })
        save()
        expect(await screen.findByRole("alert")).toBeInTheDocument()
        expect(field(/Name/)).toHaveValue("Rejected")
        expect(screen.queryByText(SAVED)).toBeNull()
        expect(updates(server)).toHaveLength(1)
    })

    it("shows a denied save without a saved status", async () => {
        setup({ post: () => err(403, "forbidden") })
        await open()
        fireEvent.change(field(/Name/), { target: { value: "Nope" } })
        save()
        expect(await screen.findByText(/do not have permission|permission/i)).toBeInTheDocument()
        expect(screen.queryByText(SAVED)).toBeNull()
        expect(field(/Name/)).toHaveValue("Nope")
    })

    it("keeps the person's changes through a conflict and saves against the new version after loading", async () => {
        const { server, state } = setup({ post: () => err(409, "stale_write") })
        await open()
        fireEvent.change(field(/Name/), { target: { value: "My name" } })
        save()
        expect(await screen.findByText(/Someone else changed this record/)).toBeInTheDocument()
        expect(screen.getByText(/Your unsaved changes: Name/)).toBeInTheDocument()
        state.current = definition({ row_version: 3, description: "Edited by someone else" })
        fireEvent.click(screen.getByRole("button", { name: /Load latest/i }))
        await waitFor(() =>
            expect(within(formEl()).getByRole("textbox", { name: /Description/ })).toHaveValue("Edited by someone else"),
        )
        // The intended edit is still there and still unsaved; nothing was re-sent by loading.
        expect(field(/Name/)).toHaveValue("My name")
        expect(updates(server)).toHaveLength(1)
        expect(screen.queryByText(SAVED)).toBeNull()
    })
})

describe("item definition save: scope", () => {
    it("ignores a save on one definition once another is open", async () => {
        let release: (() => void) | undefined
        const gate = new Promise<void>((resolve) => {
            release = resolve
        })
        setup({ post: async () => { await gate; return undefined as unknown as MockResponse } })
        await open()
        const spoken = watchAnnouncements()
        fireEvent.change(field(/Name/), { target: { value: "Leaving" } })
        save()
        fireEvent.click(screen.getByRole("link", { name: "Go to Sunblade" }))
        await waitFor(() => expect(field(/Name/)).toHaveValue("Sunblade"))
        await act(async () => release?.())
        await new Promise((resolve) => setTimeout(resolve, 30))
        expect(screen.queryByText(SAVED)).toBeNull()
        expect(spoken).toEqual([])
        expect(field(/Name/)).toHaveValue("Sunblade")
        expect(saveButton()).toHaveAttribute("aria-disabled", "false")
    })
})
