import {
    act,
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    Link,
    MemoryRouter,
    Route,
    Routes,
    useLocation,
    useNavigate,
} from "react-router"
import {
    afterEach,
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { useWorldBackPath } from "../hooks/useWorldBackPath"
import { useWorldEntities } from "../hooks/useWorldEntities"
import type { WorldEntityPage } from "../types/world"
import { CampaignWorldPage } from "./CampaignWorldPage"

vi.mock("../hooks/useWorldEntities", () => ({
    useWorldEntities: vi.fn(),
}))

const useWorldEntitiesMock = vi.mocked(useWorldEntities)

const worldPage: WorldEntityPage = {
    items: [
        {
            entity_id: "location-1",
            category: "location",
            entity_type_code: "city",
            name: "Glass Harbor",
            summary: "A harbor surrounded by ancient glass towers.",
        },
    ],
    next_cursor: "next-cursor",
}

const path = "/app/campaign-a/world"

beforeEach(() => {
    vi.useFakeTimers()
    useWorldEntitiesMock.mockReset()
    useWorldEntitiesMock.mockReturnValue({
        state: { status: "success", page: worldPage },
        retry: vi.fn(),
    })
})

afterEach(() => {
    vi.useRealTimers()
})

function LocationProbe() {
    const location = useLocation()
    const navigate = useNavigate()
    return (
        <>
            <p data-testid="location">{location.pathname + location.search}</p>
            <button type="button" onClick={() => void navigate(-1)}>
                Browser back
            </button>
            <button type="button" onClick={() => void navigate(1)}>
                Browser forward
            </button>
        </>
    )
}

function EntryStub() {
    const back = useWorldBackPath("campaign-a")
    return <Link to={back}>Back to World</Link>
}

function renderAt(initial: string) {
    return render(
        <MemoryRouter initialEntries={[initial]}>
            <LocationProbe />
            <Routes>
                <Route path="/app/:campaignId/world" element={<CampaignWorldPage />} />
                <Route path="/app/:campaignId/world/:category/:entityId" element={<EntryStub />} />
            </Routes>
        </MemoryRouter>,
    )
}

const here = () => screen.getByTestId("location").textContent

function typeInSearch(value: string) {
    fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), {
        target: { value },
    })
    act(() => {
        vi.advanceTimersByTime(180)
    })
}

function chooseCategory(name: string) {
    fireEvent.click(screen.getByRole("link", { name }))
}

describe("CampaignWorldPage browsing state in the address", () => {
    it("starts on All entries for a missing or unknown category", () => {
        renderAt(`${path}?category=relationship`)

        expect(useWorldEntitiesMock).toHaveBeenLastCalledWith("campaign-a", null, "", null, false)
        expect(screen.getByRole("link", { name: "All entries" })).toHaveAttribute(
            "aria-current",
            "page",
        )
    })

    it("opens a deep link with category, search and page already applied", () => {
        renderAt(`${path}?category=event&q=sundering&cursor=c1`)

        expect(useWorldEntitiesMock).toHaveBeenLastCalledWith(
            "campaign-a",
            "event",
            "sundering",
            "c1",
            false,
        )
        expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("sundering")
        expect(screen.getByRole("link", { name: "Events" })).toHaveAttribute("aria-current", "page")
        expect(screen.getByText("Page 2")).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Previous page" })).toBeEnabled()
    })

    it("combines search and category; a category change keeps the search but restarts paging", () => {
        renderAt(path)

        typeInSearch("harbor")
        fireEvent.click(screen.getByRole("button", { name: "Next page" }))
        expect(here()).toBe(`${path}?q=harbor&cursor=next-cursor`)

        chooseCategory("Locations")

        expect(here()).toBe(`${path}?category=location&q=harbor`)
        expect(useWorldEntitiesMock).toHaveBeenLastCalledWith(
            "campaign-a",
            "location",
            "harbor",
            null,
            false,
        )
    })

    it("a new search keeps the category and restarts paging", () => {
        renderAt(`${path}?category=item&cursor=c1&cursor=c2`)

        typeInSearch("sword")

        expect(here()).toBe(`${path}?category=item&q=sword`)
    })

    it("pages forward and back through the trail without leaving a stale cursor", () => {
        renderAt(`${path}?category=item&q=a`)

        expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled()

        fireEvent.click(screen.getByRole("button", { name: "Next page" }))
        expect(here()).toBe(`${path}?category=item&q=a&cursor=next-cursor`)

        fireEvent.click(screen.getByRole("button", { name: "Previous page" }))
        expect(here()).toBe(`${path}?category=item&q=a`)
        expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled()
    })

    it("disables Next page on the last page", () => {
        useWorldEntitiesMock.mockReturnValue({
            state: { status: "success", page: { ...worldPage, next_cursor: null } },
            retry: vi.fn(),
        })

        renderAt(`${path}?cursor=c1`)

        expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled()
        expect(screen.getByRole("button", { name: "Previous page" })).toBeEnabled()
    })

    it("returns from an opened entry to the same category, search and page", () => {
        renderAt(`${path}?category=location&q=glass&cursor=c1`)

        fireEvent.click(screen.getByRole("link", { name: /Glass Harbor/ }))
        expect(here()).toBe(`${path}/location/location-1`)

        fireEvent.click(screen.getByRole("link", { name: "Back to World" }))

        expect(here()).toBe(`${path}?category=location&q=glass&cursor=c1`)
        expect(useWorldEntitiesMock).toHaveBeenLastCalledWith(
            "campaign-a",
            "location",
            "glass",
            "c1",
            false,
        )
        expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("glass")
    })

    it("follows browser Back and Forward across category and page changes", () => {
        renderAt(path)

        chooseCategory("Events")
        fireEvent.click(screen.getByRole("button", { name: "Next page" }))
        expect(here()).toBe(`${path}?category=event&cursor=next-cursor`)

        fireEvent.click(screen.getByRole("button", { name: "Browser back" }))
        expect(here()).toBe(`${path}?category=event`)
        expect(useWorldEntitiesMock).toHaveBeenLastCalledWith("campaign-a", "event", "", null, false)

        fireEvent.click(screen.getByRole("button", { name: "Browser back" }))
        expect(here()).toBe(path)
        expect(screen.getByRole("link", { name: "All entries" })).toHaveAttribute(
            "aria-current",
            "page",
        )

        fireEvent.click(screen.getByRole("button", { name: "Browser forward" }))
        expect(screen.getByRole("link", { name: "Events" })).toHaveAttribute("aria-current", "page")
    })

    it("puts the search field back in step with the address on Back", () => {
        renderAt(`${path}?q=old`)

        chooseCategory("Items")
        fireEvent.click(screen.getByRole("button", { name: "Browser back" }))

        expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("old")
    })

    it("clears an empty search without losing the selected category", () => {
        useWorldEntitiesMock.mockReturnValue({
            state: { status: "success", page: { items: [], next_cursor: null } },
            retry: vi.fn(),
        })

        renderAt(`${path}?category=event&q=zzz`)

        expect(screen.getByText("No events match “zzz”.")).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Clear search" }))

        expect(here()).toBe(`${path}?category=event`)
        expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("")
        expect(screen.getByRole("link", { name: "Events" })).toHaveAttribute("aria-current", "page")
    })

    it("ignores the draft-preview address flag and shows no authoring controls without the capability", () => {
        renderAt(`${path}?hidden=1`)

        expect(useWorldEntitiesMock).toHaveBeenLastCalledWith("campaign-a", null, "", null, false)
        expect(screen.queryByLabelText(/Show drafts and archived/)).not.toBeInTheDocument()
        expect(
            screen.queryByRole("navigation", { name: "Create world content" }),
        ).not.toBeInTheDocument()
    })
})
