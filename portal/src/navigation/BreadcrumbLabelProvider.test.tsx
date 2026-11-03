import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { SessionBootstrapState } from "../hooks/useSessionBootstrap"
import type { SessionBootstrap } from "../types/bootstrap"
import { BreadcrumbLabelProvider } from "./BreadcrumbLabelProvider"
import { useBreadcrumbLabel, useBreadcrumbLabelReader } from "./BreadcrumbLabelContext"

const PARAMS = { campaignId: "mundivita", partyId: "p1" }
const ROUTE = "parties.detail"
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

function Registrant({ name, denied = false }: { name: string | null; denied?: boolean }) {
    useBreadcrumbLabel({ route: ROUTE, params: PARAMS, name, denied })
    return null
}

function Reader() {
    const labelFor = useBreadcrumbLabelReader()
    return <p data-testid="label">{labelFor(ROUTE, PARAMS) ?? "generic"}</p>
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
        <SessionContext.Provider value={{ state, reload: vi.fn(), refresh: vi.fn() }}>
            <BreadcrumbLabelProvider campaignId="mundivita" characterId={characterId}>
                {children}
            </BreadcrumbLabelProvider>
        </SessionContext.Provider>
    )
}

const label = () => screen.getByTestId("label").textContent

interface Update {
    state?: SessionBootstrapState
    characterId?: string | null
    name?: string | null
    denied?: boolean
}

// One registrant page and one reader, rendered under the provider. `update` re-renders the SAME tree
// positions with new props, so the registrant stays mounted across an authority change, as a page does.
function setup(initialName: string | null = "Lantern Company") {
    const page = (name: string | null, denied = false) => (
        <>
            <Registrant name={name} denied={denied} />
            <Reader />
        </>
    )
    const view = render(<Tree state={authenticated()}>{page(initialName)}</Tree>)
    const update = (props: Update) =>
        view.rerender(
            <Tree
                state={props.state ?? authenticated()}
                characterId={props.characterId === undefined ? CHARACTER : props.characterId}
            >
                {page(props.name === undefined ? initialName : props.name, props.denied)}
            </Tree>,
        )
    return { ...view, update }
}

describe("label registration from an authorized read", () => {
    it("shows a name only after a page registered it, and the generic fallback before", () => {
        const { update } = setup(null)
        expect(label()).toBe("generic")
        update({ name: "Lantern Company" })
        expect(label()).toBe("Lantern Company")
    })

    it("keeps the label after the registering page has gone, for pages that follow", () => {
        const { rerender } = setup()
        expect(label()).toBe("Lantern Company")
        rerender(
            <Tree state={authenticated()}>
                <Reader />
            </Tree>,
        )
        expect(label()).toBe("Lantern Company")
    })

    it("falls back to the generic label with no provider at all", () => {
        render(
            <>
                <Registrant name="Lantern Company" />
                <Reader />
            </>,
        )
        expect(label()).toBe("generic")
    })
})

describe("invalidation by authority change", () => {
    it.each<[string, (b: SessionBootstrap) => void]>([
        ["capabilities", (b) => void b.campaigns[0]!.capabilities.push("canon.edit")],
        ["roles", (b) => void (b.campaigns[0]!.roles = ["player"])],
        ["world capabilities", (b) => void (b.campaigns[0]!.world_capabilities = ["world.view"])],
        ["available perspectives", (b) => void (b.campaigns[0]!.character_perspectives = [])],
        ["the clock-set state", (b) => void (b.campaigns[0]!.current_time_set = false)],
        ["the signed-in user", (b) => void (b.user.user_id = "another-user")],
        ["the browser session", (b) => void (b.browser_session_id = "another-session")],
    ])("clears every label when %s change in a refreshed bootstrap, without a remount", (_name, change) => {
        const { update } = setup()
        expect(label()).toBe("Lantern Company")
        update({ state: authenticated(bootstrap(change)), name: null })
        expect(label()).toBe("generic")
    })

    it("does not clear on a refresh that changes nothing the labels depend on", () => {
        const { update } = setup()
        update({ state: authenticated(bootstrap((b) => void (b.csrf_token = "rotated"))) })
        expect(label()).toBe("Lantern Company")
    })

    it("clears when the committed perspective changes and is not restored by returning to it", () => {
        const { update } = setup()
        update({ characterId: "character-other", name: null })
        expect(label()).toBe("generic")
        update({ characterId: CHARACTER, name: null })
        expect(label()).toBe("generic")
    })

    it("clears when the selection is cleared", () => {
        const { update } = setup()
        expect(label()).toBe("Lantern Company")
        update({ characterId: null, name: null })
        expect(label()).toBe("generic")
    })
})

describe("session loss", () => {
    it.each<[string, SessionBootstrapState]>([
        ["loading", { status: "loading" }],
        ["unauthenticated", { status: "unauthenticated" }],
        ["error", { status: "error", error: new Error("down") }],
    ])("drops every label when the session becomes %s, and does not bring them back on re-authentication", (_n, lost) => {
        const { update } = setup()
        expect(label()).toBe("Lantern Company")
        update({ state: lost, name: null })
        expect(label()).toBe("generic")
        update({ state: authenticated(), name: null })
        expect(label()).toBe("generic")
    })
})

describe("late registrations from an obsolete authority", () => {
    it("ignores a registration from a page that mounted before a context change, even after the context returns to its earlier value", () => {
        const { update } = setup(null)
        // The page began its read under authority A, then the authority became B...
        update({ characterId: "character-other", name: null })
        // ...then returned to A. The read answers now.
        update({ characterId: CHARACTER, name: "Late Name" })
        expect(label()).toBe("generic")
    })

    it("ignores a registration after a same-scope refresh changed capabilities", () => {
        const { update } = setup(null)
        update({
            state: authenticated(bootstrap((b) => void b.campaigns[0]!.capabilities.push("canon.edit"))),
            name: "Late Name",
        })
        expect(label()).toBe("generic")
    })

    it("ignores a registration while there is no session", () => {
        const { update } = setup(null)
        update({ state: { status: "loading" }, name: "Late Name" })
        expect(label()).toBe("generic")
    })

    it("accepts a registration from a page opened under the current authority", () => {
        const { update, rerender } = setup(null)
        update({ characterId: "character-other", name: null })
        // A page opened after the change (a new mount) is bound to the new registry.
        rerender(
            <Tree state={authenticated()} characterId="character-other">
                <Reader />
                <section>
                    <Registrant name="Fresh Name" />
                </section>
            </Tree>,
        )
        expect(label()).toBe("Fresh Name")
    })
})

describe("record denial", () => {
    it("drops the label of a record whose read is refused or unavailable", () => {
        const { update } = setup()
        expect(label()).toBe("Lantern Company")
        update({ denied: true })
        expect(label()).toBe("generic")
    })

    it("a denied page never registers its name", () => {
        const { update } = setup(null)
        update({ name: "Lantern Company", denied: true })
        expect(label()).toBe("generic")
    })
})
