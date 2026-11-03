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

// Focus `element` if it is eligible; whether focus actually arrived there.
export function restoreFocus(element: Element | null | undefined, closedDialog: HTMLElement): boolean {
    if (!canTakeFocus(element ?? null, closedDialog)) return false
    ;(element as HTMLElement).focus()
    return document.activeElement === element
}
