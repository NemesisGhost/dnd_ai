import { act, fireEvent, render, screen } from "@testing-library/react"
import { useContext } from "react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { SessionBootstrapState } from "../hooks/useSessionBootstrap"
import { installMockServer } from "../test/authoringHarness"
import type { MockServer, MockResponse } from "../test/authoringHarness"
import type { SessionBootstrap } from "../types/bootstrap"
import { BreadcrumbLabelProvider } from "./BreadcrumbLabelProvider"
import { BreadcrumbLabelContext, useBreadcrumbLabel, useBreadcrumbLabelReader } from "./BreadcrumbLabelContext"

// Label ownership runs from the start of a read to the label: the read layer captures the authority
// generation (the registry in force) when a request STARTS, and only that generation can be published
// into. These tests drive the real read hook (useAuthoringResource) with deferred responses, through a
// page that stays mounted while the authority changes.

const ROUTE = "parties.detail"
const CAMPAIGN = "mundivita"
const CHARACTER = "character-ixamarra"

const bootstrap = (change: (b: SessionBootstrap) => void = () => undefined): SessionBootstrap => {
    const copy = structuredClone(sessionBootstrapFixture) as SessionBootstrap
    change(copy)
    return copy
}
const authenticated = (b: SessionBootstrap = bootstrap()): SessionBootstrapState => ({
    status: "authenticated",
    bootstrap: b,
})
// Two authorities that differ only in what the labels depend on.
const A = () => authenticated()
const B = () => authenticated(bootstrap((b) => void b.campaigns[0]!.capabilities.push("canon.edit")))

// Stable, as the real session functions are: a new function each render would restart the page's read.
const RELOAD = vi.fn()
const REFRESH = vi.fn()

interface Thing {
    name: string
}

// An adopted page's pattern: a real authoring read, whose answer and authority generation feed the label.
function Page({ id = "p1" }: { id?: string }) {
    const resource = useAuthoringResource<Thing>(`/things/${id}`)
    useBreadcrumbLabel({
        route: ROUTE,
        params: { campaignId: CAMPAIGN, partyId: id },
        name: resource.state.kind === "ready" ? resource.state.data.name : null,
        denied: resource.state.kind === "denied" || resource.state.kind === "unavailable",
        authority: resource.authority,
    })
    return (
        <button type="button" onClick={() => void resource.refetch()}>
            reload
        </button>
    )
}

function Reader({ id = "p1" }: { id?: string }) {
    const labelFor = useBreadcrumbLabelReader()
    return <p data-testid={`label-${id}`}>{labelFor(ROUTE, { campaignId: CAMPAIGN, partyId: id }) ?? "generic"}</p>
}

function Tree({
    state,
    characterId = CHARACTER,
    children,
}: {
    state: SessionBootstrapState
    characterId?: string | null
    children: ReactNode
}) {
    return (
        <SessionContext.Provider value={{ state, reload: RELOAD, refresh: REFRESH }}>
            <BreadcrumbLabelProvider campaignId={CAMPAIGN} characterId={characterId}>
                {children}
                <Reader />
            </BreadcrumbLabelProvider>
        </SessionContext.Provider>
    )
}

// Each GET of the record is parked until the test answers it, in the order the requests were made.
interface Parked {
    answer: (response: MockResponse) => Promise<void>
}
let server: MockServer
let reads: Parked[]

beforeEach(() => {
    server = installMockServer()
    reads = []
    server.on("GET", "/things/p1", () => {
        return new Promise<MockResponse>((resolve) => {
            reads.push({
                answer: async (response) => {
                    await act(async () => {
                        resolve(response)
                        await Promise.resolve()
                    })
                },
            })
        })
    })
})

afterEach(() => {
    vi.unstubAllGlobals()
})

const label = () => screen.getByTestId("label-p1").textContent
const named = (name: string): MockResponse => ({ body: { name } })
const NOT_FOUND: MockResponse = { status: 404, body: { error: { code: "not_found", message: "m", correlation_id: "c" } } }
const reload = () => fireEvent.click(screen.getByRole("button", { name: "reload" }))
const settle = () => act(async () => void (await new Promise((resolve) => setTimeout(resolve, 0))))

function mount(state: SessionBootstrapState = A()) {
    const view = render(
        <Tree state={state}>
            <Page />
        </Tree>,
    )
    // The same page instance stays mounted across authority changes.
    const change = (props: { state?: SessionBootstrapState; characterId?: string | null }) =>
        view.rerender(
            <Tree
                state={props.state ?? A()}
                characterId={props.characterId === undefined ? CHARACTER : props.characterId}
            >
                <Page />
            </Tree>,
        )
    return { ...view, change }
}

describe("a label belongs to the authority under which its read started", () => {
    it("1. an old read answered after the authority changed leaves the name absent", async () => {
        const { change } = mount(A())
        await settle()
        expect(reads).toHaveLength(1)
        change({ state: B() })
        await reads[0]!.answer(named("Old Name"))
        expect(label()).toBe("generic")
    })

    it("2. a new read started under the new authority publishes its authorized name on the page that stayed mounted", async () => {
        const { change } = mount(A())
        await settle()
        change({ state: B() })
        await reads[0]!.answer(named("Old Name"))
        expect(label()).toBe("generic")
        reload()
        await settle()
        expect(reads).toHaveLength(2)
        await reads[1]!.answer(named("New Name"))
        expect(label()).toBe("New Name")
    })

    it("3. a new answer arriving before the old one is not overwritten by it", async () => {
        const { change } = mount(A())
        await settle()
        change({ state: B() })
        reload()
        await settle()
        expect(reads).toHaveLength(2)
        await reads[1]!.answer(named("New Name"))
        expect(label()).toBe("New Name")
        await reads[0]!.answer(named("Old Name"))
        expect(label()).toBe("New Name")
    })

    it("3b. two reads under the same authority: the later start wins whatever order they answer in", async () => {
        mount(A())
        await settle()
        reload()
        await settle()
        await reads[1]!.answer(named("Later"))
        await reads[0]!.answer(named("Earlier"))
        expect(label()).toBe("Later")
    })

    it("4. A to B to A does not revive the first generation of A", async () => {
        const { change } = mount(A())
        await settle()
        change({ state: B() })
        change({ state: A() })
        await reads[0]!.answer(named("First A"))
        expect(label()).toBe("generic")
        // A read started in the new generation of A publishes.
        reload()
        await settle()
        await reads[1]!.answer(named("Second A"))
        expect(label()).toBe("Second A")
    })

    it("a perspective commit and a cleared selection are generations too", async () => {
        const { change } = mount(A())
        await settle()
        change({ characterId: "character-other" })
        await reads[0]!.answer(named("Old Name"))
        expect(label()).toBe("generic")
        reload()
        await settle()
        await reads[1]!.answer(named("Now"))
        expect(label()).toBe("Now")
        change({ characterId: null })
        expect(label()).toBe("generic")
    })

    it("a name already published is dropped when the authority changes, and the page's held data does not republish it", async () => {
        const { change } = mount(A())
        await settle()
        await reads[0]!.answer(named("Aldric's Band"))
        expect(label()).toBe("Aldric's Band")
        change({ state: B() })
        await settle()
        expect(label()).toBe("generic")
        expect(reads).toHaveLength(1)
    })
})

describe("session loss and record denial", () => {
    it.each<[string, SessionBootstrapState]>([
        ["loading", { status: "loading" }],
        ["unauthenticated", { status: "unauthenticated" }],
        ["error", { status: "error", error: new Error("down") }],
    ])("5. a read answered after the session became %s publishes nothing, and re-authentication does not restore it", async (_n, lost) => {
        const { change } = mount(A())
        await settle()
        change({ state: lost })
        await reads[0]!.answer(named("Late Name"))
        expect(label()).toBe("generic")
        change({ state: A() })
        expect(label()).toBe("generic")
    })

    it("5. a read started after session loss has no authority and publishes nothing", async () => {
        const { change } = mount(A())
        await settle()
        await reads[0]!.answer(named("Aldric's Band"))
        change({ state: { status: "loading" } })
        reload()
        await settle()
        await reads[1]!.answer(named("While Lost"))
        expect(label()).toBe("generic")
    })

    it("5. a refused record drops its name, and an older read answered later cannot restore it", async () => {
        mount(A())
        await settle()
        await reads[0]!.answer(named("Aldric's Band"))
        expect(label()).toBe("Aldric's Band")
        reload()
        await settle()
        reload()
        await settle()
        expect(reads).toHaveLength(3)
        await reads[2]!.answer(NOT_FOUND)
        expect(label()).toBe("generic")
        await reads[1]!.answer(named("Stale Name"))
        expect(label()).toBe("generic")
    })
})

describe("registrations", () => {
    it("6. an older registration going away does not remove a newer one", () => {
        function Direct({ name }: { name: string }) {
            const registry = useContext(BreadcrumbLabelContext)
            useBreadcrumbLabel({ route: ROUTE, params: { campaignId: CAMPAIGN, partyId: "p1" }, name, authority: registry })
            return null
        }
        const view = render(
            <Tree state={A()}>
                <Direct name="Older" />
            </Tree>,
        )
        expect(label()).toBe("Older")
        view.rerender(
            <Tree state={A()}>
                <Direct name="Older" />
                <section>
                    <Direct name="Newer" />
                </section>
            </Tree>,
        )
        expect(label()).toBe("Newer")
        // The older page goes away: the newer label stays.
        view.rerender(
            <Tree state={A()}>
                <section>
                    <Direct name="Newer" />
                </section>
            </Tree>,
        )
        expect(label()).toBe("Newer")
    })

    it("a page with no label registry in force registers nothing and the fallback is generic", async () => {
        render(
            <SessionContext.Provider value={{ state: A(), reload: RELOAD, refresh: REFRESH }}>
                <Page />
            </SessionContext.Provider>,
        )
        await settle()
        await reads[0]!.answer(named("Aldric's Band"))
        function Bare() {
            const labelFor = useBreadcrumbLabelReader()
            return <p data-testid="bare">{labelFor(ROUTE, { campaignId: CAMPAIGN, partyId: "p1" }) ?? "generic"}</p>
        }
        render(<Bare />)
        expect(screen.getByTestId("bare").textContent).toBe("generic")
    })
})
