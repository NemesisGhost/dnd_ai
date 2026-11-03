import { describe, expect, it } from "vitest"
import { NavigationAttempt, hrefOf } from "./navigationAttempt"
import type { AttemptLocation, AttemptView } from "./navigationAttempt"

// The contract of navigation/navigationAttempt.ts, one phase at a time and without a router.

const at = (key: string, path: string, state?: unknown): AttemptLocation => {
    const [pathname = "", rest = ""] = path.split("?")
    const [search, hash] = rest.split("#")
    return { key, pathname, search: search ? `?${search}` : "", hash: hash ? `#${hash}` : "", state }
}

const left = at("L", "/parties")
const WANTED = { pathname: "/quests", search: "?x=1", hash: "#top" }

function attempt() {
    return new NavigationAttempt(WANTED, { key: left.key, href: hrefOf(left) })
}

function view(overrides: Partial<AttemptView> = {}): AttemptView {
    return {
        location: left,
        action: "PUSH",
        navigating: null,
        blocked: null,
        proceeding: null,
        failed: false,
        ...overrides,
    }
}

const wanted = (key: string, state?: unknown) => at(key, "/quests?x=1#top", state)

describe("hrefOf", () => {
    it("is the whole destination without a trailing slash", () => {
        expect(hrefOf({ pathname: "/a/b/", search: "?q=1", hash: "#h" })).toBe("/a/b?q=1#h")
        expect(hrefOf({ pathname: "/", search: "", hash: "" })).toBe("/")
    })
})

describe("NavigationAttempt", () => {
    it("accepts the first commit of the full destination when nothing else was seen", () => {
        expect(attempt().observe(view({ location: wanted("N1"), action: "PUSH" }))).toBe("accepted")
        expect(attempt().observe(view({ location: wanted("N1"), action: "REPLACE" }))).toBe("accepted")
    })

    it("does not accept the same pathname with another query or hash, a POP, or another place", () => {
        expect(attempt().observe(view({ location: at("N1", "/quests?x=2#top") }))).toBe("cancelled")
        expect(attempt().observe(view({ location: at("N1", "/quests?x=1") }))).toBe("cancelled")
        expect(attempt().observe(view({ location: wanted("N1"), action: "POP" }))).toBe("cancelled")
        expect(attempt().observe(view({ location: at("N1", "/elsewhere") }))).toBe("cancelled")
    })

    it("ignores the stamp of the entry it left and goes on waiting", () => {
        const a = attempt()
        expect(a.observe(view({ location: at("S", "/parties"), action: "REPLACE" }))).toBe("pending")
        expect(a.observe(view({ location: wanted("N1") }))).toBe("accepted")
    })

    it("owns the request it saw in flight, and only that one", () => {
        const a = attempt()
        expect(a.observe(view({ navigating: wanted("F1") }))).toBe("pending")
        expect(a.observe(view({ location: wanted("F1") }))).toBe("accepted")

        const b = attempt()
        b.observe(view({ navigating: wanted("F1") }))
        // The same address committed under another key is someone else's navigation.
        expect(b.observe(view({ location: wanted("F2") }))).toBe("cancelled")

        const c = attempt()
        c.observe(view({ navigating: wanted("F1") }))
        expect(c.observe(view({ navigating: wanted("F2") }))).toBe("cancelled")
    })

    it("follows a redirect the router marks, in flight or committed unseen", () => {
        const a = attempt()
        a.observe(view({ navigating: wanted("F1") }))
        expect(a.observe(view({ navigating: at("F2", "/elsewhere", { _isRedirect: true }) }))).toBe("pending")
        expect(a.observe(view({ location: at("F2", "/elsewhere", { _isRedirect: true }) }))).toBe("accepted")

        const b = attempt()
        b.observe(view({ navigating: wanted("F1") }))
        expect(b.observe(view({ location: at("F9", "/elsewhere", { _isRedirect: true }) }))).toBe("accepted")

        // A POP to an entry that carries the mark is not a redirect of ours.
        const c = attempt()
        c.observe(view({ navigating: wanted("F1") }))
        expect(c.observe(view({ location: at("F9", "/elsewhere", { _isRedirect: true }), action: "POP" }))).toBe(
            "cancelled",
        )
    })

    it("cancels a navigation that fails or ends without arriving", () => {
        const a = attempt()
        a.observe(view({ navigating: wanted("F1") }))
        expect(a.observe(view({ location: wanted("F1"), failed: true }))).toBe("cancelled")

        const b = attempt()
        b.observe(view({ navigating: wanted("F1") }))
        expect(b.observe(view())).toBe("cancelled")
    })

    it("holds while the question is open, goes on after Leave, and cancels on Stay", () => {
        const asked = () => {
            const a = attempt()
            expect(a.observe(view({ blocked: wanted("B1") }))).toBe("pending")
            expect(a.observe(view({ blocked: wanted("B1") }))).toBe("pending")
            return a
        }

        const leave = asked()
        expect(leave.observe(view({ proceeding: wanted("B1") }))).toBe("pending")
        expect(leave.observe(view({ location: wanted("B2") }))).toBe("accepted")

        const leaveSlowly = asked()
        leaveSlowly.observe(view({ proceeding: wanted("B1") }))
        expect(leaveSlowly.observe(view({ navigating: wanted("B2") }))).toBe("pending")
        expect(leaveSlowly.observe(view({ location: wanted("B2") }))).toBe("accepted")

        expect(asked().observe(view())).toBe("cancelled")
    })

    it("cancels when a different request replaces the held one, or a commit arrives during the question", () => {
        const a = attempt()
        a.observe(view({ blocked: wanted("B1") }))
        expect(a.observe(view({ blocked: at("B2", "/elsewhere") }))).toBe("cancelled")

        const b = attempt()
        b.observe(view({ blocked: wanted("B1") }))
        expect(b.observe(view({ location: wanted("X"), action: "POP" }))).toBe("cancelled")

        const c = attempt()
        c.observe(view({ blocked: wanted("B1") }))
        c.observe(view({ proceeding: wanted("B1") }))
        // After Leave, a navigation somewhere else is not ours.
        expect(c.observe(view({ location: at("X", "/elsewhere") }))).toBe("cancelled")
    })

    it("stays settled once it has an answer", () => {
        const a = attempt()
        expect(a.observe(view({ location: wanted("N1") }))).toBe("accepted")
        expect(a.observe(view({ location: at("N2", "/else") }))).toBe("accepted")
    })
})
