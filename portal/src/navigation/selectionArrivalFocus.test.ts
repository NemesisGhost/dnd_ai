import { afterEach, describe, expect, it } from "vitest"
import { claimActivation, recordActivation, releaseActivation } from "./activationOwner"
import { SelectionArrival } from "./selectionArrival"

// Which focus a settled destination may take its heading from (docs/UI_DESIGN.md §4.8.4): nowhere, the
// Infobox, or the very control the navigation was requested with; never some other control.

afterEach(() => {
    document.body.innerHTML = ""
})

function page() {
    document.body.innerHTML = [
        '<nav><a id="activated" href="#a">Campaign beta</a><a id="other" href="#b">Campaign gamma</a></nav>',
        '<div class="campaign-context-panel"><select id="infobox"></select></div>',
        '<div class="campaign-workspace__content"><h1>Campaign Home</h1></div>',
    ].join("")
    return {
        activated: document.getElementById("activated")!,
        other: document.getElementById("other")!,
        infobox: document.getElementById("infobox")!,
        h1: document.querySelector("h1")!,
    }
}
const arrival = (origin: HTMLElement | null) =>
    new SelectionArrival(
        { level: "campaign", id: "beta" },
        { campaignId: "beta", worldId: null },
        { key: "k", pathname: "/app/beta/home", search: "", hash: "", state: null },
        null,
        origin,
    )

describe("SelectionArrival.focusHeading", () => {
    it("takes focus from the control the navigation was requested with", () => {
        const { activated, h1 } = page()
        activated.focus()
        arrival(activated).focusHeading("k")
        expect(h1).toHaveFocus()
    })

    it("does not take focus from another menu link", () => {
        const { activated, other, h1 } = page()
        other.focus()
        arrival(activated).focusHeading("k")
        expect(other).toHaveFocus()
        expect(h1).not.toHaveFocus()
    })

    it("without an owner, a menu link keeps its focus; the Infobox and nowhere do not", () => {
        const { activated, infobox, h1 } = page()
        activated.focus()
        arrival(null).focusHeading("k")
        expect(activated).toHaveFocus()

        infobox.focus()
        arrival(null).focusHeading("k")
        expect(h1).toHaveFocus()
    })
})

describe("activation owner", () => {
    it("is claimed once, for the address it was recorded for", () => {
        const { activated } = page()
        recordActivation(activated, "/app/beta/home")
        expect(claimActivation("/app/gamma/home")).toBeNull()
        expect(claimActivation("/app/beta/home")).toBe(activated)
        expect(claimActivation("/app/beta/home")).toBeNull()
    })

    it("a request that ended (Stay, superseded, failed) leaves nothing to claim; a newer one replaces an older", () => {
        const { activated, other } = page()
        recordActivation(activated, "/app/beta/home")
        releaseActivation(activated)
        expect(claimActivation("/app/beta/home")).toBeNull()

        recordActivation(activated, "/app/beta/home")
        recordActivation(other, "/app/gamma/home")
        releaseActivation(activated)
        expect(claimActivation("/app/beta/home")).toBeNull()
        expect(claimActivation("/app/gamma/home")).toBe(other)
    })
})
