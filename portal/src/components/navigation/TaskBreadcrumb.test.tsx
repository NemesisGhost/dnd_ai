import { act, fireEvent, render, screen, within } from "@testing-library/react"
import { useContext } from "react"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { RouterProvider, createMemoryRouter, useLocation } from "react-router"
import { describe, expect, it, vi } from "vitest"
import { SessionContext } from "../../context/SessionContext"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import type { SessionBootstrap } from "../../types/bootstrap"
import { BreadcrumbLabelProvider } from "../../navigation/BreadcrumbLabelProvider"
import { BreadcrumbLabelContext, useBreadcrumbLabel } from "../../navigation/BreadcrumbLabelContext"
import { continuedState } from "../../navigation/breadcrumbModel"
import { TaskBreadcrumb } from "./TaskBreadcrumb"

const C = "mundivita"
const P = "p1"
const base = `/app/${C}`

function Page({ current }: { current?: string }) {
    return <TaskBreadcrumb current={current} />
}

function open(initial: string | { pathname: string; state: unknown }, current?: string) {
    const router = createMemoryRouter([{ path: "*", element: <Page current={current} /> }], {
        initialEntries: [initial],
    })
    render(<RouterProvider router={router} />)
    return router
}

const crumbs = () =>
    within(screen.getByRole("navigation", { name: "Breadcrumb" }))
        .getAllByRole("listitem")
        .map((item) => item.textContent)

describe("TaskBreadcrumb markup", () => {
    it("is a labelled navigation landmark with an ordered list, links for ancestors and a marked current page", () => {
        open(`${base}/parties/${P}/edit`)
        const nav = screen.getByRole("navigation", { name: "Breadcrumb" })
        expect(within(nav).getByRole("list").tagName).toBe("OL")
        expect(within(nav).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
            `${base}/parties`,
            `${base}/parties/${P}`,
        ])
        const current = nav.querySelector("[aria-current='page']")
        expect(current?.textContent).toBe("Edit")
        // The current page is text, not a link, and it is the only marked item.
        expect(current?.closest("a")).toBeNull()
        expect(nav.querySelectorAll("[aria-current]")).toHaveLength(1)
        expect(crumbs()).toEqual(["Parties", "Party", "Edit"])
    })

    it("uses the page's own heading text for the current page when it has one", () => {
        open(`${base}/parties/${P}`, "Lantern Company")
        expect(screen.getByText("Lantern Company")).toHaveAttribute("aria-current", "page")
    })

    it("renders nothing on a page that is the top of its task, and on a page with no task", () => {
        open(`${base}/parties`)
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    })

    it("wraps instead of overflowing: the list is a wrapping flex row with breakable items", () => {
        // A style contract only; real wrapping at 320 px and 400% zoom is a pending browser check.
        const css = readFileSync(join(process.cwd(), "src/components/authoring/authoring.css"), "utf8")
        const rule = (selector: string) => css.slice(css.indexOf(selector), css.indexOf("}", css.indexOf(selector)))
        expect(rule(".task-breadcrumb__list {")).toMatch(/flex-wrap:\s*wrap/)
        expect(rule(".task-breadcrumb__list li {")).toMatch(/overflow-wrap:\s*anywhere/)
    })
})

describe("TaskBreadcrumb links", () => {
    it("follow as ordinary links and carry the task cut back to that ancestor", async () => {
        const router = open(`${base}/parties/${P}/edit`)
        await act(async () => {
            fireEvent.click(screen.getByRole("link", { name: "Party" }))
        })
        expect(router.state.location.pathname).toBe(`${base}/parties/${P}`)
        expect(router.state.location.state).toMatchObject({
            task: { v: 1, root: "parties", scope: { campaignId: C }, trail: [{ route: "parties.list" }] },
        })
        // The destination's breadcrumb is exactly what that task says.
        expect(crumbs()).toEqual(["Parties", "Party"])
    })

    it("keep the Parties task on the way back to the list", async () => {
        const router = open(`${base}/parties/${P}/edit`)
        await act(async () => {
            fireEvent.click(screen.getByRole("link", { name: "Parties" }))
        })
        expect(router.state.location.pathname).toBe(`${base}/parties`)
        expect(router.state.location.state).toMatchObject({ task: { root: "parties", trail: [] } })
    })

    it("never offer Campaign Home as an ancestor of a Parties page", () => {
        open(`${base}/parties/${P}/edit`)
        expect(screen.queryByRole("link", { name: "Campaign Home" })).toBeNull()
    })
})

describe("TaskBreadcrumb history", () => {
    const fromList = continuedState(`${base}/parties`, undefined)!
    const fromDetail = continuedState(`${base}/parties/${P}`, fromList)!

    it("shows the same trail after a same-tab reload (an entry seeded with its state)", () => {
        open({ pathname: `${base}/parties/${P}/edit`, state: fromDetail })
        expect(crumbs()).toEqual(["Parties", "Party", "Edit"])
    })

    it("restores the trail of the entry it returns to on Back and Forward", async () => {
        const router = open({ pathname: `${base}/characters/c9`, state: fromDetail })
        expect(crumbs()).toEqual(["Parties", "Party", "Character"])
        await act(async () => {
            await router.navigate(`${base}/characters/c9/inventory`)
        })
        // No task in that entry: the route's defaults.
        expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument()
        expect(crumbs()[0]).not.toBe("Parties")
        await act(async () => {
            await router.navigate(-1)
        })
        expect(crumbs()).toEqual(["Parties", "Party", "Character"])
        await act(async () => {
            await router.navigate(1)
        })
        expect(crumbs()[0]).not.toBe("Parties")
    })

    it("ignores a task from another campaign and falls back to the defaults", () => {
        open({
            pathname: `${base}/parties/${P}/edit`,
            state: { task: { v: 1, root: "parties", scope: { campaignId: "other" }, trail: [] } },
        })
        expect(crumbs()).toEqual(["Parties", "Party", "Edit"])
    })

    it("ignores malformed history state", () => {
        open({ pathname: `${base}/parties/${P}/edit`, state: { task: { v: 1, root: 7, trail: "x" } } })
        expect(crumbs()).toEqual(["Parties", "Party", "Edit"])
    })
})

describe("TaskBreadcrumb names", () => {
    const bootstrap = (change: (b: SessionBootstrap) => void = () => undefined): SessionBootstrap => {
        const copy = structuredClone(sessionBootstrapFixture) as SessionBootstrap
        change(copy)
        return copy
    }

    function Registrant({ name }: { name: string | null }) {
        // A read started under the registry now in force.
        const authority = useContext(BreadcrumbLabelContext)
        useBreadcrumbLabel({ route: "parties.detail", params: { campaignId: C, partyId: P }, name, authority })
        return null
    }

    // The page for party p1 reads (and registers) the name; every other page only shows the trail.
    function Harness({ b }: { b: SessionBootstrap }) {
        const registrant = useLocation().pathname.endsWith(`/${P}`)
        return (
            <SessionContext.Provider
                value={{ state: { status: "authenticated", bootstrap: b }, reload: vi.fn(), refresh: vi.fn() }}
            >
                <BreadcrumbLabelProvider campaignId={C} characterId="character-ixamarra">
                    {registrant ? <Registrant name="Lantern Company" /> : null}
                    <TaskBreadcrumb />
                </BreadcrumbLabelProvider>
            </SessionContext.Provider>
        )
    }

    function openAt(pathname: string) {
        const router = createMemoryRouter(
            [{ path: "*", element: <Harness b={bootstrap()} /> }],
            { initialEntries: [pathname] },
        )
        render(<RouterProvider router={router} />)
        return router
    }

    it("shows a generic noun until a page has registered the name, then the name", async () => {
        const router = openAt(`${base}/parties/p2/edit`)
        expect(crumbs()).toEqual(["Parties", "Party", "Edit"])
        // A page for another party registers nothing for this one.
        await act(async () => {
            await router.navigate(`${base}/parties/${P}`)
        })
        await act(async () => {
            await router.navigate(`${base}/parties/${P}/edit`)
        })
        // The registrant unmounted with the page that read it; its label remains for the pages that follow.
        expect(crumbs()).toEqual(["Parties", "Lantern Company", "Edit"])
        expect(screen.getByRole("link", { name: "Lantern Company" })).toHaveAttribute("href", `${base}/parties/${P}`)
    })

    it("never writes the name into the link's history state", async () => {
        const router = openAt(`${base}/parties/${P}`)
        await act(async () => {
            await router.navigate(`${base}/parties/${P}/edit`)
        })
        await act(async () => {
            fireEvent.click(screen.getByRole("link", { name: "Lantern Company" }))
        })
        expect(JSON.stringify(router.state.location.state)).not.toContain("Lantern")
        expect(JSON.stringify(router.state.location)).not.toContain("Lantern")
    })
})
