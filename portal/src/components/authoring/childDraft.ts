import type { ChildFields, ChildKind, ChildView } from "../../types/dungeonAuthoring"

// What a feature, hazard or interactable form holds. A hazard alone has a severity.
export interface ChildDraft {
    childType: string
    description: string
    hidden: string
    severity: string
    [field: string]: string
}

export const EMPTY_CHILD: ChildDraft = { childType: "", description: "", hidden: "no", severity: "" }

export function childDraftOf(child: ChildView): ChildDraft {
    return {
        childType: child.child_type ?? "",
        description: child.description ?? "",
        hidden: child.is_hidden ? "yes" : "no",
        severity: child.severity === null ? "" : String(child.severity),
    }
}

// The reason a child draft cannot be sent, or null.
export function childProblem(draft: ChildDraft, kind: ChildKind, min: number, max: number): string | null {
    if (kind !== "hazard" || draft.severity.trim() === "") return null
    const rating = Number(draft.severity)
    return Number.isInteger(rating) && rating >= min && rating <= max
        ? null
        : `Severity is a whole number from ${min} to ${max}.`
}

export function childFields(draft: ChildDraft, kind: ChildKind): ChildFields {
    return {
        child_type: draft.childType.trim() === "" ? null : draft.childType.trim(),
        description: draft.description.trim() === "" ? null : draft.description.trim(),
        is_hidden: draft.hidden === "yes",
        severity: kind === "hazard" && draft.severity.trim() !== "" ? Number(draft.severity) : null,
    }
}

export const CHILD_KINDS: { kind: ChildKind; plural: string; singular: string; typeLabel: string }[] = [
    { kind: "feature", plural: "Features", singular: "feature", typeLabel: "Kind of feature" },
    { kind: "hazard", plural: "Hazards", singular: "hazard", typeLabel: "Kind of hazard" },
    { kind: "interactable", plural: "Interactables", singular: "interactable", typeLabel: "Kind of interactable" },
]
