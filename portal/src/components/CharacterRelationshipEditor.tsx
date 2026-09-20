import { useId, useState } from "react"
import { useChangeCharacterRelationship } from "../hooks/useChangeCharacterRelationship"
import type {
    AccessCharacterRelationshipSummary,
    AssignableCharacterRelationshipType,
} from "../types/accessOverview"

interface CharacterRelationshipEditorProps {
    campaignId: string
    campaignName: string
    memberDisplayName: string
    relationship: AccessCharacterRelationshipSummary
    assignableRelationshipTypes: AssignableCharacterRelationshipType[]
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(
    kind:
        | "pending"
        | "success"
        | "denied"
        | "conflict"
        | "validation"
        | "error",
): string {
    switch (kind) {
        case "pending":
            return "Saving relationship type change…"
        case "success":
            return "Relationship type updated."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This character relationship changed elsewhere. Reload the page to see the current state."
        case "validation":
            return "That relationship type can no longer be assigned. Reload the page to see the current choices."
        case "error":
            return "The relationship type change could not be saved. Try again."
    }
}

// One editor per currently active character relationship (never per
// member): the backend contract changes exactly one `membership_
// character_relationship_id` at a time, so the UI never offers a single
// control that could silently replace every relationship a member holds —
// see dnd_ai.commands.access_grants.change_character_relationship's own
// docstring.
export function CharacterRelationshipEditor({
    campaignId,
    campaignName,
    memberDisplayName,
    relationship,
    assignableRelationshipTypes,
    onChanged,
    onMutationStart,
}: CharacterRelationshipEditorProps) {
    const selectId = useId()
    const statusId = useId()

    const [isEditing, setIsEditing] = useState(false)

    const currentTypeId =
        assignableRelationshipTypes.find(
            (type) => type.code === relationship.relationship_type_code,
        )?.character_relationship_type_id ?? ""

    const [selectedTypeId, setSelectedTypeId] = useState(currentTypeId)

    const { status, submit, reset } = useChangeCharacterRelationship(
        campaignId,
        () => onChanged("Relationship type updated."),
    )

    const isPending = status.kind === "pending"
    // Selecting the type the relationship already holds is not a change at
    // all — disabled here so the no-op never reaches the server in the
    // first place; dnd_ai.commands.access_grants.
    // change_character_relationship still rejects it server-side (422) as
    // defense in depth.
    const isUnchangedSelection = selectedTypeId === currentTypeId

    if (assignableRelationshipTypes.length === 0) {
        // Nothing the contract marks as an eligible replacement type —
        // never show a control with nowhere safe to send it.
        return null
    }

    if (!isEditing) {
        return (
            <button
                type="button"
                className="access-role-editor__trigger"
                onClick={() => {
                    reset()
                    setSelectedTypeId(currentTypeId)
                    setIsEditing(true)
                }}
            >
                Change type
            </button>
        )
    }

    return (
        <form
            className="access-role-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (isUnchangedSelection || selectedTypeId === "") {
                    return
                }
                onMutationStart()
                submit(
                    relationship.membership_character_relationship_id,
                    selectedTypeId,
                )
            }}
        >
            <label htmlFor={selectId}>
                Change {memberDisplayName}'s{" "}
                {relationship.character_display_name} relationship type in{" "}
                {campaignName}
            </label>

            <select
                id={selectId}
                value={selectedTypeId}
                disabled={isPending}
                onChange={(event) => {
                    setSelectedTypeId(event.currentTarget.value)
                }}
            >
                {assignableRelationshipTypes.map((type) => (
                    <option
                        key={type.character_relationship_type_id}
                        value={type.character_relationship_type_id}
                    >
                        {type.display_name}
                    </option>
                ))}
            </select>

            <div className="access-role-editor__actions">
                <button
                    type="submit"
                    disabled={isPending || isUnchangedSelection}
                    aria-busy={isPending}
                >
                    {isPending ? "Saving…" : "Save"}
                </button>

                <button
                    type="button"
                    disabled={isPending}
                    onClick={() => {
                        reset()
                        setSelectedTypeId(currentTypeId)
                        setIsEditing(false)
                    }}
                >
                    Cancel
                </button>
            </div>

            <p
                id={statusId}
                className={
                    status.kind === "denied" ||
                    status.kind === "conflict" ||
                    status.kind === "validation" ||
                    status.kind === "error"
                        ? "access-role-editor__status access-role-editor__status--error"
                        : "access-role-editor__status"
                }
                role="status"
                aria-live="polite"
            >
                {status.kind === "idle" ? "" : statusMessage(status.kind)}
            </p>
        </form>
    )
}
