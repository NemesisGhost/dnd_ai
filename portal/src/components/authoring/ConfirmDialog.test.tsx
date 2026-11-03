import { fireEvent, render, screen } from "@testing-library/react"
import { useEffect, useState } from "react"
import { describe, expect, it, vi } from "vitest"
import { registerFocusFallback } from "../../hooks/navigationHolds"
import { ConfirmDialog } from "./ConfirmDialog"

function Harness({ onConfirm = vi.fn(), error }: { onConfirm?: () => void; error?: string }) {
    const [open, setOpen] = useState(false)
    return (
        <>
            <button type="button" onClick={() => setOpen(true)}>
                Archive world
            </button>
            <ConfirmDialog
                open={open}
                title="Archive this world?"
                description="It becomes read-only."
                confirmLabel="Archive it"
                onConfirm={onConfirm}
                onCancel={() => setOpen(false)}
                error={error ? <p role="alert">{error}</p> : null}
            />
        </>
    )
}

describe("ConfirmDialog", () => {
    it("is labelled and described, and puts initial focus on Cancel", () => {
        render(<Harness />)
        fireEvent.click(screen.getByRole("button", { name: "Archive world" }))

        const dialog = screen.getByRole("dialog", { name: "Archive this world?", hidden: true })
        expect(dialog).toHaveAccessibleDescription("It becomes read-only.")
        expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus()
    })

    it("labels the destructive action with its verb", () => {
        render(<Harness />)
        fireEvent.click(screen.getByRole("button", { name: "Archive world" }))
        expect(screen.getByRole("button", { name: "Archive it" })).toBeInTheDocument()
    })

    it("returns focus to the control that opened it when cancelled", () => {
        render(<Harness />)
        const opener = screen.getByRole("button", { name: "Archive world" })
        opener.focus()
        fireEvent.click(opener)
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        expect(opener).toHaveFocus()
    })

    describe("when the control that had focus is no longer usable (navigation focus fallbacks)", () => {
        function Fallbacks({ candidates }: { candidates: Array<[number, () => HTMLElement | null]> }) {
            useEffect(() => {
                const releases = candidates.map(([priority, resolve]) => registerFocusFallback(priority, resolve))
                return () => releases.forEach((release) => release())
            }, [candidates])
            return null
        }

        it("tries the candidates nearest first, and skips hidden or removed ones", () => {
            const near = document.createElement("button")
            near.hidden = true
            const opener = document.createElement("button")
            const far = document.createElement("button")
            document.body.append(near, opener, far)
            render(
                <>
                    <Fallbacks
                        candidates={[
                            [2, () => far],
                            [0, () => near],
                            [1, () => opener],
                        ]}
                    />
                    <Harness />
                </>,
            )
            // Nothing usable holds focus when the dialog opens (the opener never took it).
            fireEvent.click(screen.getByRole("button", { name: "Archive world" }))
            ;(document.activeElement as HTMLElement).blur()
            // The control that opened it is gone from the user's reach too.
            screen.getByRole("button", { name: "Archive world" }).hidden = true

            fireEvent.click(screen.getByRole("button", { name: "Cancel" }))

            // The hidden nearest candidate is skipped; the next usable one takes focus; the farther is untouched.
            expect(opener).toHaveFocus()
            expect(far).not.toHaveFocus()
            near.remove()
            opener.remove()
            far.remove()
        })

        it("leaves focus alone when its first choice is usable, whatever candidates exist", () => {
            const candidate = document.createElement("button")
            document.body.append(candidate)
            render(
                <>
                    <Fallbacks candidates={[[0, () => candidate]]} />
                    <Harness />
                </>,
            )
            const opener = screen.getByRole("button", { name: "Archive world" })
            opener.focus()
            fireEvent.click(opener)
            fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
            expect(opener).toHaveFocus()
            candidate.remove()
        })

        it("uses the candidates it saw when it opened, even if they are released as it closes", () => {
            const candidate = document.createElement("button")
            document.body.append(candidate)
            const candidates: Array<[number, () => HTMLElement | null]> = [[0, () => candidate]]
            const { rerender } = render(
                <>
                    <Fallbacks candidates={candidates} />
                    <Harness />
                </>,
            )
            fireEvent.click(screen.getByRole("button", { name: "Archive world" }))
            ;(document.activeElement as HTMLElement).blur()
            screen.getByRole("button", { name: "Archive world" }).hidden = true
            // The owner of the candidate releases it (its navigation was answered Stay) before the dialog closes.
            rerender(
                <>
                    {null}
                    <Harness />
                </>,
            )
            fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
            expect(candidate).toHaveFocus()
            candidate.remove()
        })
    })

    it("cancels on Escape", () => {
        render(<Harness />)
        fireEvent.click(screen.getByRole("button", { name: "Archive world" }))
        const dialog = screen.getByRole("dialog", { hidden: true })
        fireEvent(dialog, new Event("cancel", { cancelable: true }))
        expect(screen.queryByRole("button", { name: "Archive it" })).not.toBeInTheDocument()
    })

    it("keeps a failure inside the open dialog", () => {
        render(<Harness error="Could not archive" />)
        fireEvent.click(screen.getByRole("button", { name: "Archive world" }))
        expect(screen.getByRole("alert")).toHaveTextContent("Could not archive")
        expect(screen.getByRole("button", { name: "Archive it" })).toBeInTheDocument()
    })

    it("confirms through the callback", () => {
        const onConfirm = vi.fn()
        render(<Harness onConfirm={onConfirm} />)
        fireEvent.click(screen.getByRole("button", { name: "Archive world" }))
        fireEvent.click(screen.getByRole("button", { name: "Archive it" }))
        expect(onConfirm).toHaveBeenCalledTimes(1)
    })

    it("disables both actions and shows progress while pending", () => {
        render(
            <ConfirmDialog
                open
                title="T"
                description="D"
                confirmLabel="Go"
                onConfirm={() => {}}
                onCancel={() => {}}
                pending
            />,
        )
        expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled()
        expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled()
    })

    it("shows a labelled reason field and reports edits", () => {
        const onChange = vi.fn()
        render(
            <ConfirmDialog
                open
                title="T"
                description="D"
                confirmLabel="Go"
                onConfirm={() => {}}
                onCancel={() => {}}
                reason={{ label: "Reason", required: true, value: "", onChange, error: "A reason is required." }}
            />,
        )
        const reason = screen.getByRole("textbox", { name: /Reason/ })
        expect(reason).toHaveAttribute("aria-invalid", "true")
        fireEvent.change(reason, { target: { value: "because" } })
        expect(onChange).toHaveBeenCalledWith("because")
    })
})
