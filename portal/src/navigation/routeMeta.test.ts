import { Children, isValidElement } from "react"
import type { ReactElement, ReactNode } from "react"
import { createRoutesFromChildren } from "react-router"
import type { RouteObject } from "react-router"
import { describe, expect, it } from "vitest"
import App from "../App"
import {
    NAV_ROOTS,
    ROUTE_METAS,
    defaultAncestors,
    executionScopeOf,
    matchRouteMeta,
    patternParams,
    routeMetaById,
    viewedRecordOf,
} from "./routeMeta"

// The production route inventory comes from App.tsx itself: App is a function component without hooks,
// so calling it returns its element tree, and react-router's own `createRoutesFromChildren` reads the
// <Routes> it contains. There is no second, hand-kept route table in this test.
function productionPatterns(): string[] {
    const shell = (App as () => ReactElement)()
    const routes = findRoutes(shell)
    if (routes === null) throw new Error("App no longer renders a <Routes> element")
    const patterns: string[] = []
    const walk = (list: RouteObject[], parent: string) => {
        for (const route of list) {
            const own = route.path ?? ""
            const full = own.startsWith("/") ? own : own === "" ? parent : joinPath(parent, own)
            if (route.children !== undefined && route.children.length > 0) walk(route.children, full)
            else patterns.push(route.index === true ? (full === "" ? "/" : full) : full)
        }
    }
    walk(createRoutesFromChildren(routes), "")
    return patterns
}

function joinPath(parent: string, own: string): string {
    return parent === "" ? own : `${parent.replace(/\/$/, "")}/${own}`
}

function findRoutes(node: ReactNode): ReactNode | null {
    if (!isValidElement(node)) return null
    const element = node as ReactElement<{ children?: ReactNode }>
    if (typeof element.type !== "string" && (element.type as { name?: string }).name === "Routes") {
        return element.props.children
    }
    let found: ReactNode | null = null
    Children.forEach(element.props.children, (child) => {
        found ??= findRoutes(child)
    })
    return found
}

describe("production route inventory", () => {
    const patterns = productionPatterns()

    it("reads a plausible number of routes from App.tsx", () => {
        expect(patterns.length).toBeGreaterThan(90)
        expect(patterns).toContain("/app/:campaignId/parties/:partyId/edit")
        expect(patterns).toContain("/worlds/:worldId/timelines/:timelineId/branch")
        expect(patterns).toContain("*")
    })

    it("has metadata for every production route pattern", () => {
        const known = new Set(ROUTE_METAS.map((meta) => meta.pattern))
        expect(patterns.filter((pattern) => !known.has(pattern))).toEqual([])
    })

    it("has no metadata for a pattern App.tsx no longer routes", () => {
        const routed = new Set(patterns)
        expect(ROUTE_METAS.filter((meta) => !routed.has(meta.pattern)).map((meta) => meta.pattern)).toEqual([])
    })

    it("has unique ids and patterns", () => {
        expect(new Set(ROUTE_METAS.map((meta) => meta.id)).size).toBe(ROUTE_METAS.length)
        expect(new Set(ROUTE_METAS.map((meta) => meta.pattern)).size).toBe(ROUTE_METAS.length)
    })
})

describe("route metadata invariants", () => {
    it("keeps defaultRoot inside allowedRoots, and every root a known Navbar root", () => {
        for (const meta of ROUTE_METAS) {
            if (meta.defaultRoot !== null) expect(meta.allowedRoots, meta.id).toContain(meta.defaultRoot)
            for (const root of meta.allowedRoots) expect(NAV_ROOTS, meta.id).toContain(root)
        }
    })

    it("scopes by the params the pattern declares", () => {
        for (const meta of ROUTE_METAS) {
            const params = patternParams(meta.pattern)
            if (meta.scope === "campaign") expect(params, meta.id).toContain("campaignId")
            if (meta.scope === "world") expect(params, meta.id).toContain("worldId")
            if (meta.scope === "none") expect(params.includes("campaignId") || params.includes("worldId"), meta.id).toBe(false)
        }
    })

    it("points every parent at a real route whose params this page supplies", () => {
        for (const meta of ROUTE_METAS) {
            if (meta.parent === undefined) continue
            const parent = routeMetaById(meta.parent)
            expect(parent, `${meta.id} -> ${meta.parent}`).toBeDefined()
            const own = new Set(patternParams(meta.pattern))
            for (const name of patternParams(parent!.pattern)) expect(own.has(name), `${meta.id} lacks :${name}`).toBe(true)
            // A scoped page may sit under an unscoped list (Worlds), never under another scope.
            expect([meta.scope, "none"], meta.id).toContain(parent!.scope)
            if (parent!.scope === "none") expect(parent!.kind, meta.id).toBe("list")
        }
    })

    it("has acyclic parent chains and a default ancestry for every page", () => {
        for (const meta of ROUTE_METAS) {
            const params = Object.fromEntries(patternParams(meta.pattern).map((name) => [name, `${name}-1`]))
            const ancestors = defaultAncestors({ meta, params })
            expect(ancestors.length, meta.id).toBeLessThanOrEqual(ROUTE_METAS.length)
            expect(ancestors.map((ref) => ref.route), meta.id).not.toContain(meta.id)
            // The chain ends at the top of the family, root first.
            for (const ref of ancestors) expect(routeMetaById(ref.route), meta.id).toBeDefined()
        }
    })
})

describe("matching and default ancestors", () => {
    it("matches by react-router's ranking: a static preview route beats the claim id route", () => {
        expect(matchRouteMeta("/app/c1/knowledge/member-preview")?.meta.id).toBe("knowledge.memberPreview")
        expect(matchRouteMeta("/app/c1/knowledge/k1")?.meta.id).toBe("knowledge.detail")
        expect(matchRouteMeta("/app/c1/world/location/new")?.meta.id).toBe("world.location.new")
        expect(matchRouteMeta("/app/c1/world/npcs/e1")?.meta.id).toBe("world.record")
        expect(matchRouteMeta("/app/c1/nothing-here")?.meta.id).toBe("campaign.notFound")
        expect(matchRouteMeta("/somewhere/else")?.meta.id).toBe("public.notFound")
    })

    it("returns the declared params only", () => {
        expect(matchRouteMeta("/app/c1/parties/p1/edit")?.params).toEqual({ campaignId: "c1", partyId: "p1" })
    })

    it("keeps Parties ancestry on Parties and never offers Campaign Home", () => {
        const edit = matchRouteMeta("/app/c1/parties/p1/edit")!
        expect(edit.meta.defaultRoot).toBe("parties")
        expect(defaultAncestors(edit)).toEqual([
            { route: "parties.list", params: { campaignId: "c1" } },
            { route: "parties.detail", params: { campaignId: "c1", partyId: "p1" } },
        ])
        for (const meta of ROUTE_METAS.filter((candidate) => candidate.pattern.includes("/parties"))) {
            const params = Object.fromEntries(patternParams(meta.pattern).map((name) => [name, "x1"]))
            expect(defaultAncestors({ meta, params }).map((ref) => ref.route)).not.toContain("campaign.home")
        }
    })

    it("builds the character ancestry from the character's own route", () => {
        const inventory = matchRouteMeta("/app/c1/characters/ch1/inventory")!
        expect(defaultAncestors(inventory).map((ref) => ref.route)).toEqual(["characters.browse", "characters.detail"])
        expect(defaultAncestors(matchRouteMeta("/app/c1/characters/pc/new")!).map((ref) => ref.route)).toEqual([
            "characters.browse",
            "characters.new",
        ])
    })

    it("is empty for the top of a family", () => {
        expect(defaultAncestors(matchRouteMeta("/app/c1/parties")!)).toEqual([])
        expect(defaultAncestors(matchRouteMeta("/worlds")!)).toEqual([])
    })
})

describe("execution scope and viewed record are separate answers", () => {
    it("takes the scope from the route and the viewed record from a different param", () => {
        const sheet = matchRouteMeta("/app/c1/characters/ch1")!
        expect(executionScopeOf(sheet)).toEqual({ kind: "campaign", campaignId: "c1" })
        expect(viewedRecordOf(sheet)).toEqual({ type: "character", id: "ch1" })
    })

    it("has a world scope for world routes and none for unscoped ones", () => {
        expect(executionScopeOf(matchRouteMeta("/worlds/w1/timelines/t1")!)).toEqual({ kind: "world", worldId: "w1" })
        expect(viewedRecordOf(matchRouteMeta("/worlds/w1/timelines/t1")!)).toEqual({ type: "timeline", id: "t1" })
        expect(executionScopeOf(matchRouteMeta("/worlds")!)).toEqual({ kind: "none" })
        expect(executionScopeOf(matchRouteMeta("/campaigns")!)).toEqual({ kind: "none" })
        expect(viewedRecordOf(matchRouteMeta("/app/c1/parties")!)).toBeNull()
    })

    it("refuses a scope or record that is not id-shaped", () => {
        expect(executionScopeOf({ meta: routeMetaById("campaign.home")!, params: { campaignId: "a.b" } })).toEqual({
            kind: "none",
        })
        expect(viewedRecordOf({ meta: routeMetaById("parties.detail")!, params: { campaignId: "c", partyId: "x y" } })).toBeNull()
    })
})
