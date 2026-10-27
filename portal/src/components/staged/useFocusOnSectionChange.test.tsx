import { act, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { useFocusOnSectionChange } from "./useFocusOnSectionChange"

type Key = "one" | "two" | "three"

function Probe({
    section,
    ready,
    offered = ["one", "two", "three"],
}: {
    section: Key
    ready?: boolean
    offered?: Key[]
}) {
    useFocusOnSectionChange(section, (s) => document.getElementById(`h-${s}`)?.focus(), {
        ready,
        keep: (previous) => offered.includes(previous),
    })
    return (
        <div>
            {(["one", "two", "three"] as const).map((k) => (
                <h2 key={k} id={`h-${k}`} tabIndex={-1}>
                    {k}
                </h2>
            ))}
            <button type="button">elsewhere</button>
        </div>
    )
}

describe("useFocusOnSectionChange", () => {
    it("leaves focus alone on arrival and moves it when the section changes", () => {
        const { rerender } = render(<Probe section="one" />)
        expect(document.body).toHaveFocus()
        rerender(<Probe section="two" />)
        expect(screen.getByRole("heading", { name: "two" })).toHaveFocus()
        rerender(<Probe section="three" />)
        expect(screen.getByRole("heading", { name: "three" })).toHaveFocus()
    })

    it("does not move focus when the same section is rendered again", () => {
        const { rerender } = render(<Probe section="one" />)
        screen.getByRole("button", { name: "elsewhere" }).focus()
        rerender(<Probe section="one" />)
        expect(screen.getByRole("button", { name: "elsewhere" })).toHaveFocus()
    })

    it("treats the section it becomes ready on as the arrival", () => {
        const { rerender } = render(<Probe section="one" ready={false} />)
        rerender(<Probe section="two" ready={false} />)
        expect(document.body).toHaveFocus()
        rerender(<Probe section="two" ready />)
        expect(document.body).toHaveFocus()
        rerender(<Probe section="three" ready />)
        expect(screen.getByRole("heading", { name: "three" })).toHaveFocus()
    })

    it("keeps focus where it is when the section left is no longer offered", () => {
        const { rerender } = render(<Probe section="one" />)
        const button = screen.getByRole("button", { name: "elsewhere" })
        act(() => button.focus())
        // "one" is withdrawn from under the person, who lands on "two" without asking.
        rerender(<Probe section="two" offered={["two", "three"]} />)
        expect(button).toHaveFocus()
        // A later, genuine change still moves focus.
        rerender(<Probe section="three" offered={["two", "three"]} />)
        expect(screen.getByRole("heading", { name: "three" })).toHaveFocus()
    })
})
