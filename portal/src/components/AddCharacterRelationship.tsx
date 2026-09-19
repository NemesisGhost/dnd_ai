import { useId, useState } from "react"
import { useAddCharacterRelationship } from "../hooks/useAddCharacterRelationship"
import type {
    AccessCharacterRelationshipSummary,
    AssignableCharacter,
    AssignableCharacterRelationshipType,
} from "../types/accessOverview"

interface AddCharacterRelationshipProps {
    campaignId: string
    campaignName: string
    campaignMembershipId: string
    memberDisplayName: string
    assignableCharacters: AssignableCharacter[]
    assignableRelationshipTypes: AssignableCharacterRelationshipType[]
    existingRelationships: AccessCharacterRelationshipSummary[]
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Adding character relationship…"
        case "success":
            return "Character relationship added."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This member's character relationships changed elsewhere. Reload the page to see the current state."
        case "error":
            return "The character relationship could not be added. Try again."
    }
}

// One control per member (never per character): "add a character
// relationship" names a member, a character, and a relationship type to
// add. The type choices offered are narrowed to whichever ones are not
// already active for the *currently selected* character — combinations
// already active are excluded per-character rather than merely disabled,
// since the server independently re-validates everything regardless
// (dnd_ai.commands.access_grants.grant_character_relationship).
export function AddCharacterRelationship({
    campaignId,
    campaignName,
    campaignMembershipId,
    memberDisplayName,
    assignableCharacters,
    assignableRelationshipTypes,
    existingRelationships,
    onChanged,
    onMutationStart,
}: AddCharacterRelationshipProps) {
    const characterSelectId = useId()
    const typeSelectId = useId()
    const statusId = useId()

    const [isEditing, setIsEditing] = useState(false)
    const [selectedCharacterId, setSelectedCharacterId] = useState(
        assignableCharacters[0]?.character_id ?? "",
    )
    // Tracks its own "which character was this chosen for" alongside the
    // chosen code, purely so a character change can be detected and reset
    // during render (React's own documented "adjusting state when a prop
    // changes" pattern) without an effect — a character change must never
    // briefly leave a now-invalid type code selected for the new
    // character.
    const [selectedType, setSelectedType] = useState<{
        characterId: string
        code: string
    }>({ characterId: "", code: "" })

    const { status, submit, reset } = useAddCharacterRelationship(
        campaignId,
        () => onChanged("Character relationship added."),
    )

    const isPending = status.kind === "pending"

    const activeTypeCodesForSelectedCharacter = new Set(
        existingRelationships
            .filter(
                (relationship) =>
                    relationship.character_id === selectedCharacterId,
            )
            .map((relationship) => relationship.relationship_type_code),
    )
    const availableTypesForSelectedCharacter =
        assignableRelationshipTypes.filter(
            (type) => !activeTypeCodesForSelectedCharacter.has(type.code),
        )

    let selectedRelationshipTypeCode = selectedType.code
    if (selectedType.characterId !== selectedCharacterId) {
        selectedRelationshipTypeCode =
            availableTypesForSelectedCharacter[0]?.code ?? ""
        setSelectedType({
            characterId: selectedCharacterId,
            code: selectedRelationshipTypeCode,
        })
    }

    if (assignableCharacters.length === 0 || assignableRelationshipTypes.length === 0) {
        // Nothing the contract marks as an eligible character or
        // relationship type — never show a control with nowhere safe to
        // send it.
        return null
    }

    if (!isEditing) {
        return (
            <button
                type="button"
                className="access-role-editor__trigger"
                onClick={() => {
                    reset()
                    setSelectedCharacterId(
                        assignableCharacters[0]?.character_id ?? "",
                    )
                    setIsEditing(true)
                }}
            >
                Add character relationship
            </button>
        )
    }

    return (
        <form
            className="access-role-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (
                    selectedCharacterId === "" ||
                    selectedRelationshipTypeCode === ""
                ) {
                    return
                }
                onMutationStart()
                submit(
                    campaignMembershipId,
                    selectedCharacterId,
                    selectedRelationshipTypeCode,
                )
            }}
        >
            <label htmlFor={characterSelectId}>
                Add a character relationship for {memberDisplayName} in{" "}
                {campaignName}
            </label>

            <select
                id={characterSelectId}
                value={selectedCharacterId}
                disabled={isPending}
                onChange={(event) => {
                    setSelectedCharacterId(event.currentTarget.value)
                }}
            >
                {assignableCharacters.map((character) => (
                    <option
                        key={character.character_id}
                        value={character.character_id}
                    >
                        {character.display_name}
                    </option>
                ))}
            </select>

            <label htmlFor={typeSelectId}>Relationship type</label>

            {availableTypesForSelectedCharacter.length > 0 ? (
                <select
                    id={typeSelectId}
                    value={selectedRelationshipTypeCode}
                    disabled={isPending}
                    onChange={(event) => {
                        setSelectedType({
                            characterId: selectedCharacterId,
                            code: event.currentTarget.value,
                        })
                    }}
                >
                    {availableTypesForSelectedCharacter.map((type) => (
                        <option key={type.code} value={type.code}>
                            {type.display_name}
                        </option>
                    ))}
                </select>
            ) : (
                <p>
                    Every relationship type is already active for this
                    character.
                </p>
            )}

            <div className="access-role-editor__actions">
                <button
                    type="submit"
                    disabled={
                        isPending ||
                        selectedCharacterId === "" ||
                        selectedRelationshipTypeCode === ""
                    }
                    aria-busy={isPending}
                >
                    {isPending ? "Adding…" : "Add"}
                </button>

                <button
                    type="button"
                    disabled={isPending}
                    onClick={() => {
                        reset()
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
