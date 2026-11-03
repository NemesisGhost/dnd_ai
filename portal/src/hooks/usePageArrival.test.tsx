import { act, render, screen } from "@testing-library/react"
import { RouterProvider, createMemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import { AnnouncerProvider } from "../components/authoring/AnnouncerProvider"
import { usePageArrival } from "./usePageArrival"

function Page() {
    const heading = usePageArrival(true)
    return (
        <AnnouncerProvider>
            <h1 ref={heading} tabIndex={-1}>
                Page
            </h1>
            <input aria-label="Field" />
        </AnnouncerProvider>
    )
}

function mount(initial = "/a") {
    const router = createMemoryRouter([{ path: "*", element: <Page /> }], { initialEntries: [initial] })
    render(<RouterProvider router={router} />)
    return router
}

describe("usePageArrival", () => {
    it("focuses the heading on arrival", () => {
        mount()
        expect(screen.getByRole("heading", { name: "Page" })).toHaveFocus()
    })

    it("focuses the heading again for a new entry", async () => {
        const router = mount()
        screen.getByRole("textbox", { name: "Field" }).focus()
        await act(async () => {
            await router.navigate("/b")
        })
        expect(screen.getByRole("heading", { name: "Page" })).toHaveFocus()
    })

    it("does not treat a same-address REPLACE with nothing to announce as an arrival (a stamp)", async () => {
        const router = mount("/a?x=1")
        const field = screen.getByRole("textbox", { name: "Field" })
        field.focus()
        const before = router.state.location.key

        await act(async () => {
            await router.navigate("/a?x=1", { replace: true, state: { ctx: { v: 1, characterId: null } } })
        })

        expect(router.state.location.key).not.toBe(before)
        expect(field).toHaveFocus()
    })

    it("still treats a REPLACE to another address as an arrival", async () => {
        const router = mount("/a")
        screen.getByRole("textbox", { name: "Field" }).focus()
        await act(async () => {
            await router.navigate("/b", { replace: true })
        })
        expect(screen.getByRole("heading", { name: "Page" })).toHaveFocus()
    })
})
