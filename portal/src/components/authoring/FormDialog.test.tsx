import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { useState } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { FormDialog } from "./FormDialog"
import type { FormDialogPrompt } from "./FormDialog"

function Harness({
    onDismiss = vi.fn(),
    pending = false,
    prompt = null,
    returnFocusTo,
}: {
    onDismiss?: () => void
    pending?: boolean
    prompt?: FormDialogPrompt | null
    returnFocusTo?: () => HTMLElement | null
}) {
    const [open, setOpen] = useState(false)
    return (
        <>
            <button type="button" onClick={() => setOpen(true)}>
                Open it
            </button>
            <button type="button" onClick={() => setOpen(false)}>
                Close it
            </button>
            <FormDialog
                open={open}
                title="Record a thing"
                description="It adds a thing."
                onDismiss={onDismiss}
                pending={pending}
                prompt={prompt}
                returnFocusTo={returnFocusTo}
            >
                <label>
                    Name
                    <input defaultValue="" />
                </label>
                <button type="button">Inside action</button>
            </FormDialog>
        </>
    )
}

const escape = (dialog: HTMLElement) => {
    const event = new Event("cancel", { cancelable: true })
    fireEvent(dialog, event)
    return event
}

describe("FormDialog", () => {
    it("is labelled and described, and moves focus to the first control when it opens", () => {
        render(<Harness />)
        fireEvent.click(screen.getByRole("button", { name: "Open it" }))
        const dialog = screen.getByRole("dialog", { name: "Record a thing" })
        expect(dialog).toHaveAccessibleDescription("It adds a thing.")
        expect(screen.getByRole("textbox", { name: "Name" })).toHaveFocus()
    })

    it("returns focus to the control that opened it", () => {
        render(<Harness />)
        const opener = screen.getByRole("button", { name: "Open it" })
        opener.focus()
        fireEvent.click(opener)
        fireEvent.click(screen.getByRole("button", { name: "Close it", hidden: true }))
        expect(opener).toHaveFocus()
    })

    it("keeps its children, and what was typed in them, while it is closed", () => {
        render(<Harness />)
        const opener = screen.getByRole("button", { name: "Open it" })
        fireEvent.click(opener)
        fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "kept" } })
        fireEvent.click(screen.getByRole("button", { name: "Close it", hidden: true }))
        expect(screen.queryByRole("dialog", { name: "Record a thing" })).toBeNull()
        fireEvent.click(opener)
        expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("kept")
    })

    it("hands Escape to the page, and ignores it while a request is pending", () => {
        const onDismiss = vi.fn()
        const { rerender } = render(<Harness onDismiss={onDismiss} />)
        fireEvent.click(screen.getByRole("button", { name: "Open it" }))
        const dialog = screen.getByRole("dialog", { name: "Record a thing" })
        const first = escape(dialog)
        // The native dialog is never closed by Escape itself: only the page closes it.
        expect(first.defaultPrevented).toBe(true)
        expect(onDismiss).toHaveBeenCalledTimes(1)

        rerender(<Harness onDismiss={onDismiss} pending />)
        const second = escape(screen.getByRole("dialog", { name: "Record a thing" }))
        expect(second.defaultPrevented).toBe(true)
        expect(onDismiss).toHaveBeenCalledTimes(1)
    })

    it("does nothing when the backdrop is clicked", () => {
        const onDismiss = vi.fn()
        render(<Harness onDismiss={onDismiss} />)
        fireEvent.click(screen.getByRole("button", { name: "Open it" }))
        const dialog = screen.getByRole("dialog", { name: "Record a thing" })
        fireEvent.click(dialog)
        fireEvent.mouseDown(dialog)
        expect(onDismiss).not.toHaveBeenCalled()
        expect(screen.getByRole("dialog", { name: "Record a thing" })).toBeInTheDocument()
    })

    it("asks inside itself, keeps the form's values, and gives focus back when answered", () => {
        const onKeep = vi.fn()
        const prompt: FormDialogPrompt = {
            message: "Discard this?",
            keepLabel: "Keep editing",
            confirmLabel: "Discard",
            onKeep,
            onConfirm: vi.fn(),
        }
        const { rerender } = render(<Harness />)
        fireEvent.click(screen.getByRole("button", { name: "Open it" }))
        const input = screen.getByRole("textbox", { name: "Name" })
        fireEvent.change(input, { target: { value: "typed" } })
        input.focus()

        rerender(<Harness prompt={prompt} />)
        expect(screen.getByText("Discard this?")).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Keep editing" })).toHaveFocus()
        // Only one dialog: the question is inside it, not a second modal.
        expect(screen.getAllByRole("dialog")).toHaveLength(1)

        rerender(<Harness prompt={null} />)
        expect(screen.queryByText("Discard this?")).toBeNull()
        expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("typed")
        expect(screen.getByRole("textbox", { name: "Name" })).toHaveFocus()
    })

    it("returns focus to the fallback when the opener is gone, and to the opener when it is usable", () => {
        const fallback = document.createElement("button")
        document.body.appendChild(fallback)
        const { unmount } = render(<Harness returnFocusTo={() => fallback} />)
        const opener = screen.getByRole("button", { name: "Open it" })
        opener.focus()
        fireEvent.click(opener)
        fireEvent.click(screen.getByRole("button", { name: "Close it", hidden: true }))
        // Usable opener: it wins over the fallback.
        expect(opener).toHaveFocus()
        // Opener unusable by the time the dialog closes: the fallback is used.
        opener.focus()
        fireEvent.click(opener)
        opener.setAttribute("disabled", "")
        fireEvent.click(screen.getByRole("button", { name: "Close it", hidden: true }))
        expect(fallback).toHaveFocus()
        unmount()
        fallback.remove()
    })

    it("leaves focus alone when there is no fallback to go to", () => {
        render(<Harness returnFocusTo={() => null} />)
        const opener = screen.getByRole("button", { name: "Open it" })
        opener.focus()
        fireEvent.click(opener)
        opener.setAttribute("disabled", "")
        fireEvent.click(screen.getByRole("button", { name: "Close it", hidden: true }))
        expect(opener).not.toHaveFocus()
    })

    it("hands Escape to the page while a question is shown, even when a request is pending", () => {
        const onDismiss = vi.fn()
        const prompt: FormDialogPrompt = {
            message: "Leave?",
            keepLabel: "Stay",
            confirmLabel: "Leave",
            onKeep: vi.fn(),
            onConfirm: vi.fn(),
        }
        render(<Harness onDismiss={onDismiss} pending prompt={prompt} />)
        fireEvent.click(screen.getByRole("button", { name: "Open it" }))
        escape(screen.getByRole("dialog", { name: "Record a thing" }))
        expect(onDismiss).toHaveBeenCalledTimes(1)
    })

    describe("choosing where focus goes on closing", () => {
        // An opener outside React's tree: focus it, open the dialog without moving focus, let `change` run
        // (the page changing under the dialog), close, and report where focus is.
        function closeAfter(
            make: () => { opener: HTMLElement; mount?: HTMLElement },
            change: (opener: HTMLElement) => void,
            fallback: HTMLElement | null,
        ) {
            const { opener, mount } = make()
            document.body.appendChild(mount ?? opener)
            opener.focus()
            render(<Harness returnFocusTo={() => fallback} />)
            fireEvent.click(screen.getByRole("button", { name: "Open it" }))
            change(opener)
            fireEvent.click(screen.getByRole("button", { name: "Close it", hidden: true }))
            return opener
        }
        const made: HTMLElement[] = []
        const element = (tag: string, attributes: Record<string, string> = {}) => {
            const node = document.createElement(tag)
            for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value)
            made.push(node)
            return node
        }
        const fallbackButton = () => {
            const button = element("button")
            document.body.appendChild(button)
            return button
        }
        afterEach(() => {
            cleanup()
            while (made.length > 0) made.pop()!.remove()
        })

        it("uses the fallback for a CSS-hidden opener", () => {
            const fallback = fallbackButton()
            closeAfter(() => ({ opener: element("button") }), (opener) => (opener.style.display = "none"), fallback)
            expect(fallback).toHaveFocus()
        })

        it("uses the fallback for an opener inside a CSS-hidden ancestor", () => {
            const fallback = fallbackButton()
            const wrapper = element("div")
            const opener = element("button")
            wrapper.appendChild(opener)
            closeAfter(() => ({ opener, mount: wrapper }), () => (wrapper.style.display = "none"), fallback)
            expect(fallback).toHaveFocus()
        })

        it("uses the fallback for a visibility:hidden opener", () => {
            const fallback = fallbackButton()
            closeAfter(() => ({ opener: element("button") }), (opener) => (opener.style.visibility = "hidden"), fallback)
            expect(fallback).toHaveFocus()
        })

        it("uses the fallback for an opener inside an inert ancestor", () => {
            const fallback = fallbackButton()
            const wrapper = element("div")
            const opener = element("button")
            wrapper.appendChild(opener)
            closeAfter(() => ({ opener, mount: wrapper }), () => wrapper.setAttribute("inert", ""), fallback)
            expect(fallback).toHaveFocus()
        })

        it("uses the fallback for an opener that stopped being focusable (tabindex removed)", () => {
            const fallback = fallbackButton()
            closeAfter(
                () => ({ opener: element("div", { tabindex: "0" }) }),
                (opener) => opener.removeAttribute("tabindex"),
                fallback,
            )
            expect(fallback).toHaveFocus()
        })

        it("accepts tabindex=-1 as a valid programmatic target, for the opener and for the fallback", () => {
            const fallback = fallbackButton()
            const opener = closeAfter(() => ({ opener: element("div", { tabindex: "-1" }) }), () => {}, fallback)
            expect(opener).toHaveFocus()
        })

        it("accepts a tabindex=-1 fallback", () => {
            const target = element("div", { tabindex: "-1" })
            document.body.appendChild(target)
            const opener = closeAfter(() => ({ opener: element("button") }), (node) => node.setAttribute("disabled", ""), target)
            expect(opener).not.toHaveFocus()
            expect(target).toHaveFocus()
        })

        it("tries the fallback when focusing the original opener did not take", () => {
            const fallback = fallbackButton()
            const opener = element("button")
            const attempt = vi.fn()
            opener.focus = attempt
            closeAfter(() => ({ opener }), () => {}, fallback)
            expect(attempt).toHaveBeenCalledTimes(1)
            expect(fallback).toHaveFocus()
        })

        it("leaves focus where the user deliberately moved it", () => {
            const fallback = fallbackButton()
            const elsewhere = fallbackButton()
            const opener = closeAfter(() => ({ opener: element("button") }), () => elsewhere.focus(), fallback)
            expect(elsewhere).toHaveFocus()
            expect(opener).not.toHaveFocus()
            expect(fallback).not.toHaveFocus()
        })

        it("never focuses a control inside the closed dialog", () => {
            render(<Harness returnFocusTo={() => document.querySelector<HTMLElement>("dialog button")} />)
            const inside = document.querySelector<HTMLElement>("dialog button")!
            const attempt = vi.spyOn(inside, "focus")
            const opener = screen.getByRole("button", { name: "Open it" })
            opener.setAttribute("disabled", "")
            fireEvent.click(opener)
            fireEvent.click(screen.getByRole("button", { name: "Close it", hidden: true }))
            expect(attempt).not.toHaveBeenCalled()
        })
    })

    it("does not move focus to the fallback merely because it was mounted closed", () => {
        const fallback = document.createElement("button")
        document.body.appendChild(fallback)
        render(<Harness returnFocusTo={() => fallback} />)
        expect(fallback).not.toHaveFocus()
        fallback.remove()
    })
})
