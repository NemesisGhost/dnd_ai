import type {
    AreaAuthoringView,
    AreaFieldsBody,
    DungeonAuthoringView,
    DungeonCommand,
    DungeonFieldsBody,
    StateReceipt,
} from "../types/dungeonAuthoring"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

function base(campaignId: string): string {
    return `/campaigns/${enc(campaignId)}/authoring`
}

export const dungeonOptionsPath = (campaignId: string): string =>
    `${base(campaignId)}/dungeons/options`

export const dungeonAuthoringPath = (campaignId: string, dungeonId: string): string =>
    `${base(campaignId)}/dungeons/${enc(dungeonId)}`

export const areaAuthoringPath = (campaignId: string, areaId: string): string =>
    `${base(campaignId)}/dungeon-areas/${enc(areaId)}`

const KIND_PATH = { feature: "features", hazard: "hazards", interactable: "interactables" } as const

export function createDungeon(
    campaignId: string,
    body: DungeonFieldsBody,
    ctx: MutationContext,
): Promise<DungeonAuthoringView> {
    return apiRequest<DungeonAuthoringView>("POST", `${base(campaignId)}/dungeons`, {
        body,
        ...ctx,
    })
}

export function updateDungeon(
    campaignId: string,
    dungeonId: string,
    body: DungeonFieldsBody & { expected_row_version: number; change_note: string | null },
    ctx: MutationContext,
): Promise<DungeonAuthoringView> {
    return apiRequest<DungeonAuthoringView>(
        "POST",
        `${dungeonAuthoringPath(campaignId, dungeonId)}/update`,
        { body, ...ctx },
    )
}

export function updateArea(
    campaignId: string,
    areaId: string,
    body: AreaFieldsBody & { expected_row_version: number; change_note: string | null },
    ctx: MutationContext,
): Promise<AreaAuthoringView> {
    return apiRequest<AreaAuthoringView>("POST", `${areaAuthoringPath(campaignId, areaId)}/update`, {
        body,
        ...ctx,
    })
}

// One structural command on a dungeon (its areas, connections and children), or a state change.
export function runDungeonCommand(
    campaignId: string,
    dungeonId: string,
    areaId: string | null,
    command: DungeonCommand,
    ctx: MutationContext,
): Promise<unknown> {
    const dungeon = dungeonAuthoringPath(campaignId, dungeonId)
    const post = (path: string, body: unknown) =>
        apiRequest<unknown>("POST", path, { body, ...ctx })
    switch (command.op) {
        case "add_area":
            return post(`${dungeon}/areas`, command.body)
        case "add_connection":
            return post(`${dungeon}/connections`, command.body)
        case "update_connection":
            return post(`${dungeon}/connections/${enc(command.connectionId)}/update`, command.body)
        case "remove_connection":
            return post(`${dungeon}/connections/${enc(command.connectionId)}/remove`, {
                expected_row_version: command.expected_row_version,
            })
        case "add_child":
            return post(`${dungeon}/${KIND_PATH[command.kind]}`, command.body)
        case "update_child":
            return post(
                `${dungeon}/${KIND_PATH[command.kind]}/${enc(command.childId)}/update`,
                command.body,
            )
        case "remove_child":
            return post(`${dungeon}/${KIND_PATH[command.kind]}/${enc(command.childId)}/remove`, {
                expected_row_version: command.expected_row_version,
            })
        case "set_state":
            return apiRequest<StateReceipt>(
                "POST",
                `/campaigns/${enc(campaignId)}/dungeon-areas/${enc(areaId ?? "")}/state`,
                { body: command.body, ...ctx },
            )
    }
}
