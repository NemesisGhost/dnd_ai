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
    // Where focus goes on closing when the control that opened the dialog is gone, hidden or disabled
    // (a "Reopen" link that the page removes as it opens the dialog). Returns null when there is nowhere
    // to go, e.g. the page it belongs to has been left; focus is then left alone.
    returnFocusTo?: () => HTMLElement | null
    children: ReactNode
}

// Elements the platform can focus (tabindex="-1" included: it is still a valid programmatic target).
const FOCUSABLE =
    'a[href], area[href], button, input:not([type="hidden"]), select, textarea, summary, iframe, [contenteditable]:not([contenteditable="false"]), [tabindex]'

// Whether `element` can take focus back now: in the document and outside `closedDialog`, not disabled, not
// inert or hidden (itself or through an ancestor: [hidden], [inert], display:none, visibility:hidden), and
// something that can be focused at all. Style is read from computed style, not from layout measurements.
function canTakeFocus(element: Element | null, closedDialog: HTMLElement): element is HTMLElement {
    if (!(element instanceof HTMLElement) || element === document.body || !element.isConnected) return false
    if (closedDialog.contains(element)) return false
    if (element.closest("[inert], [hidden]") !== null || element.matches(":disabled")) return false
    if (!element.matches(FOCUSABLE)) return false
    if (getComputedStyle(element).visibility === "hidden") return false
    for (let node: HTMLElement | null = element; node !== null; node = node.parentElement) {
        if (getComputedStyle(node).display === "none") return false
    }
    return true
}

// Focus `element` if it is eligible; whether focus actually arrived there.
function restoreFocus(element: Element | null | undefined, closedDialog: HTMLElement): boolean {
    if (!canTakeFocus(element ?? null, closedDialog)) return false
    ;(element as HTMLElement).focus()
    return document.activeElement === element
}

// A modal that holds a form, built on the native <dialog> like ConfirmDialog (showModal supplies the
// focus trap and makes the page behind inert) but with the semantics a form needs:
//   - the children stay mounted while the dialog is closed, so a form's state (an unsent draft, or a
//     request whose outcome is unknown) belongs to the page that owns the dialog, not to its visibility;
//   - a click on the backdrop does nothing, so a touch cannot lose what was typed;
//   - Escape asks the page (`onDismiss`) and is ignored while a request is pending;
//   - a confirmation (`prompt`) is shown inside the dialog, never as a second modal.
// Focus enters the first control when it opens and returns to the control that opened it when it closes
// (or to `returnFocusTo` when that control is no longer usable). Escape while a question is shown is
// passed to the page, which answers it with the safe choice; a pending request only blocks dismissal.
export function FormDialog({
    open,
    title,
    description,
    onDismiss,
    pending = false,
    prompt = null,
    returnFocusTo,
    children,
}: FormDialogProps) {
    const fallbackRef = useRef(returnFocusTo)
    useEffect(() => {
        fallbackRef.current = returnFocusTo
    }, [returnFocusTo])
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
        // Focus that has already moved to something on the page (not the dialog, not nowhere) is left alone.
        const active = document.activeElement
        if (active !== null && active !== document.body && !dialog.contains(active)) return
        if (!restoreFocus(target, dialog)) restoreFocus(fallbackRef.current?.(), dialog)
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
                // Answering a question is never a dismissal, so it is allowed while a request is pending.
                if (!pending || asking) onDismiss()
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
