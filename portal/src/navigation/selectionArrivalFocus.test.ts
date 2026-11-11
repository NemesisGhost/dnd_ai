import { afterEach, describe, expect, it } from "vitest"
import { activationFor, bindActivation, releaseActivation } from "./activationOwner"
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
// An arrival accepted at location "k"; `origin` is the control the accepted request bound to that location.
const arrival = (origin: HTMLElement | null, key = "k") => {
    if (origin !== null) bindActivation(key, origin)
    return new SelectionArrival(
        { level: "campaign", id: "beta" },
        { campaignId: "beta", worldId: null },
        { key, pathname: "/app/beta/home", search: "", hash: "", state: null },
        null,
    )
}

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

describe("activation handoff", () => {
    it("is bound to the location the request was accepted at: an unrelated arrival at the same path gets nothing", () => {
        const { activated, h1 } = page()
        bindActivation("accepted-key", activated)
        activated.focus()

        // Another arrival (same pathname, different location key) does not own the control.
        new SelectionArrival(
            { level: "campaign", id: "beta" },
            { campaignId: "beta", worldId: null },
            { key: "unrelated-key", pathname: "/app/beta/home", search: "", hash: "", state: null },
            null,
        ).focusHeading("unrelated-key")
        expect(h1).not.toHaveFocus()
        expect(activated).toHaveFocus()
        expect(activationFor("accepted-key")).toBe(activated)
    })

    it("is used up with the focus claim and can be released", () => {
        const { activated, h1 } = page()
        activated.focus()
        arrival(activated, "k1").focusHeading("k1")
        expect(h1).toHaveFocus()
        expect(activationFor("k1")).toBeNull()

        bindActivation("k2", activated)
        releaseActivation("k2")
        expect(activationFor("k2")).toBeNull()
    })

    it("is bounded", () => {
        const { activated } = page()
        for (let index = 0; index < 10; index += 1) bindActivation(`bound-${index}`, activated)
        expect(activationFor("bound-0")).toBeNull()
        expect(activationFor("bound-9")).toBe(activated)
    })
})
