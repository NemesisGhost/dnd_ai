import { useEffect, useId, useRef } from "react"
import type { ReactNode } from "react"
import { TextAreaField } from "./fields"
import "./authoring.css"

export interface ConfirmReason {
    label: string
    required: boolean
    value: string
    onChange: (value: string) => void
    error?: string | null
}

interface ConfirmDialogProps {
    open: boolean
    title: string
    // The consequence, stated plainly; announced as the dialog's description.
    description: string
    // The destructive action is labelled with its verb ("Archive world").
    confirmLabel: string
    onConfirm: () => void
    onCancel: () => void
    pending?: boolean
    // A failure stays inside the dialog; it closes only on success.
    error?: ReactNode
    reason?: ConfirmReason
    cancelLabel?: string
    // Extra content between the description and the reason (e.g. a chooser).
    children?: ReactNode
    // Disables the confirm button until something is chosen.
    confirmDisabled?: boolean
}

// A modal confirmation built on the native <dialog>: showModal() supplies the
// focus trap and Escape handling. Initial focus is Cancel (the safe choice),
// focus returns to the control that opened it, and an optional reason field is
// shown for actions that require one. The dialog is closed by the page only
// after the action succeeds, so errors render in place.
export function ConfirmDialog({
    open,
    title,
    description,
    confirmLabel,
    onConfirm,
    onCancel,
    pending = false,
    error,
    reason,
    cancelLabel = "Cancel",
    children,
    confirmDisabled = false,
}: ConfirmDialogProps) {
    const dialogRef = useRef<HTMLDialogElement>(null)
    const cancelRef = useRef<HTMLButtonElement>(null)
    const returnFocusRef = useRef<Element | null>(null)
    const titleId = useId()
    const descriptionId = useId()

    useEffect(() => {
        const dialog = dialogRef.current
        if (dialog === null) {
            return
        }
        if (open) {
            returnFocusRef.current = document.activeElement
            if (typeof dialog.showModal === "function") {
                if (!dialog.open) {
                    dialog.showModal()
                }
            } else {
                dialog.setAttribute("open", "")
            }
            cancelRef.current?.focus()
            return
        }
        if (typeof dialog.close === "function") {
            if (dialog.open) {
                dialog.close()
            }
        } else {
            dialog.removeAttribute("open")
        }
        const target = returnFocusRef.current
        returnFocusRef.current = null
        if (target instanceof HTMLElement && target.isConnected) {
            target.focus()
        }
    }, [open])

    return (
        <dialog
            ref={dialogRef}
            className="authoring-dialog"
            aria-labelledby={titleId}
            aria-describedby={descriptionId}
            onCancel={(event) => {
                // Escape: let the page decide (it may be mid-request).
                event.preventDefault()
                if (!pending) {
                    onCancel()
                }
            }}
        >
            {open ? (
                <div className="authoring-dialog__body">
                    <h2 id={titleId}>{title}</h2>
                    <p id={descriptionId}>{description}</p>
                    {children}
                    {reason ? (
                        <TextAreaField
                            label={reason.label}
                            value={reason.value}
                            onChange={reason.onChange}
                            error={reason.error}
                            required={reason.required}
                            maxLength={1000}
                            rows={3}
                        />
                    ) : null}
                    {error}
                    <div className="authoring-actions">
                        <button
                            type="button"
                            className="authoring-button authoring-button--danger"
                            onClick={onConfirm}
                            disabled={pending || confirmDisabled}
                            aria-busy={pending}
                        >
                            {pending ? "Working…" : confirmLabel}
                        </button>
                        <button
                            ref={cancelRef}
                            type="button"
                            className="authoring-button"
                            onClick={onCancel}
                            disabled={pending}
                        >
                            {cancelLabel}
                        </button>
                    </div>
                </div>
            ) : null}
        </dialog>
    )
}
