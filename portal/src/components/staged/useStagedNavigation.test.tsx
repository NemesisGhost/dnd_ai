import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { StrictMode, useEffect, useState } from "react"
import { Link, RouterProvider, createMemoryRouter, useBlocker } from "react-router"
import type { DataRouter } from "react-router"
import { describe, expect, it } from "vitest"
import { isGuardedTransition } from "../../hooks/navigationHolds"
import { normalizationRoot } from "../../navigation/entryStamp"
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

// P02-7d correction: the section normalization belongs to the entry it was computed for. A mark identifies
// the write; it does not authorize it, so the write is made only while that entry is still the router's
// current one, nothing is pending and nothing is waiting on a decision. These pages are real routers with a
// real editor control and blocker; the lifecycle read that makes the page `ready` is deferred by the test,
// and the departure under test is performed BEFORE it answers (nothing here waits for normalization).
describe("section normalization is owned by its entry", () => {
    // The deferred lifecycle read: the test answers it by calling this.
    const read: { answer: (ready: boolean) => void } = { answer: () => {} }
    const setReady = (ready: boolean) => read.answer(ready)

    function Editor({ fallback = "one" as Key }: { fallback?: Key }) {
        const [ready, set] = useState(false)
        const [draft, setDraft] = useState("")
        useEffect(() => {
            read.answer = set
        }, [set])
        const blocker = useBlocker((transition) => draft !== "" && isGuardedTransition(transition))
        useStagedNavigation(SECTIONS, fallback, { ready })
        return (
            <div>
                <input aria-label="draft" value={draft} onChange={(event) => setDraft(event.target.value)} />
                {blocker.state === "blocked" && (
                    <div role="dialog">
                        <button onClick={() => blocker.reset()}>Stay</button>
                        <button onClick={() => blocker.proceed()}>Leave</button>
                    </div>
                )}
            </div>
        )
    }

    const TASK = { v: 1, root: "world", scope: { campaignId: "c" }, trail: [] }

    function mount(
        entries: Array<string | { pathname: string; search?: string; state?: unknown }>,
        options: { strict?: boolean; yLoader?: () => Promise<null> } = {},
    ) {
        const router: DataRouter = createMemoryRouter(
            [
                { path: "/x", element: <Editor /> },
                { path: "/y", element: <p>destination y</p>, ...(options.yLoader === undefined ? {} : { loader: options.yLoader }) },
            ],
            { initialEntries: entries },
        )
        const tree = <RouterProvider router={router} />
        render(options.strict === true ? <StrictMode>{tree}</StrictMode> : tree)
        return router
    }

    const writes = (router: DataRouter) => {
        const seen: string[] = []
        router.subscribe((state) => seen.push(`${state.historyAction} ${state.location.pathname}${state.location.search}`))
        return seen
    }

    it("a clean departure made while the read is deferred is not redirected back when the read answers", async () => {
        const router = mount([{ pathname: "/x", search: "?keep=1", state: { task: TASK } }])
        expect(router.state.location.search).toBe("?keep=1")
        await act(async () => {
            void router.navigate("/y")
            setReady(true)
        })
        await screen.findByText("destination y")
        expect(router.state.location.pathname).toBe("/y")
        expect(router.state.location.search).toBe("")
        expect(router.state.historyAction).toBe("PUSH")
    })

    it("a dirty departure that is kept (Stay) is normalized on the same entry afterwards, keeping the task and the draft", async () => {
        const router = mount([{ pathname: "/x", search: "?keep=1", state: { task: TASK, worldSearch: "?q=a" } }])
        const first = router.state.location.key
        fireEvent.change(screen.getByLabelText("draft"), { target: { value: "unsaved" } })
        await act(async () => {
            void router.navigate("/y")
        })
        await screen.findByRole("dialog")
        // The answer arrives while the question is open: nothing may be written under it.
        await act(async () => {
            setReady(true)
        })
        expect(router.state.location.key).toBe(first)
        expect(router.state.location.search).toBe("?keep=1")
        expect([...router.state.blockers.values()].some((blocker) => blocker.state === "blocked")).toBe(true)
        fireEvent.click(screen.getByRole("button", { name: "Stay" }))
        await waitFor(() => expect(router.state.location.search).toBe("?keep=1&section=one"))
        expect(router.state.location.pathname).toBe("/x")
        expect(router.state.location.state).toEqual({ task: TASK, worldSearch: "?q=a" })
        expect(screen.getByLabelText("draft")).toHaveValue("unsaved")
        expect(screen.queryByRole("dialog")).toBeNull()
    })

    it("a dirty departure that is allowed (Leave) is never overwritten by the late answer", async () => {
        const router = mount([{ pathname: "/x", search: "?keep=1", state: { task: TASK } }])
        fireEvent.change(screen.getByLabelText("draft"), { target: { value: "unsaved" } })
        await act(async () => {
            void router.navigate("/y", { state: { destination: true } })
        })
        await screen.findByRole("dialog")
        await act(async () => {
            setReady(true)
        })
        fireEvent.click(screen.getByRole("button", { name: "Leave" }))
        await screen.findByText("destination y")
        expect(router.state.location.pathname).toBe("/y")
        expect(router.state.location.state).toEqual({ destination: true })
        expect(router.state.historyAction).toBe("PUSH")
    })

    it("a newer entry at the same address keeps its own state and is not rewritten from the older one", async () => {
        const router = mount([{ pathname: "/x", search: "?keep=1", state: { task: TASK, which: "older" } }])
        await act(async () => {
            void router.navigate("/x?keep=1", { state: { task: TASK, which: "newer" } })
            setReady(true)
        })
        await waitFor(() => expect(router.state.location.search).toBe("?keep=1&section=one"))
        expect(router.state.location.state).toEqual({ task: TASK, which: "newer" })
        expect(router.state.historyAction).toBe("REPLACE")
    })

    it("navigation superseding a pending normalization wins: the write is abandoned, not applied after it", async () => {
        let release: () => void = () => {}
        const router = mount([{ pathname: "/x", search: "?keep=1" }], {
            yLoader: () => new Promise<null>((resolve) => (release = () => resolve(null))),
        })
        const seen = writes(router)
        await act(async () => {
            void router.navigate("/y")
        })
        expect(router.state.navigation.state).toBe("loading")
        await act(async () => {
            setReady(true)
        })
        // Pending navigation: the normalization waits rather than interrupting it.
        expect(router.state.navigation.state).toBe("loading")
        await act(async () => {
            release()
        })
        await screen.findByText("destination y")
        expect(router.state.location.pathname).toBe("/y")
        expect(seen.filter((entry) => entry.startsWith("REPLACE"))).toEqual([])
    })

    it("normalizes the current entry once, marked as its normalization, in StrictMode too", async () => {
        const router = mount([{ pathname: "/x", search: "?keep=1", state: { task: TASK } }], { strict: true })
        const origin = router.state.location.key
        const seen = writes(router)
        await act(async () => {
            setReady(true)
        })
        await waitFor(() => expect(router.state.location.search).toBe("?keep=1&section=one"))
        expect(seen.filter((entry) => entry.startsWith("REPLACE"))).toHaveLength(1)
        expect(seen.filter((entry) => !entry.startsWith("REPLACE"))).toEqual([])
        expect(router.state.location.state).toEqual({ task: TASK })
        expect(normalizationRoot(router.state.location.state)).toBe(origin)
        expect(router.state.location.key).not.toBe(origin)
    })
})
