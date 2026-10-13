import type { EntityLifecycleView } from "../../types/entityLifecycle"

// The Quest workspace is organised into workflow phases, each with local sections. They organise
// the interface only: they are never persisted, never call the API and are not lifecycle statuses
// or quest progress. The record's real status is shown in the page header.
//
// Three things are kept apart here and in the copy:
//   - a workflow phase (this file): Prepare, Review & publish, Use in play;
//   - a quest stage and its objectives: the authored adventure, a definition (never named "phase");
//   - progress: per-scope timeline state changed only by explicit GM commands.

export type QuestPhase = "prepare" | "publish" | "play"

export type QuestSection =
    | "details"
    | "structure"
    | "dependencies"
    | "outcomes"
    | "participants"
    | "sources"
    | "review"
    | "publication"
    | "progress"
    | "preview"

export interface QuestSectionInfo {
    key: QuestSection
    phase: QuestPhase
    label: string
    purpose: string
}

export const QUEST_PHASE_LABELS: Readonly<Record<QuestPhase, string>> = {
    prepare: "Prepare",
    publish: "Review & publish",
    play: "Use in play",
}

const PHASE_ORDER: readonly QuestPhase[] = ["prepare", "publish", "play"]

const INFO: Readonly<Record<QuestSection, QuestSectionInfo>> = {
    details: {
        key: "details",
        phase: "prepare",
        label: "Details",
        purpose: "The quest's name and summary, and the planning notes only editors see. Each saves on its own.",
    },
    structure: {
        key: "structure",
        phase: "prepare",
        label: "Stages and objectives",
        purpose: "The adventure's stages in order, and the objectives in each. Every change saves on its own.",
    },
    dependencies: {
        key: "dependencies",
        phase: "prepare",
        label: "Dependencies",
        purpose: "Which objectives wait on which others.",
    },
    outcomes: {
        key: "outcomes",
        phase: "prepare",
        label: "Outcomes and rewards",
        purpose: "How the quest can end, and what each ending gives.",
    },
    participants: {
        key: "participants",
        phase: "prepare",
        label: "Participants",
        purpose: "The characters and organizations involved, and their roles.",
    },
    sources: {
        key: "sources",
        phase: "prepare",
        label: "Sources",
        purpose: "Where this quest came from.",
    },
    review: {
        key: "review",
        phase: "publish",
        label: "Review",
        purpose: "Check what a reviewer would approve, and decide.",
    },
    publication: {
        key: "publication",
        phase: "publish",
        label: "Publication",
        purpose: "Where the quest is in its life, and the steps available to you.",
    },
    progress: {
        key: "progress",
        phase: "play",
        label: "Progress",
        purpose: "How far the campaign and each party have got. Every change is recorded as an event and saves on its own.",
    },
    preview: {
        key: "preview",
        phase: "play",
        label: "Member preview",
        purpose: "What a member of the campaign would see of this quest. Read-only.",
    },
}

const ALWAYS: readonly QuestSection[] = [
    "details",
    "structure",
    "dependencies",
    "outcomes",
    "participants",
    "sources",
    "review",
    "publication",
    "progress",
]

// The sections an editor has. The member preview is offered only to people who may preview a
// member (`access.manage`); everyone with the workspace has the rest.
export function questSectionsOf({ canPreview }: { canPreview: boolean }): QuestSectionInfo[] {
    const keys: QuestSection[] = canPreview ? [...ALWAYS, "preview"] : [...ALWAYS]
    return keys.map((key) => INFO[key])
}

export const questSectionInfo = (key: QuestSection): QuestSectionInfo => INFO[key]

export const questSectionsInPhase = (sections: readonly QuestSectionInfo[], phase: QuestPhase): QuestSectionInfo[] =>
    sections.filter((s) => s.phase === phase)

export const questPhasesOf = (sections: readonly QuestSectionInfo[]): QuestPhase[] =>
    PHASE_ORDER.filter((phase) => sections.some((s) => s.phase === phase))

export const questHeadingId = (key: QuestSection): string => `quest-section-${key}-heading`

type StatusView = Pick<EntityLifecycleView, "canon_status" | "lifecycle_status">

// Where an editor lands when the address names no section. Derived from the loaded lifecycle only;
// `null` (the read failed) opens the details.
export function defaultQuestSection(view: StatusView | null): QuestSection {
    if (view === null) return "details"
    if (view.lifecycle_status === "archived") return "publication"
    switch (view.canon_status) {
        case "proposed":
        case "approved":
            return "review"
        case "superseded":
            return "publication"
        case "canon":
            return "progress"
        default:
            return "details"
    }
}

export type QuestGuidanceTarget =
    | { kind: "section"; section: QuestSection }
    | { kind: "replacement"; entityId: string }

export interface QuestGuidance {
    text: string
    target: QuestGuidanceTarget
}

// The one next step that is actually available, from the server's own lifecycle actions (and, for
// a draft with nothing to publish yet, the authoring read's own stages). Navigation only: the
// target is where the step lives, never an action. The server still decides every step.
export function questGuidance(
    view: Pick<EntityLifecycleView, "canon_status" | "lifecycle_status" | "available_actions" | "superseded_by">,
    { canEdit, hasObjective }: { canEdit: boolean; hasObjective: boolean },
): QuestGuidance | null {
    const available = new Set(view.available_actions)
    const at = (text: string, section: QuestSection): QuestGuidance => ({
        text,
        target: { kind: "section", section },
    })
    if (view.lifecycle_status === "archived") {
        return available.has("restore") ? at("Restore it", "publication") : null
    }
    if (view.canon_status === "superseded") {
        return view.superseded_by === null
            ? null
            : {
                  text: `Replaced by ${view.superseded_by.canonical_name}`,
                  target: { kind: "replacement", entityId: view.superseded_by.entity_id },
              }
    }
    if (view.canon_status === "canon") return at("Run it", "progress")
    if (available.has("publish")) return at("Publish it", "review")
    if (available.has("approve")) return at("Approve it", "review")
    if (view.canon_status === "draft" && canEdit && !hasObjective) {
        return at("Add stages and objectives", "structure")
    }
    if (available.has("submit_for_review")) return at("Submit for review", "publication")
    if (view.canon_status === "rejected" && available.has("return_to_draft")) {
        return at("Return it to draft to rework it", "publication")
    }
    return null
}

// Why running the quest is not available yet, or `null` when it is published and active (the
// condition under which the server accepts progress commands) or its status is unknown. The server
// remains the authority; this only explains. An unknown status is not eligibility: the caller
// withholds the commands in that case too.
export function questPlayBlockedText(view: StatusView | null): string | null {
    if (view === null) return null
    if (view.lifecycle_status === "archived") {
        return "This quest is archived. Restore it before running it."
    }
    switch (view.canon_status) {
        case "canon":
            return null
        case "superseded":
            return "This quest has been replaced. Run its replacement."
        default:
            return "This quest is not published yet. Publish it before running it."
    }
}

// Why the definition cannot be changed now, and what to do about it, from the server's own blocked
// reason for `update` (a status the person can act on is named; anything else is not guessed).
export function questEditBlockedText(view: StatusView): string {
    if (view.lifecycle_status === "archived") return "This quest is archived. Restore it to edit it."
    switch (view.canon_status) {
        case "proposed":
        case "approved":
            return "This quest is in review. Return it to draft to edit it."
        case "rejected":
            return "This quest was rejected. Return it to draft to edit it."
        case "superseded":
            return "This quest has been replaced and can no longer be edited. Edit its replacement instead."
        default:
            return "This quest cannot be edited right now."
    }
}
