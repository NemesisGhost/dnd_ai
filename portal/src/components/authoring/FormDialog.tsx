import { useEffect, useId, useRef } from "react"
import type { ReactNode } from "react"
import "./authoring.css"

// A question asked inside the dialog, in place of stacking a second modal on it.
export interface FormDialogPrompt {
    message: string
    keepLabel: string
    confirmLabel: string
    // Return to the form, with what was entered intact.
    onKeep: () => void
    onConfirm: () => void
}

interface FormDialogProps {
    open: boolean
    title: string
    // Announced as the dialog's description.
    description: string
    // Escape (and a Cancel the form wires itself). Ignored while `pending`.
    onDismiss: () => void
    // A request is in flight: the dialog must not be dismissed.
    pending?: boolean
    // When set it replaces the form (which stays mounted, with its values) until answered.
    prompt?: FormDialogPrompt | null
    children: ReactNode
}

// A modal that holds a form, built on the native <dialog> like ConfirmDialog (showModal supplies the
// focus trap and makes the page behind inert) but with the semantics a form needs:
//   - the children stay mounted while the dialog is closed, so a form's state (an unsent draft, or a
//     request whose outcome is unknown) belongs to the page that owns the dialog, not to its visibility;
//   - a click on the backdrop does nothing, so a touch cannot lose what was typed;
//   - Escape asks the page (`onDismiss`) and is ignored while a request is pending;
//   - a confirmation (`prompt`) is shown inside the dialog, never as a second modal.
// Focus enters the first control when it opens and returns to the control that opened it when it closes.
export function FormDialog({ open, title, description, onDismiss, pending = false, prompt = null, children }: FormDialogProps) {
    const dialogRef = useRef<HTMLDialogElement>(null)
    const keepRef = useRef<HTMLButtonElement>(null)
    const returnFocusRef = useRef<Element | null>(null)
    const beforePromptRef = useRef<Element | null>(null)
    const titleId = useId()
    const descriptionId = useId()
    const asking = prompt !== null

    useEffect(() => {
        const dialog = dialogRef.current
        if (dialog === null) return
        if (open) {
            returnFocusRef.current = document.activeElement
            if (typeof dialog.showModal === "function") {
                if (!dialog.open) dialog.showModal()
            } else {
                dialog.setAttribute("open", "")
            }
            dialog.querySelector<HTMLElement>("input, select, textarea")?.focus()
            return
        }
        if (typeof dialog.close === "function") {
            if (dialog.open) dialog.close()
        } else {
            dialog.removeAttribute("open")
        }
        const target = returnFocusRef.current
        returnFocusRef.current = null
        if (target instanceof HTMLElement && target.isConnected) target.focus()
    }, [open])

    // The question takes focus on its safe answer, and the form gets its place back when it is answered.
    useEffect(() => {
        if (asking) {
            beforePromptRef.current = document.activeElement
            keepRef.current?.focus()
            return
        }
        const target = beforePromptRef.current
        beforePromptRef.current = null
        if (target instanceof HTMLElement && target.isConnected && dialogRef.current?.contains(target)) {
            target.focus()
        }
    }, [asking])

    return (
        <dialog
            ref={dialogRef}
            className="authoring-dialog authoring-dialog--form"
            aria-labelledby={titleId}
            aria-describedby={descriptionId}
            onCancel={(event) => {
                // Escape: the page decides (a request may be in flight, or input may be unsaved).
                event.preventDefault()
                if (!pending) onDismiss()
            }}
        >
            <div className="authoring-dialog__body">
                <h2 id={titleId}>{title}</h2>
                <p id={descriptionId}>{description}</p>
                <div inert={asking} hidden={asking}>
                    {children}
                </div>
                {prompt !== null ? (
                    <div role="group" aria-label="Confirm" className="authoring-dialog__prompt">
                        <p>{prompt.message}</p>
                        <div className="authoring-actions">
                            <button ref={keepRef} type="button" className="authoring-button" onClick={prompt.onKeep}>
                                {prompt.keepLabel}
                            </button>
                            <button type="button" className="authoring-button authoring-button--danger" onClick={prompt.onConfirm}>
                                {prompt.confirmLabel}
                            </button>
                        </div>
                    </div>
                ) : null}
            </div>
        </dialog>
    )
}
