import type { EntityLifecycleView } from "../../types/entityLifecycle"

// The Knowledge claim page is organised into stages, each with local sections. Stages and
// sections are a way of organising the interface only: they are never persisted, never call the
// API and are not lifecycle statuses. The claim's real status is shown in the page header.

export type ClaimStage = "prepare" | "review" | "use"

export type ClaimSection = "claim" | "sources" | "review" | "publication" | "who-knows" | "character"

export interface ClaimSectionInfo {
    key: ClaimSection
    stage: ClaimStage
    label: string
    purpose: string
}

export const CLAIM_STAGES: readonly { key: ClaimStage; label: string }[] = [
    { key: "prepare", label: "Prepare" },
    { key: "review", label: "Review & publish" },
    { key: "use", label: "Use in play" },
]

export const CLAIM_SECTIONS: readonly ClaimSectionInfo[] = [
    {
        key: "claim",
        stage: "prepare",
        label: "Claim",
        purpose: "What the claim says, what it is about, and the GM's canonical record of it.",
    },
    {
        key: "sources",
        stage: "prepare",
        label: "Sources",
        purpose: "Where this claim came from.",
    },
    {
        key: "review",
        stage: "review",
        label: "Review claim",
        purpose: "Check what a reviewer would approve.",
    },
    {
        key: "publication",
        stage: "review",
        label: "Publication",
        purpose: "Where the claim is in its life, and the steps available to you.",
    },
    {
        key: "who-knows",
        stage: "use",
        label: "Who knows this",
        purpose: "Recorded separately from the claim. Changes here save on their own.",
    },
    {
        key: "character",
        stage: "use",
        label: "Character knowledge",
        purpose: "What the selected character knows of this claim.",
    },
]

export const claimHeadingId = (key: ClaimSection): string => `claim-section-${key}-heading`

export const claimSectionInfo = (key: ClaimSection): ClaimSectionInfo =>
    CLAIM_SECTIONS.find((s) => s.key === key) as ClaimSectionInfo

export const claimStageOf = (key: ClaimSection): ClaimStage => claimSectionInfo(key).stage

export const claimSectionsOf = (stage: ClaimStage): ClaimSectionInfo[] =>
    CLAIM_SECTIONS.filter((s) => s.stage === stage)

export const claimStageLabel = (stage: ClaimStage): string =>
    (CLAIM_STAGES.find((s) => s.key === stage) as { label: string }).label

// A valid section key, or null for anything missing or unknown.
export function parseClaimSection(raw: string | null | undefined): ClaimSection | null {
    return CLAIM_SECTIONS.find((s) => s.key === raw)?.key ?? null
}

// Where an editor lands when the address names no section. Derived from the loaded lifecycle only;
// `null` (the lifecycle read failed) opens the claim.
export function defaultClaimSection(
    lifecycle: Pick<EntityLifecycleView, "canon_status" | "lifecycle_status"> | null,
): ClaimSection {
    if (lifecycle === null) return "claim"
    if (lifecycle.lifecycle_status === "archived") return "publication"
    switch (lifecycle.canon_status) {
        case "proposed":
        case "approved":
            return "review"
        case "canon":
        case "superseded":
            return "who-knows"
        default:
            return "claim"
    }
}

export type GuidanceTarget =
    | { kind: "section"; section: ClaimSection }
    | { kind: "replacement"; entityId: string }
    | { kind: "subject" }

export interface ClaimGuidance {
    text: string
    target: GuidanceTarget
}

// The one next step that is actually available, from the server's own lifecycle read. Navigation
// only: the target is where the step lives, never an action.
export function claimGuidance(view: EntityLifecycleView): ClaimGuidance | null {
    const available = new Set(view.available_actions)
    const section = (text: string, key: ClaimSection): ClaimGuidance => ({
        text,
        target: { kind: "section", section: key },
    })
    if (view.lifecycle_status === "archived") {
        if (!available.has("restore")) return null
        return section(
            view.canon_status === "canon" ? "Restore it to use it in play" : "Restore it, then continue review",
            "publication",
        )
    }
    if (view.canon_status === "superseded") {
        return view.superseded_by === null
            ? null
            : {
                  text: `Replaced by ${view.superseded_by.canonical_name}`,
                  target: { kind: "replacement", entityId: view.superseded_by.entity_id },
              }
    }
    if (available.has("publish")) return section("Publish as canon", "publication")
    if (view.canon_status === "approved" && subjectBlocksPublish(view)) {
        return { text: "Publish its subject first", target: { kind: "subject" } }
    }
    if (available.has("approve")) return section("Approve", "review")
    if (available.has("submit_for_review")) return section("Submit for review", "publication")
    if (view.canon_status === "rejected" && available.has("return_to_draft")) {
        return section("Return it to draft to rework it", "publication")
    }
    if (view.canon_status === "canon") return section("Record who knows it", "who-knows")
    return null
}

// Publishing is blocked only because the claim's subject is not yet published.
export function subjectBlocksPublish(view: Pick<EntityLifecycleView, "blocked_actions">): boolean {
    return view.blocked_actions.some((b) => b.action === "publish" && b.reason === "reference_not_published")
}
