import { fireEvent, render, screen } from "@testing-library/react"
import { useEffect, useState } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { registerFocusFallback } from "../../hooks/navigationHolds"
import { installNativeDialogModel } from "../../test/nativeDialog"
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

    it("does not take focus back from something live that took it while the dialog was open or as it closed", () => {
        render(
            <>
                <Harness />
                <button type="button">Destination</button>
            </>,
        )
        const opener = screen.getByRole("button", { name: "Archive world" })
        opener.focus()
        fireEvent.click(opener)
        // As an accepted navigation does: the destination takes focus in the same step the dialog closes.
        const destination = screen.getByRole("button", { name: "Destination" })
        destination.focus()
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        expect(destination).toHaveFocus()
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

    // jsdom does not implement the native close; this models its focus rule (showModal records the focused
    // element, close() hands focus back to it if connected, whoever holds focus). Modeled evidence, not a browser run.
    describe("when native close restores focus to the element focused before showModal()", () => {
        let uninstall: () => void
        beforeEach(() => {
            uninstall = installNativeDialogModel()
        })
        afterEach(() => uninstall())

        function Closing({ onClosed }: { onClosed?: () => void }) {
            const [open, setOpen] = useState(false)
            const close = () => {
                setOpen(false)
                onClosed?.()
            }
            return (
                <>
                    <button type="button" onClick={() => setOpen(true)}>
                        Open question
                    </button>
                    <button type="button">Destination</button>
                    <button type="button">Elsewhere</button>
                    <ConfirmDialog
                        open={open}
                        title="Discard?"
                        description="unsent"
                        confirmLabel="Leave"
                        cancelLabel="Stay"
                        onConfirm={close}
                        onCancel={close}
                    />
                </>
            )
        }
        const button = (name: string) => screen.getByRole("button", { name })
        const ask = () => {
            const opener = button("Open question")
            opener.focus()
            fireEvent.click(opener)
            return opener
        }

        it("Leave: a destination that took focus before the close keeps it", () => {
            render(<Closing />)
            const opener = ask()
            button("Destination").focus()

            fireEvent.click(button("Leave"))

            expect(button("Destination")).toHaveFocus()
            expect(opener).not.toHaveFocus()
        })

        it("Leave: the opener gets focus at close, and a destination that arrives afterwards keeps it", () => {
            render(<Closing />)
            const opener = ask()

            fireEvent.click(button("Leave"))
            expect(opener).toHaveFocus()

            button("Destination").focus()
            expect(button("Destination")).toHaveFocus()
        })

        it("Stay and Escape return focus to the usable opener", () => {
            render(<Closing />)
            const opener = ask()
            fireEvent.click(button("Stay"))
            expect(opener).toHaveFocus()

            opener.focus()
            fireEvent.click(opener)
            fireEvent(screen.getByRole("dialog", { hidden: true }), new Event("cancel", { cancelable: true }))
            expect(opener).toHaveFocus()
        })

        it("uses the registered fallback when the opener is hidden, though the native close tried it first", () => {
            const fallback = document.createElement("button")
            document.body.append(fallback)
            const Fallback = () => {
                useEffect(() => registerFocusFallback(0, () => fallback), [])
                return null
            }
            render(
                <>
                    <Fallback />
                    <Closing />
                </>,
            )
            const opener = ask()
            opener.hidden = true

            fireEvent.click(button("Stay"))

            expect(fallback).toHaveFocus()
            fallback.remove()
        })

        it("a control the person moved focus to is not taken back", () => {
            render(<Closing />)
            ask()
            button("Elsewhere").focus()

            fireEvent.click(button("Stay"))

            expect(button("Elsewhere")).toHaveFocus()
        })

        it("a held control that is gone or hidden by the close falls back to the opener", () => {
            render(<Closing />)
            const opener = ask()
            const destination = button("Destination")
            destination.focus()
            destination.hidden = true

            fireEvent.click(button("Leave"))

            expect(opener).toHaveFocus()
        })

        it("unmounting while open, or a removed opener, restores nothing stale", () => {
            const { unmount } = render(<Closing />)
            ask()
            expect(() => unmount()).not.toThrow()
            expect(document.body).toHaveFocus()

            render(<Closing />)
            const opener = ask()
            const parent = opener.parentElement as HTMLElement
            opener.remove()
            fireEvent.click(button("Stay"))
            expect(document.body).toHaveFocus()
            parent.prepend(opener)
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
