// Dungeon, area and structural-child authoring contracts (Phase 15 checkpoint 15.3A-1).

import type { AuthoringReadModel, EntityReferenceSummary } from "./contentAuthoring"

export interface DungeonChoice {
    value: string
    label: string
}

export interface DungeonOptions {
    can_create: boolean
    connection_types: DungeonChoice[]
    limits: {
        name_max_length: number
        summary_max_length: number
        short_text_max_length: number
        notes_max_length: number
        change_note_max_length: number
        rating_min: number
        rating_max: number
        alarm_level_max: number
    }
}

export interface AreaSummary {
    dungeon_area_id: string
    name: string
    area_type: string | null
    canon_status: string
    lifecycle_status: string
    row_version: number
    feature_count: number
    hazard_count: number
    interactable_count: number
}

export interface ConnectionView {
    area_connection_id: string
    from_area: EntityReferenceSummary
    to_area: EntityReferenceSummary
    connection_type: string
    connection_type_label: string
    is_one_way: boolean
    is_hidden: boolean
    description: string | null
    is_conditional: boolean
    condition_description: string | null
    status: string | null
    state_event_id: string | null
}

export interface DungeonAuthoringView extends AuthoringReadModel {
    dungeon_id: string
    name: string
    summary: string | null
    danger_level: number | null
    parent: EntityReferenceSummary | null
    areas: AreaSummary[]
    connections: ConnectionView[]
}

export type ChildKind = "feature" | "hazard" | "interactable"

export interface ChildView {
    kind: ChildKind
    child_id: string
    child_type: string | null
    description: string | null
    is_hidden: boolean
    severity: number | null
    status: string | null
    is_destroyed: boolean | null
    condition_notes: string | null
    state_event_id: string | null
}

export interface AreaStateView {
    is_searched: boolean
    is_destroyed: boolean
    alarm_level: number
    condition_notes: string | null
    state_event_id: string | null
}

export interface AreaAuthoringView extends AuthoringReadModel {
    dungeon_area_id: string
    name: string
    summary: string | null
    area_type: string | null
    dimensions: string | null
    environmental_properties: string | null
    dungeon: EntityReferenceSummary
    dungeon_row_version: number
    structure_actions: string[]
    features: ChildView[]
    hazards: ChildView[]
    interactables: ChildView[]
    connections: ConnectionView[]
    state: AreaStateView
    can_set_state: boolean
    state_choices: Record<string, DungeonChoice[]>
}

export interface DungeonFieldsBody {
    name: string
    summary: string | null
    danger_level: number | null
    parent_location_id: string | null
}

export interface AreaFieldsBody {
    name: string
    summary: string | null
    area_type: string | null
    dimensions: string | null
    environmental_properties: string | null
}

export interface ConnectionFields {
    connection_type: string
    is_one_way: boolean
    is_hidden: boolean
    description: string | null
    is_conditional: boolean
    condition_description: string | null
}

export interface ChildFields {
    child_type: string | null
    description: string | null
    is_hidden: boolean
    severity: number | null
}

export type StateKind = "area" | "connection" | "feature" | "hazard" | "interactable"

export interface SetStateBody {
    kind: StateKind
    target_id: string
    expected_last_event_id: string | null
    is_searched?: boolean
    is_destroyed?: boolean
    alarm_level?: number
    condition_notes?: string | null
    connection_status?: string
    hazard_status?: string
    interactable_status?: string
}

export interface StateReceipt {
    dungeon_area_id: string
    kind: StateKind
    target_id: string
    changed: boolean
    event_id?: string
}

export type DungeonCommand =
    | { op: "add_area"; body: { name: string; area_type: string | null } }
    | {
          op: "add_connection"
          body: ConnectionFields & {
              expected_row_version: number
              from_area_id: string
              to_area_id: string
          }
      }
    | {
          op: "update_connection"
          connectionId: string
          body: ConnectionFields & { expected_row_version: number }
      }
    | { op: "remove_connection"; connectionId: string; expected_row_version: number }
    | {
          op: "add_child"
          kind: ChildKind
          body: ChildFields & { expected_row_version: number; dungeon_area_id: string }
      }
    | {
          op: "update_child"
          kind: ChildKind
          childId: string
          body: ChildFields & { expected_row_version: number }
      }
    | { op: "remove_child"; kind: ChildKind; childId: string; expected_row_version: number }
    | { op: "set_state"; body: SetStateBody }
