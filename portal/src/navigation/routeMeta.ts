import { matchRoutes } from "react-router"
import type { ExecutionScope, ViewedRecord } from "./contexts"
import { isIdShaped } from "./contexts"

// One entry per production route pattern in App.tsx (docs/UI_DESIGN.md §4.8, and the route inventory in
// docs/UI_DESIGN.md). `routeMeta.test.ts` builds the pattern list
// from the real route tree and fails when a pattern has no entry, or an entry matches no pattern, so
// this table cannot drift from App.tsx silently. Matching itself is react-router's, over these same
// patterns, so route ranking and permissions are untouched: this table only describes routes.

export type NavRoot =
    | "campaign"
    | "world"
    | "characters"
    | "parties"
    | "quests"
    | "sessions"
    | "knowledge"
    | "items"
    | "review"
    | "access"

export const NAV_ROOTS: readonly NavRoot[] = [
    "campaign",
    "world",
    "characters",
    "parties",
    "quests",
    "sessions",
    "knowledge",
    "items",
    "review",
    "access",
]

export type RouteScopeKind = "campaign" | "world" | "none"
export type RouteKind = "list" | "detail" | "section" | "create" | "edit" | "redirect" | "other"

export interface RouteMeta {
    id: string
    pattern: string
    scope: RouteScopeKind
    // The Navbar section the page belongs to when it is the start of a task; null for pages that are no
    // task start (public, account, redirects, not-found).
    defaultRoot: NavRoot | null
    // The task roots a task may be in when it reaches this page. Always contains `defaultRoot`.
    allowedRoots: readonly NavRoot[]
    kind: RouteKind
    // Static text, or a generic noun for an entity page (never a record's own name).
    label: string
    // The record the route shows, when it shows exactly one.
    viewed?: { type: string; param: string }
    // The id of the route a person goes up to by default. Its params are the parameters shared with this
    // pattern, so the ancestor chain is deterministic from the URL alone.
    parent?: string
}

type Roots = readonly NavRoot[]

const C = "/app/:campaignId"
const W = "/worlds"

// Roots from which an entity page can be reached by a link within a task.
const RECORD_ROOTS: Roots = ["world", "review", "characters", "parties", "quests", "sessions", "knowledge", "items"]
const CHARACTER_ROOTS: Roots = ["characters", "parties", "world", "sessions", "quests"]

function meta(
    id: string,
    pattern: string,
    scope: RouteScopeKind,
    defaultRoot: NavRoot | null,
    allowedRoots: Roots,
    kind: RouteKind,
    label: string,
    extra: { viewed?: RouteMeta["viewed"]; parent?: string } = {},
): RouteMeta {
    return { id, pattern, scope, defaultRoot, allowedRoots, kind, label, ...extra }
}

const campaign = (
    id: string,
    path: string,
    defaultRoot: NavRoot | null,
    allowedRoots: Roots,
    kind: RouteKind,
    label: string,
    extra?: { viewed?: RouteMeta["viewed"]; parent?: string },
) => meta(id, path === "" ? C : `${C}/${path}`, "campaign", defaultRoot, allowedRoots, kind, label, extra)

const world = (
    id: string,
    path: string,
    kind: RouteKind,
    label: string,
    extra?: { viewed?: RouteMeta["viewed"]; parent?: string },
) => meta(id, `${W}/${path}`, "world", "world", ["world"], kind, label, extra)

const unscoped = (id: string, pattern: string, defaultRoot: NavRoot | null, kind: RouteKind, label: string) =>
    meta(id, pattern, "none", defaultRoot, defaultRoot === null ? [] : [defaultRoot], kind, label)

export const ROUTE_METAS: readonly RouteMeta[] = [
    // Public and self-managed.
    unscoped("public.index", "/", null, "redirect", "Sign in"),
    unscoped("public.login", "/login", null, "other", "Sign in"),
    unscoped("public.invitation", "/campaign-invitations/accept", null, "other", "Campaign invitation"),
    unscoped("public.activate", "/activate", null, "other", "Activate account"),
    unscoped("public.resetPassword", "/reset-password", null, "other", "Reset password"),
    unscoped("public.notFound", "*", null, "other", "Page not found"),

    // Authenticated, not inside a campaign or world.
    unscoped("home", "/home", null, "redirect", "Home"),
    unscoped("settings", "/settings", null, "other", "Settings"),
    unscoped("campaigns.list", "/campaigns", null, "list", "Campaigns"),
    unscoped("campaigns.new", "/campaigns/new", null, "create", "New campaign"),
    unscoped("platform.accounts", "/platform/accounts", null, "other", "Accounts"),
    unscoped("account", "/account", null, "other", "Account"),
    unscoped("admin.accounts", "/admin/accounts", null, "redirect", "Accounts"),

    // Worlds. The list and the creation page name no world, so they are not world-scoped.
    meta("worlds.list", `${W}`, "none", "world", ["world"], "list", "Worlds"),
    meta("worlds.new", `${W}/new`, "none", "world", ["world"], "create", "New world", { parent: "worlds.list" }),
    meta("worlds.detail", `${W}/:worldId`, "world", "world", ["world"], "detail", "World", {
        viewed: { type: "world", param: "worldId" },
        parent: "worlds.list",
    }),
    world("worlds.edit", ":worldId/edit", "edit", "Edit", { parent: "worlds.detail" }),
    world("worlds.sharing", ":worldId/sharing", "section", "Sharing", { parent: "worlds.detail" }),
    world("worlds.canon", ":worldId/canon", "section", "Published canon", { parent: "worlds.detail" }),
    world("worlds.calendars.new", ":worldId/calendars/new", "create", "New calendar", { parent: "worlds.detail" }),
    world("worlds.timelines", ":worldId/timelines", "list", "Timelines", { parent: "worlds.detail" }),
    world("worlds.timelines.new", ":worldId/timelines/new", "create", "New timeline", { parent: "worlds.timelines" }),
    world("worlds.timeline", ":worldId/timelines/:timelineId", "detail", "Timeline", {
        viewed: { type: "timeline", param: "timelineId" },
        parent: "worlds.timelines",
    }),
    world("worlds.timeline.edit", ":worldId/timelines/:timelineId/edit", "edit", "Edit", { parent: "worlds.timeline" }),
    world("worlds.timeline.branch", ":worldId/timelines/:timelineId/branch", "create", "New branch", {
        parent: "worlds.timeline",
    }),

    // Campaign: home, world reader and authoring.
    campaign("campaign.index", "", "campaign", ["campaign"], "redirect", "Campaign"),
    campaign("campaign.home", "home", "campaign", ["campaign"], "section", "Campaign Home"),
    campaign("campaign.world", "world", "world", ["world"], "list", "World"),
    campaign("world.dungeon.new", "world/dungeon/new", "world", ["world"], "create", "New dungeon", {
        parent: "campaign.world",
    }),
    campaign("world.dungeon.edit", "world/dungeon/:dungeonId/edit", "world", ["world"], "edit", "Edit dungeon", {
        parent: "campaign.world",
    }),
    campaign(
        "world.dungeon.area.edit",
        "world/dungeon/:dungeonId/areas/:areaId/edit",
        "world",
        ["world"],
        "edit",
        "Edit area",
        { parent: "world.dungeon.edit" },
    ),
    campaign("world.location.new", "world/location/new", "world", ["world"], "create", "New location", {
        parent: "campaign.world",
    }),
    campaign("world.location.edit", "world/location/:entityId/edit", "world", ["world"], "edit", "Edit location", {
        parent: "campaign.world",
    }),
    campaign("world.organization.new", "world/organization/new", "world", ["world"], "create", "New organization", {
        parent: "campaign.world",
    }),
    campaign(
        "world.organization.edit",
        "world/organization/:entityId/edit",
        "world",
        ["world"],
        "edit",
        "Edit organization",
        { parent: "campaign.world" },
    ),
    campaign("world.religion.new", "world/religion/new", "world", ["world"], "create", "New religion", {
        parent: "campaign.world",
    }),
    campaign("world.religion.edit", "world/religion/:entityId/edit", "world", ["world"], "edit", "Edit religion", {
        parent: "campaign.world",
    }),
    campaign(
        "world.record.provenance",
        "world/:category/:entityId/provenance",
        "world",
        RECORD_ROOTS,
        "section",
        "Provenance",
        { parent: "world.record" },
    ),
    campaign(
        "world.record.history",
        "world/:category/:entityId/history",
        "world",
        RECORD_ROOTS,
        "section",
        "History",
        { parent: "world.record" },
    ),
    campaign("world.record", "world/:category/:entityId", "world", RECORD_ROOTS, "detail", "Record", {
        viewed: { type: "world-record", param: "entityId" },
        parent: "campaign.world",
    }),
    campaign("review.queue", "review", "review", ["review"], "list", "Review queue"),

    // Characters.
    campaign("characters.index", "characters", "characters", CHARACTER_ROOTS, "list", "Characters"),
    campaign("characters.browse", "characters/all", "characters", CHARACTER_ROOTS, "list", "All characters"),
    campaign("characters.new", "characters/new", "characters", ["characters", "world"], "create", "New character", {
        parent: "characters.browse",
    }),
    campaign("characters.npc.new", "characters/npc/new", "characters", ["characters", "world"], "create", "New NPC", {
        parent: "characters.new",
    }),
    campaign("characters.pc.new", "characters/pc/new", "characters", ["characters"], "create", "New PC", {
        parent: "characters.new",
    }),
    campaign(
        "characters.builds",
        "characters/:characterId/builds",
        "characters",
        CHARACTER_ROOTS,
        "section",
        "Builds",
        { parent: "characters.detail" },
    ),
    campaign(
        "characters.builds.new",
        "characters/:characterId/builds/new",
        "characters",
        CHARACTER_ROOTS,
        "create",
        "New build",
        { parent: "characters.builds" },
    ),
    campaign(
        "characters.portrayal",
        "characters/:characterId/portrayal",
        "characters",
        CHARACTER_ROOTS,
        "section",
        "Portrayal",
        { parent: "characters.detail" },
    ),
    campaign(
        "characters.edit",
        "characters/:characterId/edit",
        "characters",
        CHARACTER_ROOTS,
        "edit",
        "Edit",
        { parent: "characters.detail" },
    ),
    campaign(
        "characters.inventory",
        "characters/:characterId/inventory",
        "characters",
        CHARACTER_ROOTS,
        "section",
        "Inventory",
        { parent: "characters.detail" },
    ),
    campaign("characters.detail", "characters/:characterId", "characters", CHARACTER_ROOTS, "detail", "Character", {
        viewed: { type: "character", param: "characterId" },
        parent: "characters.browse",
    }),

    // Items.
    campaign("items.list", "items", "items", ["items"], "list", "Items"),
    campaign("items.new", "items/new", "items", ["items"], "create", "New item", { parent: "items.list" }),
    campaign("items.detail", "items/:itemId", "items", ["items", "characters", "sessions"], "detail", "Item", {
        viewed: { type: "item", param: "itemId" },
        parent: "items.list",
    }),
    campaign("items.edit", "items/:itemId/edit", "items", ["items", "characters", "sessions"], "edit", "Edit", {
        parent: "items.detail",
    }),
    campaign("itemDefinitions.list", "item-definitions", "items", ["items"], "list", "Item definitions"),
    campaign("itemDefinitions.new", "item-definitions/new", "items", ["items"], "create", "New item definition", {
        parent: "itemDefinitions.list",
    }),
    campaign(
        "itemDefinitions.detail",
        "item-definitions/:definitionId",
        "items",
        ["items"],
        "detail",
        "Item definition",
        { viewed: { type: "item-definition", param: "definitionId" }, parent: "itemDefinitions.list" },
    ),

    // Legacy section addresses: adapters that replace themselves, never a task page.
    campaign("knowledge.audience.redirect", "knowledge/:knowledgeItemId/audience", null, [], "redirect", "Who knows"),
    campaign("quests.progress.redirect", "quests/:questId/progress", null, [], "redirect", "Progress"),
    campaign("quests.edit.redirect", "quests/:questId/edit", null, [], "redirect", "Edit"),
    campaign("knowledge.edit.redirect", "knowledge/:knowledgeItemId/edit", null, [], "redirect", "Claim"),
    campaign("sessions.edit.redirect", "sessions/:sessionId/edit", null, [], "redirect", "Edit"),

    // Events.
    campaign("events.new", "events/new", "sessions", ["sessions", "world", "quests"], "create", "Record event", {
        parent: "sessions.list",
    }),
    campaign("events.detail", "events/:eventId", "sessions", ["sessions", "world", "quests"], "detail", "Event", {
        viewed: { type: "event", param: "eventId" },
        parent: "sessions.list",
    }),

    // Parties stay Parties: Campaign Home is never an ancestor.
    campaign("parties.list", "parties", "parties", ["parties", "characters", "sessions"], "list", "Parties"),
    campaign("parties.new", "parties/new", "parties", ["parties", "characters", "sessions"], "create", "New party", {
        parent: "parties.list",
    }),
    campaign("parties.detail", "parties/:partyId", "parties", ["parties", "characters", "sessions"], "detail", "Party", {
        viewed: { type: "party", param: "partyId" },
        parent: "parties.list",
    }),
    campaign("parties.edit", "parties/:partyId/edit", "parties", ["parties", "characters", "sessions"], "edit", "Edit", {
        parent: "parties.detail",
    }),

    campaign("worldTimes", "world-times", "campaign", ["campaign", "world", "parties", "sessions"], "other", "World time"),

    // Quests.
    campaign("quests.list", "quests", "quests", ["quests", "characters", "sessions"], "list", "Quests"),
    campaign("quests.new", "quests/new", "quests", ["quests"], "create", "New quest", { parent: "quests.list" }),
    campaign("quests.detail", "quests/:questId", "quests", ["quests", "characters", "sessions"], "detail", "Quest", {
        viewed: { type: "quest", param: "questId" },
        parent: "quests.list",
    }),

    // Sessions.
    campaign("sessions.list", "sessions", "sessions", ["sessions", "characters", "quests", "world", "knowledge"], "list", "Sessions"),
    campaign("sessions.new", "sessions/new", "sessions", ["sessions"], "create", "New session", {
        parent: "sessions.list",
    }),
    campaign(
        "sessions.run",
        "sessions/:sessionId/run",
        "sessions",
        ["sessions", "characters", "quests", "world", "knowledge"],
        "section",
        "Run session",
        { parent: "sessions.detail" },
    ),
    campaign(
        "sessions.encounters.new",
        "sessions/:sessionId/encounters/new",
        "sessions",
        ["sessions"],
        "create",
        "Prepare encounter",
        { parent: "sessions.run" },
    ),
    campaign(
        "sessions.encounters.detail",
        "sessions/:sessionId/encounters/:encounterId",
        "sessions",
        ["sessions"],
        "detail",
        "Encounter",
        { viewed: { type: "encounter", param: "encounterId" }, parent: "sessions.run" },
    ),
    campaign(
        "sessions.detail",
        "sessions/:sessionId",
        "sessions",
        ["sessions", "characters", "quests", "world", "knowledge"],
        "detail",
        "Session",
        { viewed: { type: "session", param: "sessionId" }, parent: "sessions.list" },
    ),

    // Knowledge.
    campaign(
        "knowledge.list",
        "knowledge",
        "knowledge",
        ["knowledge", "characters", "quests", "sessions", "world"],
        "list",
        "Knowledge",
    ),
    campaign("knowledge.new", "knowledge/new", "knowledge", ["knowledge"], "create", "New claim", {
        parent: "knowledge.list",
    }),
    campaign("knowledge.memberPreview", "knowledge/member-preview", "knowledge", ["knowledge"], "other", "Member preview", {
        parent: "knowledge.list",
    }),
    campaign(
        "knowledge.memberPreview.claim",
        "knowledge/member-preview/:knowledgeItemId",
        "knowledge",
        ["knowledge"],
        "detail",
        "Member preview",
        { parent: "knowledge.memberPreview" },
    ),
    campaign(
        "knowledge.detail",
        "knowledge/:knowledgeItemId",
        "knowledge",
        ["knowledge", "characters", "quests", "sessions", "world"],
        "detail",
        "Claim",
        { viewed: { type: "knowledge-claim", param: "knowledgeItemId" }, parent: "knowledge.list" },
    ),

    campaign("ask", "ask", "campaign", ["campaign"], "other", "Ask"),
    campaign("campaign.settings", "settings", "campaign", ["campaign"], "section", "Campaign settings"),
    campaign("access.overview", "access", "access", ["access"], "section", "Access"),
    campaign("access.invitations", "access/invitations", "access", ["access"], "section", "Invitations", {
        parent: "access.overview",
    }),
    campaign("access.audit", "access/audit", "access", ["access"], "section", "Access audit", {
        parent: "access.overview",
    }),
    campaign("campaign.notFound", "*", null, [], "other", "Campaign page not found"),
]

const BY_ID = new Map<string, RouteMeta>(ROUTE_METAS.map((entry) => [entry.id, entry]))

export function routeMetaById(id: string): RouteMeta | undefined {
    return BY_ID.get(id)
}

/** The parameter names a pattern declares, in order (`*` is not a parameter). */
export function patternParams(pattern: string): string[] {
    return pattern
        .split("/")
        .filter((segment) => segment.startsWith(":"))
        .map((segment) => segment.slice(1))
}

const MATCHABLE = ROUTE_METAS.map((entry) => ({ id: entry.id, path: entry.pattern }))

export interface RouteMatch {
    meta: RouteMeta
    // Only the declared, non-empty parameters of the pattern (the splat is dropped).
    params: Record<string, string>
}

/** The route `pathname` resolves to, by react-router's own ranking over the production patterns. */
export function matchRouteMeta(pathname: string): RouteMatch | null {
    const matches = matchRoutes(MATCHABLE, pathname)
    const leaf = matches?.[matches.length - 1]
    if (leaf === undefined) return null
    const found = BY_ID.get(leaf.route.id as string)
    if (found === undefined) return null
    const params: Record<string, string> = {}
    for (const name of patternParams(found.pattern)) {
        const value = leaf.params[name]
        if (typeof value !== "string" || value === "") return null
        params[name] = value
    }
    return { meta: found, params }
}

const SCOPE_PARAM: Record<Exclude<RouteScopeKind, "none">, string> = {
    campaign: "campaignId",
    world: "worldId",
}

/** Whose data the route reads and writes: from the route's own params, never from a selection. */
export function executionScopeOf(match: RouteMatch): ExecutionScope {
    if (match.meta.scope === "none") return { kind: "none" }
    const id = match.params[SCOPE_PARAM[match.meta.scope]]
    if (!isIdShaped(id)) return { kind: "none" }
    return match.meta.scope === "campaign" ? { kind: "campaign", campaignId: id } : { kind: "world", worldId: id }
}

/** The record the route shows, or null when it shows none. */
export function viewedRecordOf(match: RouteMatch): ViewedRecord | null {
    const viewed = match.meta.viewed
    if (viewed === undefined) return null
    const id = match.params[viewed.param]
    return isIdShaped(id) ? { type: viewed.type, id } : null
}

export interface RouteRef {
    route: string
    params: Record<string, string>
}

/**
 * The default ancestors of a page, root first: the `parent` chain of its metadata with each ancestor's
 * own parameters taken from this page's. Deterministic from the URL alone; empty only for a page that
 * is itself the top of its family.
 */
export function defaultAncestors(match: RouteMatch): RouteRef[] {
    const chain: RouteRef[] = []
    const seen = new Set<string>([match.meta.id])
    let parentId = match.meta.parent
    while (parentId !== undefined && !seen.has(parentId)) {
        seen.add(parentId)
        const parent = BY_ID.get(parentId)
        if (parent === undefined) break
        const params: Record<string, string> = {}
        for (const name of patternParams(parent.pattern)) {
            const value = match.params[name]
            if (value === undefined) return []
            params[name] = value
        }
        chain.unshift({ route: parent.id, params })
        parentId = parent.parent
    }
    return chain
}
