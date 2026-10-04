import { act, fireEvent, render, screen } from "@testing-library/react"
import { useState } from "react"
import { Link, RouterProvider, createMemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import { useUnsavedChangesGuard } from "./useUnsavedChangesGuard"

function Form() {
    const [dirty, setDirty] = useState(false)
    const guard = useUnsavedChangesGuard(dirty)
    return (
        <div>
            <button type="button" onClick={() => setDirty(true)}>
                edit
            </button>
            <button type="button" onClick={() => guard.release()}>
                release
            </button>
            <Link to="/elsewhere">leave</Link>
            <Link to="/form?step=2">next step</Link>
            {guard.blocked ? (
                <div role="dialog" aria-label="blocked">
                    <button type="button" onClick={guard.stay}>
                        stay
                    </button>
                    <button type="button" onClick={guard.discard}>
                        discard
                    </button>
                </div>
            ) : null}
        </div>
    )
}

function setup() {
    const router = createMemoryRouter(
        [
            { path: "/form", element: <Form /> },
            { path: "/elsewhere", element: <p>Elsewhere</p> },
        ],
        { initialEntries: ["/form"] },
    )
    render(<RouterProvider router={router} />)
    return router
}

describe("useUnsavedChangesGuard", () => {
    it("lets a clean form navigate freely", () => {
        const router = setup()
        fireEvent.click(screen.getByRole("link", { name: "leave" }))
        expect(router.state.location.pathname).toBe("/elsewhere")
    })

    it("holds a dirty form's navigation until the user decides, and stays on request", () => {
        const router = setup()
        fireEvent.click(screen.getByRole("button", { name: "edit" }))
        fireEvent.click(screen.getByRole("link", { name: "leave" }))

        expect(router.state.location.pathname).toBe("/form")
        expect(screen.getByRole("dialog", { name: "blocked" })).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "stay" }))
        expect(screen.queryByRole("dialog", { name: "blocked" })).not.toBeInTheDocument()
        expect(router.state.location.pathname).toBe("/form")
    })

    it("completes the held navigation when the user discards", () => {
        const router = setup()
        fireEvent.click(screen.getByRole("button", { name: "edit" }))
        fireEvent.click(screen.getByRole("link", { name: "leave" }))
        fireEvent.click(screen.getByRole("button", { name: "discard" }))
        expect(router.state.location.pathname).toBe("/elsewhere")
    })

    it("does not treat a query-only change as leaving the form", () => {
        const router = setup()
        fireEvent.click(screen.getByRole("button", { name: "edit" }))
        fireEvent.click(screen.getByRole("link", { name: "next step" }))
        expect(router.state.location.search).toBe("?step=2")
        expect(screen.queryByRole("dialog", { name: "blocked" })).not.toBeInTheDocument()
    })

    it("lets a deliberate post-save navigation through once released", () => {
        const router = setup()
        fireEvent.click(screen.getByRole("button", { name: "edit" }))
        fireEvent.click(screen.getByRole("button", { name: "release" }))
        fireEvent.click(screen.getByRole("link", { name: "leave" }))
        expect(router.state.location.pathname).toBe("/elsewhere")
    })

    it("asks the browser to confirm closing the tab only while dirty", () => {
        setup()
        const clean = new Event("beforeunload", { cancelable: true })
        act(() => {
            window.dispatchEvent(clean)
        })
        expect(clean.defaultPrevented).toBe(false)

        fireEvent.click(screen.getByRole("button", { name: "edit" }))
        const dirty = new Event("beforeunload", { cancelable: true })
        act(() => {
            window.dispatchEvent(dirty)
        })
        expect(dirty.defaultPrevented).toBe(true)
    })
})
