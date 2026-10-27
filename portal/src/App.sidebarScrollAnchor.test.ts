/// <reference types="node" />
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"

// CP-4 smoke D-7. An open sidebar group (the Access submenu is open on its own routes) closes on any
// outside press and the sidebar shrinks by the group's height. With scroll anchoring on, Chrome then
// scrolls the page by that height between pointerdown and click, so a control far down a long page
// (the Sharing page's "Transfer ownership…") is not under the pointer when the button is released.
// jsdom has no layout, so this pins the one declaration that stops it; the behaviour itself was
// observed and fixed in real Chrome (see docs/SCOPED_ROLE_INTEGRATION_VERIFICATION.md).
describe("sidebar scroll anchoring", () => {
    it("excludes the sidebar from scroll anchoring, and only the sidebar", () => {
        const css = readFileSync(resolve(process.cwd(), "src/App.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "")
        const rule = /\.portal-sidebar\s*\{([^}]*)\}/.exec(css)
        expect(rule).not.toBeNull()
        expect(rule![1]).toMatch(/overflow-anchor:\s*none/)
        const everywhere = [...css.matchAll(/([^{}]+)\{[^}]*overflow-anchor:\s*none[^}]*\}/g)].map((m) => m[1]!.trim())
        expect(everywhere).toEqual([".portal-sidebar"])
    })
})
