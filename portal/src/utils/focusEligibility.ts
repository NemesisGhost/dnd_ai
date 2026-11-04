// Elements the platform can focus (tabindex="-1" included: it is still a valid programmatic target).
const FOCUSABLE =
    'a[href], area[href], button, input:not([type="hidden"]), select, textarea, summary, iframe, [contenteditable]:not([contenteditable="false"]), [tabindex]'

// Whether `element` can take focus back now: in the document and outside `closedDialog`, not disabled, not
// inert or hidden (itself or through an ancestor: [hidden], [inert], display:none, visibility:hidden), and
// something that can be focused at all. Style is read from computed style, not from layout measurements.
// Shared by every modal that returns focus (FormDialog, ConfirmDialog) so they agree on "usable".
export function canTakeFocus(element: Element | null, closedDialog: HTMLElement | null = null): element is HTMLElement {
    if (!(element instanceof HTMLElement) || element === document.body || !element.isConnected) return false
    if (closedDialog?.contains(element) === true) return false
    if (element.closest("[inert], [hidden]") !== null || element.matches(":disabled")) return false
    if (!element.matches(FOCUSABLE)) return false
    if (getComputedStyle(element).visibility === "hidden") return false
    for (let node: HTMLElement | null = element; node !== null; node = node.parentElement) {
        if (getComputedStyle(node).display === "none") return false
    }
    return true
}

// The element that holds focus outside `dialog` and is not `opener`: focus that already moved onto something on
// the page (an accepted navigation's destination heading, or a control the person chose), which closing the
// dialog must not take back. Read BEFORE `dialog.close()`: a native modal close restores focus to the element
// that was focused before showModal() (the surviving opener), after which that evidence is gone. Null when focus
// is in the dialog, nowhere, or on the opener. Close reason is deliberately not consulted; focus ownership is.
export function focusHeldOutside(dialog: HTMLElement, opener: Element | null): HTMLElement | null {
    const current = document.activeElement
    if (!(current instanceof HTMLElement) || current === document.body || current === opener || dialog.contains(current)) return null
    return current
}

// Put focus back on `held` after a native close that may have moved it to the opener. True when `held` has focus
// (already, or restored because it is still usable); false when it is gone, hidden or inert, in which case the
// caller falls back to the opener as for any other close.
export function keepHeldFocus(held: HTMLElement | null, closedDialog: HTMLElement): boolean {
    if (held === null) return false
    return document.activeElement === held || restoreFocus(held, closedDialog)
}

// Focus `element` if it is eligible; whether focus actually arrived there.
export function restoreFocus(element: Element | null | undefined, closedDialog: HTMLElement): boolean {
    if (!canTakeFocus(element ?? null, closedDialog)) return false
    ;(element as HTMLElement).focus()
    return document.activeElement === element
}
