import type { ReferenceOption } from "../components/authoring/ReferenceCombobox"
import type { FieldError } from "../components/authoring/feedback"
import type { KnowledgeAuthoringView, KnowledgeFieldsBody } from "../types/knowledgeAuthoring"
import { statusDetail } from "./locationForm"

// Form model shared by the "New knowledge claim" page and the claim page's editor.
export interface KnowledgeFormValues {
    statement: string
    knowledgeType: string
    truthStatus: string
    sensitivity: string
    subject: ReferenceOption | null
}

export const EMPTY: KnowledgeFormValues = {
    statement: "",
    knowledgeType: "",
    truthStatus: "",
    sensitivity: "",
    subject: null,
}

export const FIELD = {
    statement: "knowledge-statement",
    type: "knowledge-type",
    truth: "knowledge-truth",
    sensitivity: "knowledge-sensitivity",
    subject: "knowledge-subject",
} as const

export const STATEMENT_MAX = 4000

export function same(a: KnowledgeFormValues, b: KnowledgeFormValues): boolean {
    return (
        a.statement.trim() === b.statement.trim() &&
        a.knowledgeType === b.knowledgeType &&
        a.truthStatus === b.truthStatus &&
        a.sensitivity === b.sensitivity &&
        (a.subject?.id ?? null) === (b.subject?.id ?? null)
    )
}

export function validate(values: KnowledgeFormValues): FieldError[] {
    const errors: FieldError[] = []
    const statement = values.statement.trim()
    if (statement === "") {
        errors.push({ fieldId: FIELD.statement, message: "Statement is required." })
    } else if (statement.length > STATEMENT_MAX) {
        errors.push({
            fieldId: FIELD.statement,
            message: `Statement must be ${STATEMENT_MAX} characters or fewer.`,
        })
    }
    if (values.knowledgeType === "") errors.push({ fieldId: FIELD.type, message: "Choose a type." })
    if (values.truthStatus === "") {
        errors.push({ fieldId: FIELD.truth, message: "Choose whether the claim is true." })
    }
    if (values.sensitivity === "") {
        errors.push({ fieldId: FIELD.sensitivity, message: "Choose a sensitivity." })
    }
    return errors
}

export function toBody(values: KnowledgeFormValues): KnowledgeFieldsBody {
    return {
        statement: values.statement.trim(),
        knowledge_type: values.knowledgeType,
        truth_status: values.truthStatus,
        sensitivity: values.sensitivity,
        subject_entity_id: values.subject?.id ?? null,
    }
}

export function fromView(view: KnowledgeAuthoringView): KnowledgeFormValues {
    return {
        statement: view.statement,
        knowledgeType: view.knowledge_type,
        truthStatus: view.truth_status,
        sensitivity: view.sensitivity,
        subject:
            view.subject === null
                ? null
                : {
                      id: view.subject.entity_id,
                      label: view.subject.name,
                      detail: statusDetail(view.subject.canon_status, view.subject.lifecycle_status),
                  },
    }
}

