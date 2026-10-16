import type { EntityLifecycleView } from "../../types/entityLifecycle"

// The World record workspace is organised into stages, each with local sections, for the kinds of
// record an editor authors: places, dungeons, dungeon areas, organizations, religions, NPCs and
// player characters. Stages and sections organise the interface only: they are never persisted,
// never call the API and are not lifecycle statuses. The record's real status is shown in the page
// header. Items keep the item workspace; events and relationships are not lifecycle-managed and
// have no workspace.

export type WorldStage = "prepare" | "publish" | "play"

export type WorldSection =
    | "details"
    | "structure"
    | "sources"
    | "relationships"
    | "review"
    | "publication"
    | "area-now"
    | "members"
    | "run"
    | "player"
    | "inventory"

// What a record is, as far as the workspace is concerned. "character" is a character whose type
// could not be read (the lifecycle read failed): it gets only what applies to either kind.
export type WorldKind = "place" | "dungeon" | "area" | "organization" | "religion" | "npc" | "pc" | "character"

// The World categories the workspace covers. Items use the item workspace; events are not
// lifecycle-managed.
export type WorkspaceCategory = "location" | "organization" | "religion" | "character"

export const WORKSPACE_CATEGORIES: readonly string[] = ["location", "organization", "religion", "character"]

export function isWorkspaceCategory(value: string): value is WorkspaceCategory {
    return WORKSPACE_CATEGORIES.includes(value)
}

export interface WorldSectionInfo {
    key: WorldSection
    stage: WorldStage
    label: string
    purpose: string
}

export const WORLD_STAGE_LABELS: Readonly<Record<WorldStage, string>> = {
    prepare: "Prepare",
    publish: "Review & publish",
    play: "Use in play",
}

const STAGE_ORDER: readonly WorldStage[] = ["prepare", "publish", "play"]

const INFO: Readonly<Record<WorldSection, WorldSectionInfo>> = {
    details: {
        key: "details",
        stage: "prepare",
        label: "Details",
        purpose: "What this record says. Editing happens on its own page and returns here.",
    },
    structure: {
        key: "structure",
        stage: "prepare",
        label: "Structure",
        purpose: "The areas of this dungeon and the connections between them.",
    },
    sources: {
        key: "sources",
        stage: "prepare",
        label: "Sources",
        purpose: "Where this record came from.",
    },
    relationships: {
        key: "relationships",
        stage: "prepare",
        label: "Relationships",
        purpose: "How this record is connected to others. Each relationship is its own record and saves on its own.",
    },
    review: {
        key: "review",
        stage: "publish",
        label: "Review",
        purpose: "Check what a reviewer would approve, and decide.",
    },
    publication: {
        key: "publication",
        stage: "publish",
        label: "Publication",
        purpose: "Where the record is in its life, and the steps available to you.",
    },
    "area-now": {
        key: "area-now",
        stage: "play",
        label: "Area now",
        purpose: "What is true of this area in this campaign's timeline, recorded as events apart from the area itself.",
    },
    members: {
        key: "members",
        stage: "play",
        label: "Members and status",
        purpose: "Who belongs to this organization and its operational status. Each change saves on its own.",
    },
    run: {
        key: "run",
        stage: "play",
        label: "Run this NPC",
        purpose: "Hit points, conditions, resources and location. Each change is recorded as an event and saves on its own.",
    },
    player: {
        key: "player",
        stage: "play",
        label: "Player",
        purpose: "Which player controls this character.",
    },
    inventory: {
        key: "inventory",
        stage: "play",
        label: "Inventory",
        purpose: "What this character carries.",
    },
}

const COMMON_PREPARE: readonly WorldSection[] = ["details", "sources", "relationships"]
const REVIEW: readonly WorldSection[] = ["review", "publication"]

// The sections each kind has, in the order they are listed within their stage.
const KIND_SECTIONS: Readonly<Record<WorldKind, readonly WorldSection[]>> = {
    place: [...COMMON_PREPARE, ...REVIEW],
    dungeon: ["details", "structure", "sources", "relationships", ...REVIEW],
    area: [...COMMON_PREPARE, ...REVIEW, "area-now"],
    organization: [...COMMON_PREPARE, ...REVIEW, "members"],
    religion: [...COMMON_PREPARE, ...REVIEW],
    npc: [...COMMON_PREPARE, ...REVIEW, "run", "inventory"],
    pc: [...COMMON_PREPARE, ...REVIEW, "player", "inventory"],
    character: [...COMMON_PREPARE, ...REVIEW, "inventory"],
}

// The kind of record, from the category it is browsed under and, where that category holds more
// than one kind, the entity type the lifecycle read reports (`null` when it could not be read).
export function worldKindOf(category: WorkspaceCategory, entityTypeCode: string | null): WorldKind {
    switch (category) {
        case "location":
            return entityTypeCode === "dungeon" ? "dungeon" : entityTypeCode === "dungeon_area" ? "area" : "place"
        case "organization":
            return "organization"
        case "religion":
            return "religion"
        case "character":
            return entityTypeCode === "npc" ? "npc" : entityTypeCode === "player_character" ? "pc" : "character"
    }
}

export const worldSectionInfo = (key: WorldSection): WorldSectionInfo => INFO[key]

export function worldSectionsOf(kind: WorldKind): WorldSectionInfo[] {
    return KIND_SECTIONS[kind].map((key) => INFO[key])
}

// The stages a kind has, in order.
export function worldStagesOf(kind: WorldKind): WorldStage[] {
    const present = new Set(worldSectionsOf(kind).map((s) => s.stage))
    return STAGE_ORDER.filter((stage) => present.has(stage))
}

export const worldSectionsInStage = (kind: WorldKind, stage: WorldStage): WorldSectionInfo[] =>
    worldSectionsOf(kind).filter((s) => s.stage === stage)

export const worldHeadingId = (key: WorldSection): string => `world-section-${key}-heading`

type StatusView = Pick<EntityLifecycleView, "canon_status" | "lifecycle_status">

// Where an editor lands when the address names no section. Derived from the loaded lifecycle only;
// `null` (the read failed) opens the details.
export function defaultWorldSection(view: StatusView | null): WorldSection {
    if (view === null) return "details"
    if (view.lifecycle_status === "archived") return "publication"
    switch (view.canon_status) {
        case "proposed":
        case "approved":
            return "review"
        case "superseded":
            return "publication"
        default:
            return "details"
    }
}

export interface WorldGuidance {
    text: string
    section: WorldSection
}

// The one next step that is actually available, from the server's own lifecycle actions. Navigation
// only: the target is where the step lives, never an action. Nothing is offered once a record is in
// play, because the sections that apply differ too much between kinds to name one honestly.
export function worldGuidance(view: Pick<EntityLifecycleView, "canon_status" | "lifecycle_status" | "available_actions">): WorldGuidance | null {
    const available = new Set(view.available_actions)
    const at = (text: string, section: WorldSection): WorldGuidance => ({ text, section })
    if (view.lifecycle_status === "archived") {
        return available.has("restore") ? at("Restore it", "publication") : null
    }
    if (view.canon_status === "superseded") return null
    if (available.has("publish")) return at("Publish it", "review")
    if (available.has("approve")) return at("Approve it", "review")
    if (available.has("submit_for_review")) return at("Submit for review", "review")
    if (view.canon_status === "rejected" && available.has("return_to_draft")) {
        return at("Return it to draft to rework it", "publication")
    }
    return null
}

// Why a section that records what happens in play is not available yet, or `null` when the record
// is published and active (the condition under which the server accepts those commands) or its
// status is unknown. The server remains the authority; this only explains.
export function playBlockedText(view: StatusView | null, subject: string): string | null {
    if (view === null) return null
    if (view.lifecycle_status === "archived") {
        return `This ${subject} is archived. Restore it before recording what happens to it.`
    }
    switch (view.canon_status) {
        case "canon":
            return null
        case "superseded":
            return `This ${subject} has been replaced and takes no new events.`
        default:
            return `This ${subject} is not published yet. Publish it before recording what happens to it.`
    }
}
