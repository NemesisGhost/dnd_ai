import { act, fireEvent, render, screen } from "@testing-library/react"
import { useLayoutEffect, useState } from "react"
import { MemoryRouter, RouterProvider, createMemoryRouter } from "react-router"
import type { DataRouter } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { useUnsavedChangesGuard } from "./useUnsavedChangesGuard"

// The guard must intercept a departure from the first commit in which it is required. These cases attempt the
// navigation from a sibling's layout effect, which runs in the same commit as the guard's first render or its
// first dirty render and before any passive effect, so no timer, wait or event ordering can hide a late
// registration. (react-router's own useBlocker registers in two successive passive-effect passes.)

let router: DataRouter

function Guarded({ dirty }: { dirty: boolean }) {
    const guard = useUnsavedChangesGuard(dirty)
    return guard.blocked ? (
        <div role="dialog" aria-label="blocked">
            <button type="button" onClick={guard.stay}>
                stay
            </button>
            <button type="button" onClick={guard.discard}>
                discard
            </button>
        </div>
    ) : null
}

// Attempts a navigation in the commit where `attempt` first becomes true.
function Probe({ attempt, to }: { attempt: boolean; to: string }) {
    useLayoutEffect(() => {
        if (attempt) {
            void router.navigate(to)
        }
    }, [attempt, to])
    return null
}

function Page({ initialMounted, initialDirty }: { initialMounted: boolean; initialDirty: boolean }) {
    const [mounted, setMounted] = useState(initialMounted)
    const [dirty, setDirty] = useState(initialDirty)
    const [attempt, setAttempt] = useState(false)
    const [to, setTo] = useState("/elsewhere")
    return (
        <div>
            <button type="button" onClick={() => setMounted(false)}>
                unmount guard
            </button>
            <button
                type="button"
                onClick={() => {
                    setDirty(true)
                    setAttempt(true)
                }}
            >
                become dirty and attempt
            </button>
            <button
                type="button"
                onClick={() => {
                    setMounted(true)
                    setDirty(true)
                    setAttempt(true)
                }}
            >
                mount dirty and attempt
            </button>
            <button type="button" onClick={() => setDirty(false)}>
                become clean
            </button>
            <button
                type="button"
                onClick={() => {
                    setTo("/form?step=2")
                    setDirty(true)
                    setAttempt(true)
                }}
            >
                query only
            </button>
            {mounted ? <Guarded dirty={dirty} /> : null}
            <Probe attempt={attempt} to={to} />
        </div>
    )
}

function setup(page: { initialMounted: boolean; initialDirty: boolean }) {
    router = createMemoryRouter(
        [
            { path: "/form", element: <Page {...page} /> },
            { path: "/elsewhere", element: <p>Elsewhere</p> },
        ],
        { initialEntries: ["/form"] },
    )
    render(<RouterProvider router={router} />)
    return router
}

afterEach(() => {
    vi.restoreAllMocks()
})

describe("guard registration", () => {
    it("holds a departure attempted in the very commit where a protected guard first renders", async () => {
        setup({ initialMounted: false, initialDirty: false })
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "mount dirty and attempt" }))
        })
        expect(router.state.location.pathname).toBe("/form")
        expect(screen.getByRole("dialog", { name: "blocked" })).toBeInTheDocument()

        // Stay keeps the page; leaving afterwards completes the held navigation.
        fireEvent.click(screen.getByRole("button", { name: "stay" }))
        expect(router.state.location.pathname).toBe("/form")
    })

    it("holds a departure attempted in the very commit where a mounted guard first becomes dirty", async () => {
        setup({ initialMounted: true, initialDirty: false })
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "become dirty and attempt" }))
        })
        expect(router.state.location.pathname).toBe("/form")
        expect(screen.getByRole("dialog", { name: "blocked" })).toBeInTheDocument()

        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "discard" }))
        })
        expect(router.state.location.pathname).toBe("/elsewhere")
    })

    it("does not hold a departure attempted in the commit where the guard became clean", async () => {
        setup({ initialMounted: true, initialDirty: true })
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "become clean" }))
        })
        await act(async () => {
            void router.navigate("/elsewhere")
        })
        expect(router.state.location.pathname).toBe("/elsewhere")
    })

    it("does not hold a query-only change from the first protected render", async () => {
        setup({ initialMounted: true, initialDirty: false })
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "query only" }))
        })
        expect(router.state.location.pathname).toBe("/form")
        expect(router.state.location.search).toBe("?step=2")
        expect(screen.queryByRole("dialog", { name: "blocked" })).toBeNull()
    })

    it("stops holding once the guard unmounts, and leaves no blocker behind", async () => {
        setup({ initialMounted: true, initialDirty: true })
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "unmount guard" }))
        })
        await act(async () => {
            void router.navigate("/elsewhere")
        })
        expect(router.state.location.pathname).toBe("/elsewhere")
        expect(router.state.blockers.size).toBe(0)
    })

    it("unmounting with the question open cancels the held navigation instead of approving it", async () => {
        setup({ initialMounted: true, initialDirty: false })
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "become dirty and attempt" }))
        })
        expect(screen.getByRole("dialog", { name: "blocked" })).toBeInTheDocument()
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "unmount guard" }))
        })
        expect(router.state.location.pathname).toBe("/form")
        expect(router.state.blockers.size).toBe(0)
    })

    it("keeps exactly one blocker through repeated protected transitions", async () => {
        const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
        setup({ initialMounted: true, initialDirty: false })
        for (let i = 0; i < 3; i++) {
            fireEvent.click(screen.getByRole("button", { name: "become dirty and attempt" }))
            fireEvent.click(screen.getByRole("button", { name: "become clean" }))
        }
        await act(async () => {})
        expect(warn.mock.calls.filter((call) => String(call[0]).includes("one blocker"))).toEqual([])
    })

    it("still requires a data router, as useBlocker did", () => {
        const error = vi.spyOn(console, "error").mockImplementation(() => {})
        expect(() =>
            render(
                <MemoryRouter>
                    <Guarded dirty />
                </MemoryRouter>,
            ),
        ).toThrow(/must be used within a data router/)
        error.mockRestore()
    })
})
