import type { CampaignSessionDetail } from "../../types/campaignSession"

// The Run Session page is organised into stages, each with local sections. Stages are a way of
// organising the interface only: they are never persisted, never call the API, and are not
// session lifecycle states.

export type Stage = "prepare" | "run" | "wrap"

export type SectionKey =
    | "participants"
    | "encounter-prep"
    | "log"
    | "travel"
    | "award-item"
    | "encounters"
    | "review"
    | "end"

export interface SectionInfo {
    key: SectionKey
    stage: Stage
    label: string
    purpose: string
}

export const STAGES: readonly { key: Stage; label: string }[] = [
    { key: "prepare", label: "Prepare" },
    { key: "run", label: "Run session" },
    { key: "wrap", label: "Wrap up" },
]

export const SECTIONS: readonly SectionInfo[] = [
    {
        key: "participants",
        stage: "prepare",
        label: "Participants",
        purpose: "Who is taking part in this session, and in what role.",
    },
    {
        key: "encounter-prep",
        stage: "prepare",
        label: "Encounter preparation",
        purpose: "Prepare encounters ahead of play. A prepared encounter waits until you start it.",
    },
    {
        key: "log",
        stage: "run",
        label: "Session log",
        purpose: "Record what happened. Entries are visible to the campaign. GM notes stay with editors.",
    },
    {
        key: "travel",
        stage: "run",
        label: "Travel",
        purpose: "Record characters or a whole party arriving somewhere.",
    },
    {
        key: "award-item",
        stage: "run",
        label: "Award item",
        purpose: "Give an unplaced, published item to someone taking part.",
    },
    {
        key: "encounters",
        stage: "run",
        label: "Encounters",
        purpose: "Encounters in this session that have started or finished. Open one to play or review it.",
    },
    {
        key: "review",
        stage: "wrap",
        label: "Session review",
        purpose: "Check what this session recorded before you end it.",
    },
    {
        key: "end",
        stage: "wrap",
        label: "End session",
        purpose: "End the session. This marks it completed.",
    },
]

export const panelHeadingId = (key: SectionKey): string => `run-section-${key}-heading`

export const sectionInfo = (key: SectionKey): SectionInfo =>
    SECTIONS.find((s) => s.key === key) as SectionInfo

export const stageOf = (key: SectionKey): Stage => sectionInfo(key).stage

export const sectionsOf = (stage: Stage): SectionInfo[] => SECTIONS.filter((s) => s.stage === stage)

export const stageLabel = (stage: Stage): string =>
    (STAGES.find((s) => s.key === stage) as { label: string }).label

// A valid section key, or null for anything missing or unknown.
export function parseSection(raw: string | null | undefined): SectionKey | null {
    return SECTIONS.find((s) => s.key === raw)?.key ?? null
}

// Where a session opens when the address names no section. Derived from the loaded session only.
export function defaultSection(
    session: Pick<CampaignSessionDetail, "status_code" | "play_status">,
): SectionKey {
    if (session.status_code !== "active") return "review"
    switch (session.play_status ?? "unscheduled") {
        case "in_progress":
            return "log"
        case "completed":
            return "review"
        default:
            return "participants"
    }
}
