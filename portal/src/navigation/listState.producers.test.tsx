import { act, fireEvent, render, screen } from "@testing-library/react"
import { RouterProvider, createMemoryRouter, useLocation } from "react-router"
import { describe, expect, it } from "vitest"
import { useCharactersBrowseState } from "../hooks/useCharactersBrowseState"
import { useWorldBrowseState } from "../hooks/useWorldBrowseState"
import { adaptLegacyReturn } from "./legacyReturn"
import { MAX_LIST_SEARCH, isValidListSearch } from "./listState"
import { resolveTask } from "./resolveTask"
import { matchRouteMeta } from "./routeMeta"

// The cursor trail is the page trail: the list API pages forward only, so each next-page action appends
// one cursor to the address and Previous drops the last. These tests drive the real browse-state hooks
// (the producers) and feed what they produce through the task and legacy validators and back into the
// hooks (the consumers), rather than testing constants alone.

const CAMPAIGN = "c1"
const UUID = "0f8fad5b-d9cb-469f-a165-0c0b0d6c1b3e"

// A backend-shaped cursor: URL-safe base64 of a JSON keyset envelope, padded, of exactly `length` characters.
function cursorOf(index: number, length: number): string {
    const head = `n${index}-`
    const body = "AbCd_-0123456789".repeat(Math.ceil(length / 16))
    const raw = (head + body).slice(0, length - 2)
    return `${raw}==`
}

function CharactersProbe({ cursors }: { cursors: readonly string[] }) {
    const state = useCharactersBrowseState()
    const location = useLocation()
    return (
        <div>
            <button type="button" onClick={() => state.goToNextPage(cursors[state.cursors.length]!)}>
                next
            </button>
            <button type="button" onClick={state.goToPreviousPage}>
                previous
            </button>
            <output data-testid="page">{state.pageNumber}</output>
            <output data-testid="cursor">{state.cursor ?? ""}</output>
            <output data-testid="returnTo">{state.returnTo}</output>
            <output data-testid="search">{location.search}</output>
        </div>
    )
}

function WorldProbe({ cursors }: { cursors: readonly string[] }) {
    const state = useWorldBrowseState()
    return (
        <div>
            <button type="button" onClick={() => state.goToNextPage(cursors[state.cursors.length]!)}>
                next
            </button>
            <button type="button" onClick={state.goToPreviousPage}>
                previous
            </button>
            <output data-testid="page">{state.pageNumber}</output>
            <output data-testid="cursor">{state.cursor ?? ""}</output>
            <output data-testid="returnSearch">{state.returnSearch}</output>
        </div>
    )
}

function mount(entry: string, element: React.ReactNode, path: string) {
    const router = createMemoryRouter([{ path, element }], { initialEntries: [entry] })
    const view = render(<RouterProvider router={router} />)
    return { router, ...view }
}

const nextTimes = async (count: number) => {
    for (let index = 0; index < count; index++) {
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "next" }))
        })
    }
}
const text = (id: string) => screen.getByTestId(id).textContent ?? ""

describe("a long backend-valid cursor survives producer, validation and return", () => {
    const long = cursorOf(0, 2048)

    it("Characters: one 2048-character cursor is accepted unchanged through the legacy adapter and back into the browser", async () => {
        expect(long).toHaveLength(2048)
        const first = mount(`/app/${CAMPAIGN}/characters/all`, <CharactersProbe cursors={[long]} />, "/app/:c/characters/all")
        await nextTimes(1)
        const returnTo = text("returnTo")
        expect(new URLSearchParams(text("search")).getAll("cursor")).toEqual([long])
        first.unmount()

        const adapted = adaptLegacyReturn(matchRouteMeta(`/app/${CAMPAIGN}/characters/${UUID}`)!, { charactersReturn: returnTo })
        expect(adapted?.task?.list).toEqual({ route: "characters.browse", search: returnTo.slice(returnTo.indexOf("?")) })
        expect(new URLSearchParams(adapted!.task!.list!.search).get("cursor")).toBe(long)

        const restored = mount(`/app/${CAMPAIGN}/characters/all${adapted!.task!.list!.search}`, <CharactersProbe cursors={[]} />, "/app/:c/characters/all")
        expect(text("page")).toBe("2")
        expect(text("cursor")).toBe(long)
        restored.unmount()
    })

    it("World: the same, through worldSearch", async () => {
        const first = mount(`/app/${CAMPAIGN}/world`, <WorldProbe cursors={[long]} />, "/app/:c/world")
        await nextTimes(1)
        const returnSearch = text("returnSearch")
        first.unmount()
        const adapted = adaptLegacyReturn(matchRouteMeta(`/app/${CAMPAIGN}/world/location/e1`)!, { worldSearch: returnSearch })
        expect(adapted?.task?.list).toEqual({ route: "campaign.world", search: returnSearch })
        const restored = mount(`/app/${CAMPAIGN}/world${returnSearch}`, <WorldProbe cursors={[]} />, "/app/:c/world")
        expect(text("cursor")).toBe(long)
        restored.unmount()
    })

    it("accepts 2048 and rejects 2049 and an empty or foreign-alphabet cursor", () => {
        for (const route of ["characters.browse", "campaign.world"]) {
            expect(isValidListSearch(route, `?cursor=${encodeURIComponent(cursorOf(1, 2048))}`), route).toBe(true)
            expect(isValidListSearch(route, `?cursor=${encodeURIComponent(cursorOf(1, 2049))}`), route).toBe(false)
            expect(isValidListSearch(route, "?cursor="), route).toBe(false)
            expect(isValidListSearch(route, "?cursor=a%20b"), route).toBe(false)
        }
    })

    it("a task descriptor from history carries the same search and resolves as state, unchanged", async () => {
        const first = mount(`/app/${CAMPAIGN}/characters/all`, <CharactersProbe cursors={[long]} />, "/app/:c/characters/all")
        await nextTimes(1)
        const search = text("search")
        first.unmount()
        const task = { v: 1, root: "characters", scope: { campaignId: CAMPAIGN }, trail: [], list: { route: "characters.browse", search } }
        const resolved = resolveTask(`/app/${CAMPAIGN}/characters/${UUID}`, { task })
        expect(resolved?.source).toBe("state")
        expect(resolved?.task.list?.search).toBe(search)
    })
})

describe("a page trail longer than 20 stays usable and returns to the same position", () => {
    const PAGES = 30
    const cursors = Array.from({ length: PAGES }, (_, index) => cursorOf(index, 1700))

    it("Characters: 30 next-page actions of 1700-character cursors, then the return, then Previous", async () => {
        const first = mount(`/app/${CAMPAIGN}/characters/all`, <CharactersProbe cursors={cursors} />, "/app/:c/characters/all")
        await nextTimes(PAGES)
        expect(text("page")).toBe(String(PAGES + 1))
        const returnTo = text("returnTo")
        first.unmount()

        const adapted = adaptLegacyReturn(matchRouteMeta(`/app/${CAMPAIGN}/characters/${UUID}`)!, { charactersReturn: returnTo })
        const search = adapted?.task?.list?.search
        expect(search).toBeDefined()
        expect(new URLSearchParams(search).getAll("cursor")).toEqual(cursors)
        const resolved = resolveTask(`/app/${CAMPAIGN}/characters/${UUID}`, { charactersReturn: returnTo })
        expect(resolved?.source).toBe("legacy")
        expect(resolved?.task.list?.search).toBe(search)

        const restored = mount(`/app/${CAMPAIGN}/characters/all${search}`, <CharactersProbe cursors={[]} />, "/app/:c/characters/all")
        expect(text("page")).toBe(String(PAGES + 1))
        expect(text("cursor")).toBe(cursors[PAGES - 1])
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "previous" }))
        })
        expect(text("page")).toBe(String(PAGES))
        expect(text("cursor")).toBe(cursors[PAGES - 2])
        restored.unmount()
    })

    it("World: the same through worldSearch", async () => {
        const first = mount(`/app/${CAMPAIGN}/world`, <WorldProbe cursors={cursors} />, "/app/:c/world")
        await nextTimes(PAGES)
        const returnSearch = text("returnSearch")
        first.unmount()
        const adapted = adaptLegacyReturn(matchRouteMeta(`/app/${CAMPAIGN}/world/location/e1`)!, { worldSearch: returnSearch })
        expect(adapted?.task?.list?.search).toBe(returnSearch)
        const restored = mount(`/app/${CAMPAIGN}/world${returnSearch}`, <WorldProbe cursors={[]} />, "/app/:c/world")
        expect(text("page")).toBe(String(PAGES + 1))
        expect(text("cursor")).toBe(cursors[PAGES - 1])
        restored.unmount()
    })
})

describe("combined bounds", () => {
    const encode = (value: string) => `cursor=${encodeURIComponent(value)}`

    it("accepts a trail of maximum-length cursors well past anything reachable", () => {
        const search = `?type=npc&q=${"q".repeat(200)}&hidden=1&${Array.from({ length: 150 }, (_, i) => encode(cursorOf(i, 2048))).join("&")}`
        expect(search.length).toBeGreaterThan(300_000)
        expect(search.length).toBeLessThan(MAX_LIST_SEARCH)
        expect(isValidListSearch("characters.browse", search)).toBe(true)
    })

    it("rejects, rather than truncates, a query over the total resource bound", () => {
        const search = `?${Array.from({ length: 300 }, (_, i) => encode(cursorOf(i, 2048))).join("&")}`
        expect(search.length).toBeGreaterThan(MAX_LIST_SEARCH)
        expect(isValidListSearch("characters.browse", search)).toBe(false)
    })
})

describe("endpoint-aligned name bounds", () => {
    it("Review type: 60 characters is accepted, 61 rejected (api/review_queue.py max_length=60)", () => {
        expect(isValidListSearch("review.queue", `?type=${"t".repeat(60)}`)).toBe(true)
        expect(isValidListSearch("review.queue", `?type=${"t".repeat(61)}`)).toBe(false)
        expect(isValidListSearch("review.queue", `?status=approved&type=${"t".repeat(60)}`)).toBe(true)
    })

    it("Item definition category: 100 accepted, 101 rejected (item_definition_authoring.py max_length=100)", () => {
        expect(isValidListSearch("itemDefinitions.list", `?category=${"c".repeat(100)}`)).toBe(true)
        expect(isValidListSearch("itemDefinitions.list", `?category=${"c".repeat(101)}`)).toBe(false)
    })
})
