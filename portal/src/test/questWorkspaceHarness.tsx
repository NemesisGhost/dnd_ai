/* eslint-disable react-refresh/only-export-components -- test support module: Fast Refresh does not apply to it. */
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { CampaignQuestDetailPage } from "../pages/CampaignQuestDetailPage"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "./authoringHarness"
import { installRecordReads } from "./worldWorkspaceMocks"

// Test support for the Quest workspace: the authoring read model, the lifecycle read, the progress
// read and the records the workspace reads beside them, mounted at the quest's own address.

const CHOICES = (pairs: [string, string][]) => pairs.map(([value, label]) => ({ value, label }))

export const QUEST_OPTIONS = {
    can_create: true,
    objective_types: CHOICES([
        ["reach_location", "Reach a location"],
        ["other", "Other"],
    ]),
    stage_types: CHOICES([
        ["sequential", "Sequential"],
        ["optional", "Optional"],
    ]),
    requirement_levels: CHOICES([
        ["required", "Required"],
        ["optional", "Optional"],
    ]),
    completion_modes: CHOICES([
        ["automatic", "Automatic"],
        ["gm_confirmed", "Confirmed by the GM"],
    ]),
    visibility_policies: CHOICES([
        ["visible", "Visible"],
        ["gm_only", "GM only"],
    ]),
    dependency_types: CHOICES([["prerequisite", "Prerequisite"]]),
    participant_roles: CHOICES([
        ["giver", "Quest giver"],
        ["involved", "Involved"],
    ]),
    outcome_categories: CHOICES([
        ["success", "Success"],
        ["failure", "Failure"],
    ]),
    reward_types: CHOICES([
        ["other", "Other"],
        ["knowledge", "Knowledge"],
    ]),
    limits: {
        gm_notes_max_length: 40,
        outcome_description_max_length: 4000,
        reward_description_max_length: 1000,
        name_max_length: 200,
        summary_max_length: 4000,
        change_note_max_length: 1000,
        max_stages: 100,
        max_objectives_per_stage: 100,
        quantity_max: 1000000,
    },
}

export const questObjective = (id: string, name: string, overrides: object = {}) => ({
    quest_objective_id: id,
    name,
    description: null,
    objective_type: "other",
    objective_type_label: "Other",
    requirement_level: "required",
    completion_mode: "automatic",
    visibility_policy: "visible",
    quantity_required: null,
    target_kind: null,
    target: null,
    ...overrides,
})

export const FREE_ACTIONS = [
    "update",
    "add_stage",
    "update_stage",
    "add_objective",
    "update_objective",
    "add_participant",
    "remove_participant",
    "add_outcome",
    "update_outcome",
    "remove_outcome",
    "add_reward",
    "remove_reward",
    "reorder_stages",
    "remove_stage",
    "remove_objective",
    "add_dependency",
    "remove_dependency",
]

export function questView(overrides: object = {}) {
    return {
        quest_id: "q1",
        name: "The Lost Amulet",
        summary: "Find it.",
        has_progress: false,
        gm_notes: "Remember the twist.",
        dependencies: [
            {
                objective_dependency_id: "d1",
                objective_id: "o2",
                depends_on_objective_id: "o1",
                dependency_type: "prerequisite",
            },
        ],
        participants: [
            {
                quest_participant_id: "p1",
                participant_role: "giver",
                participant: { entity_id: "n1", name: "Mara", canon_status: "canon", lifecycle_status: "active" },
            },
        ],
        outcomes: [
            {
                quest_outcome_id: "out1",
                code: "saved",
                name: "Village saved",
                description: null,
                outcome_category: "success",
                rewards: [{ quest_reward_id: "r1", reward_type: "other", description: "50 gold", knowledge: null }],
            },
        ],
        stages: [
            {
                quest_stage_id: "s1",
                name: "Opening",
                description: "Where it begins.",
                stage_type: "sequential",
                sequence_number: 1,
                objectives: [questObjective("o1", "Find the map"), questObjective("o2", "Reach the ruin")],
            },
        ],
        canon_status: "draft",
        lifecycle_status: "active",
        row_version: 4,
        available_actions: [...FREE_ACTIONS, "submit_for_review"],
        blocked_actions: [],
        field_locks: [],
        ...overrides,
    }
}

const scopeObjective = (id: string, name: string, status: string | null, next: string[]) => ({
    quest_objective_id: id,
    name,
    stage_name: "Opening",
    requirement_level: "required",
    status,
    next_statuses: next,
})

export function questProgress(overrides: Record<string, unknown> = {}, party: object | null = null) {
    return {
        quest_id: "q1",
        name: "The Lost Amulet",
        published: true,
        scopes: [
            {
                party_id: null,
                party_name: null,
                status: "active",
                actions: ["complete", "fail", "suspend", "abandon"],
                all_required_complete: false,
                objectives: [
                    scopeObjective("o1", "Find the map", "completed", []),
                    scopeObjective("o2", "Reach the ruin", null, ["available", "active", "completed", "failed", "skipped"]),
                ],
                ...overrides,
            },
            ...(party === null ? [] : [party]),
        ],
    }
}

export const AUTHORING = "/campaigns/c1/authoring/quests"
export const RUNTIME = "/campaigns/c1/quests/q1"

export interface QuestWorkspaceSetup {
    view?: object
    // The section in the address; null opens the bare address.
    section?: string | null
    // Overrides the lifecycle read (its status follows the view unless named here).
    lifecycle?: Record<string, unknown>
    progress?: object
    capabilities?: string[]
    entry?: string | { pathname: string; search?: string; state?: unknown }
    // The lifecycle read fails with a server error.
    lifecycleError?: boolean
}

export function setupQuestWorkspace(setup: QuestWorkspaceSetup = {}) {
    const server = installMockServer()
    let current: Record<string, unknown> = (setup.view ?? questView()) as Record<string, unknown>
    let lifecycle: Record<string, unknown> | null = null
    let progress: object = setup.progress ?? questProgress()
    const lifecycleBody = () => ({
        entity_id: "q1",
        entity_type_code: "quest",
        canonical_name: String(current.name),
        canon_status: current.canon_status,
        lifecycle_status: current.lifecycle_status,
        row_version: current.row_version,
        lifecycle_managed: true,
        superseded_by: null,
        available_actions: [],
        blocked_actions: [],
        ...setup.lifecycle,
        ...lifecycle,
    })
    server.on("GET", `${AUTHORING}/q1`, () => ({ body: current }))
    server.on("GET", `${AUTHORING}/options`, { body: QUEST_OPTIONS })
    server.on("GET", /target-options/, { body: { items: [], next_cursor: null } })
    server.on("GET", /\/entities\/q1\/lifecycle$/, () =>
        setup.lifecycleError === true
            ? { status: 500, body: { error: { code: "internal_error", message: "m", correlation_id: "c" } } }
            : { body: lifecycleBody() },
    )
    server.on("GET", `${RUNTIME}/progress`, () => ({ body: progress }))
    installRecordReads(server, { campaignId: "c1", entityId: "q1", name: "The Lost Amulet", entityTypeCode: "quest" })
    // Every successful command bumps the version and applies its change to the view the next read returns.
    const commit = (mutate: (draft: Record<string, unknown>) => void = () => {}) => {
        current = { ...current, row_version: (current.row_version as number) + 1 }
        mutate(current)
        return { body: { ...current, changed: true } }
    }
    server.on("POST", new RegExp(`${AUTHORING}/q1/`), () => commit())
    const section = setup.section === undefined ? "structure" : setup.section
    const rendered = renderAuthoringRoutes({
        initialEntry: setup.entry ?? `/app/c1/quests/q1${section === null ? "" : `?section=${section}`}`,
        bootstrap: bootstrapWith({
            campaigns: [
                {
                    ...sessionBootstrapFixture.campaigns[0]!,
                    campaign_id: "c1",
                    capabilities: setup.capabilities ?? ["canon.edit"],
                },
            ],
        }),
        routes: [
            { path: "/app/:campaignId/quests/:questId", element: <CampaignQuestDetailPage /> },
            { path: "/app/:campaignId/quests", element: <p>Quests list page</p> },
            { path: "/app/:campaignId/review", element: <p>Review queue page</p> },
        ],
    })
    return {
        server,
        commit,
        setView: (next: object) => (current = next as Record<string, unknown>),
        setLifecycle: (next: Record<string, unknown>) => (lifecycle = next),
        setProgress: (next: object) => (progress = next),
        ...rendered,
    }
}
