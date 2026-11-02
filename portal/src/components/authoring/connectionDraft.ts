import type { ConnectionFields, ConnectionView } from "../../types/dungeonAuthoring"

export interface ConnectionDraft {
    kind: string
    oneWay: string
    hidden: string
    description: string
    conditional: string
    condition: string
    [field: string]: string
}

export const EMPTY_CONNECTION: ConnectionDraft = {
    kind: "",
    oneWay: "no",
    hidden: "no",
    description: "",
    conditional: "no",
    condition: "",
}

export function connectionDraftOf(connection: ConnectionView): ConnectionDraft {
    return {
        kind: connection.connection_type,
        oneWay: connection.is_one_way ? "yes" : "no",
        hidden: connection.is_hidden ? "yes" : "no",
        description: connection.description ?? "",
        conditional: connection.is_conditional ? "yes" : "no",
        condition: connection.condition_description ?? "",
    }
}

export function connectionFields(draft: ConnectionDraft): ConnectionFields {
    return {
        connection_type: draft.kind,
        is_one_way: draft.oneWay === "yes",
        is_hidden: draft.hidden === "yes",
        description: draft.description.trim() === "" ? null : draft.description.trim(),
        is_conditional: draft.conditional === "yes",
        condition_description:
            draft.conditional === "yes" && draft.condition.trim() !== "" ? draft.condition.trim() : null,
    }
}

// The reason a connection draft cannot be sent, or null.
export function connectionProblem(draft: ConnectionDraft): string | null {
    if (draft.kind === "") return "Choose a kind."
    if (draft.conditional === "yes" && draft.condition.trim() === "") return "Describe the condition."
    return null
}
