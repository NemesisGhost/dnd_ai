// Models what a browser does when a modal <dialog> closes, which jsdom does not implement: showModal() records the
// element that was focused, and close() hands focus back to it if it is still connected, whatever holds focus then
// (HTML "dialog close" steps with wasModal true). This is modeled evidence of that rule, not a browser run.
// Install in a beforeEach and call the returned function in an afterEach.
export function installNativeDialogModel(): () => void {
    const proto = HTMLDialogElement.prototype as unknown as Record<string, unknown>
    const saved = { showModal: proto.showModal, close: proto.close }
    const previous = new WeakMap<HTMLDialogElement, Element | null>()
    proto.showModal = function (this: HTMLDialogElement) {
        previous.set(this, document.activeElement)
        this.setAttribute("open", "")
    }
    proto.close = function (this: HTMLDialogElement) {
        if (!this.hasAttribute("open")) return
        this.removeAttribute("open")
        const element = previous.get(this)
        previous.delete(this)
        if (element instanceof HTMLElement && element.isConnected) element.focus()
    }
    return () => {
        proto.showModal = saved.showModal
        proto.close = saved.close
    }
}
