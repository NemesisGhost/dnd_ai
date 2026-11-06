import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"

// P02 browser acceptance B16: at a 320 CSS px viewport (and at 400% zoom) a vertical scrollbar leaves the
// root 305 or 316 CSS px wide. A `min-width: 320px` on `body` is then wider than the root and scrolls the
// page sideways. jsdom does no layout, so this guards the rule itself; the width is a browser check.
describe("document width", () => {
    it("sets no minimum width on html, body or #root", () => {
        const css = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "")
        const rules = [...css.matchAll(/([^{}]+)\{([^}]*)\}/g)]
        const offenders = rules
            .filter(([, selector]) => /^(html|body|#root)(\s*,\s*(html|body|#root))*\s*$/.test(selector!.trim()))
            .filter(([, , body]) => /(^|;)\s*min-width\s*:/.test(body!))
        expect(offenders.map((match) => match[1]!.trim())).toEqual([])
    })
})
