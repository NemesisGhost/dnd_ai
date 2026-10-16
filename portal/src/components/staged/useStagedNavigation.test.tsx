import { fireEvent, render, screen } from "@testing-library/react"
import { Link, RouterProvider, createMemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import { useStagedNavigation } from "./useStagedNavigation"

type Stage = "a" | "b"
type Key = "one" | "two" | "three"
const SECTIONS: { key: Key; stage: Stage }[] = [
    { key: "one", stage: "a" },
    { key: "two", stage: "a" },
    { key: "three", stage: "b" },
]

function Probe({ ready = true, fallback = "one" as Key }: { ready?: boolean; fallback?: Key }) {
    const nav = useStagedNavigation(SECTIONS, fallback, { ready })
    return (
        <div>
            <p data-testid="now">{`${nav.stage}/${nav.section}`}</p>
            <Link to={nav.sectionHref("two")}>section two</Link>
            <Link to={nav.sectionHref("three")}>section three</Link>
            <Link to={nav.stageHref("a")}>stage a</Link>
            <Link to={nav.stageHref("b")}>stage b</Link>
        </div>
    )
}

function setup(entry: string | { pathname: string; search?: string; state?: unknown }, props: Parameters<typeof Probe>[0] = {}) {
    const router = createMemoryRouter([{ path: "/x", element: <Probe {...props} /> }], { initialEntries: [entry] })
    render(<RouterProvider router={router} />)
    return router
}

describe("useStagedNavigation", () => {
    it("shows the default section and puts it in the address by replacing the entry", () => {
        const router = setup("/x?keep=1")
        expect(screen.getByTestId("now")).toHaveTextContent("a/one")
        expect(router.state.location.search).toBe("?keep=1&section=one")
        expect(router.state.historyAction).toBe("REPLACE")
    })

    it("treats a section the record does not have as unknown", () => {
        const router = setup("/x?section=run")
        expect(screen.getByTestId("now")).toHaveTextContent("a/one")
        expect(router.state.location.search).toBe("?section=one")
    })

    it("waits for the default to be known before correcting the address", () => {
        const router = setup("/x", { ready: false })
        expect(router.state.location.search).toBe("")
        expect(screen.getByTestId("now")).toHaveTextContent("a/one")
    })

    it("keeps the router state when it corrects the address", () => {
        const router = setup({ pathname: "/x", state: { reviewSearch: "?status=draft" } })
        expect(router.state.location.state).toEqual({ reviewSearch: "?status=draft" })
    })

    it("pushes a history entry for a chosen section and keeps other parameters", async () => {
        const router = setup("/x?keep=1&section=one")
        fireEvent.click(screen.getByRole("link", { name: "section two" }))
        await screen.findByText("a/two")
        expect(router.state.location.search).toBe("?keep=1&section=two")
        expect(router.state.historyAction).toBe("PUSH")
        await router.navigate(-1)
        await screen.findByText("a/one")
    })

    it("reopens a stage on the section last shown in it", async () => {
        setup("/x?section=two")
        fireEvent.click(screen.getByRole("link", { name: "stage b" }))
        await screen.findByText("b/three")
        expect(screen.getByRole("link", { name: "stage a" })).toHaveAttribute("href", "/x?section=two")
    })

    it("uses the first section of a stage not visited yet", () => {
        setup("/x?section=one")
        expect(screen.getByRole("link", { name: "stage b" })).toHaveAttribute("href", "/x?section=three")
    })
})
