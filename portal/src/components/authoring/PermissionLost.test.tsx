import { fireEvent, render, screen } from "@testing-library/react"
import { useState } from "react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import { PermissionLost } from "./PermissionLost"

// The panel replaces a form whose Save button had focus, so focus would otherwise fall to the page.
function Harness({ retained = [] as { label: string; value: string }[] }) {
    const [lost, setLost] = useState(false)
    const [ticks, setTicks] = useState(0)
    return (
        <MemoryRouter>
            <button type="button" onClick={() => setLost(true)}>
                Save
            </button>
            <button type="button" onClick={() => setTicks(ticks + 1)}>
                Rerender {ticks}
            </button>
            {lost ? (
                <PermissionLost noun="record" retained={retained} back={{ to: "/back" }} recheck={() => setLost(false)} />
            ) : null}
            <button type="button">After the panel</button>
        </MemoryRouter>
    )
}

describe("PermissionLost keyboard focus", () => {
    it("moves focus to its heading when it appears, from a control that is then gone", () => {
        render(<Harness />)
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        const heading = screen.getByRole("heading", { name: /no longer have permission to edit this record/ })
        expect(heading).toHaveFocus()
        expect(document.activeElement).not.toBe(document.body)
    })

    it("is one announcement: a named region, not also a live alert", () => {
        render(<Harness />)
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        expect(screen.getByRole("region", { name: "Permission lost" })).toBeInTheDocument()
        expect(screen.queryByRole("alert")).toBeNull()
    })

    it("does not take focus back on a rerender", () => {
        render(<Harness />)
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        const heading = screen.getByRole("heading", { name: /no longer have permission/ })
        expect(heading).toHaveFocus()

        screen.getByRole("button", { name: /^Rerender/ }).focus()
        fireEvent.click(screen.getByRole("button", { name: /^Rerender/ }))
        expect(screen.getByRole("button", { name: /^Rerender/ })).toHaveFocus()
        expect(heading).not.toHaveFocus()
    })

    it("leaves the tab order logical: the heading is focusable only by script, then link, button, page", () => {
        render(<Harness />)
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        const heading = screen.getByRole("heading", { name: /no longer have permission/ })
        expect(heading).toHaveAttribute("tabindex", "-1")
        const tabbable = [...document.querySelectorAll<HTMLElement>("a[href], button, [tabindex]:not([tabindex='-1'])")]
        const names = tabbable.map((el) => el.textContent)
        expect(names.slice(names.indexOf("Back to the record"))).toEqual([
            "Back to the record",
            "Check my access again",
            "After the panel",
        ])
    })

    it("keeps showing only the typed input", () => {
        render(<Harness retained={[{ label: "Name", value: "Founders' Hall" }]} />)
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        expect(screen.getByRole("region", { name: "Permission lost" })).toHaveTextContent("Founders' Hall")
    })
})
