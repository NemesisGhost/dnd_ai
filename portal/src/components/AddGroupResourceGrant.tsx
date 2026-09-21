import { useId, useState } from "react"
import { useAddGroupResourceGrant } from "../hooks/useAddGroupResourceGrant"
import type {
    AccessResourceGrantSummary,
    AssignableCharacter,
} from "../types/accessOverview"

interface AddGroupResourceGrantProps {
    campaignId: string
    accessGroupId: string
    groupName: string
    assignableCharacters: AssignableCharacter[]
    grantableCapabilityCodes: { code: string; display_name: string }[]
    existingGrants: AccessResourceGrantSummary[]
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Adding resource access…"
        case "success":
            return "Resource access added."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This group's resource access changed elsewhere, or the group is not currently active. Reload the page to see the current state."
        case "error":
            return "The resource access could not be added. Try again."
    }
}

// One control per group — character-target, allow-effect only, the
// identical portal scope ../components/AddResourceGrant.tsx already
// applies to a member grantee (see dnd_ai.commands.access_grants' own
// module docstring for why the other five target kinds, and an explicit
// deny effect, are deferred). Resource type is fixed to "Character" —
// never offered as a choice — since that is the only target kind this
// portal has a safe display/search contract for.
export function AddGroupResourceGrant({
    campaignId,
    accessGroupId,
    groupName,
    assignableCharacters,
    grantableCapabilityCodes,
    existingGrants,
    onChanged,
    onMutationStart,
}: AddGroupResourceGrantProps) {
    const characterSelectId = useId()
    const capabilitySelectId = useId()
    const statusId = useId()

    const [isEditing, setIsEditing] = useState(false)
    const [selectedCharacter, setSelectedCharacter] = useState(
        assignableCharacters[0]?.character_id ?? "",
    )
    const [selectedCapability, setSelectedCapability] = useState<{
        characterId: string
        code: string
    }>({ characterId: "", code: "" })

    const { status, submit, reset } = useAddGroupResourceGrant(
        campaignId,
        () => onChanged("Resource access added."),
    )

    const isPending = status.kind === "pending"

    const activeCapabilityCodesForSelectedCharacter = new Set(
        existingGrants
            .filter(
                (grant) =>
                    grant.target_type === "character" &&
                    grant.target_id === selectedCharacter &&
                    grant.effect === "allow",
            )
            .map((grant) => grant.capability_code),
    )
    const availableCapabilities = grantableCapabilityCodes.filter(
        (capability) =>
            !activeCapabilityCodesForSelectedCharacter.has(capability.code),
    )

    let selectedCapabilityCode = selectedCapability.code
    if (selectedCapability.characterId !== selectedCharacter) {
        selectedCapabilityCode = availableCapabilities[0]?.code ?? ""
        setSelectedCapability({
            characterId: selectedCharacter,
            code: selectedCapabilityCode,
        })
    }

    if (assignableCharacters.length === 0 || grantableCapabilityCodes.length === 0) {
        // Nothing eligible to target, or no character-target capability is
        // currently grantable at all — never show a control with nowhere
        // safe to send it.
        return null
    }

    if (!isEditing) {
        return (
            <button
                type="button"
                className="access-role-editor__trigger"
                onClick={() => {
                    reset()
                    setSelectedCharacter(
                        assignableCharacters[0]?.character_id ?? "",
                    )
                    setIsEditing(true)
                }}
            >
                Add resource access
            </button>
        )
    }

    return (
        <form
            className="access-role-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (selectedCharacter === "" || selectedCapabilityCode === "") {
                    return
                }
                onMutationStart()
                submit(accessGroupId, selectedCharacter, selectedCapabilityCode)
            }}
        >
            <label htmlFor={characterSelectId}>
                Add resource access for {groupName} — Character
            </label>

            <select
                id={characterSelectId}
                value={selectedCharacter}
                disabled={isPending}
                onChange={(event) => {
                    setSelectedCharacter(event.currentTarget.value)
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

            <label htmlFor={capabilitySelectId}>Permission</label>

            {availableCapabilities.length > 0 ? (
                <select
                    id={capabilitySelectId}
                    value={selectedCapabilityCode}
                    disabled={isPending}
                    onChange={(event) => {
                        setSelectedCapability({
                            characterId: selectedCharacter,
                            code: event.currentTarget.value,
                        })
                    }}
                >
                    {availableCapabilities.map((capability) => (
                        <option key={capability.code} value={capability.code}>
                            {capability.display_name}
                        </option>
                    ))}
                </select>
            ) : (
                <p>Every available permission is already granted for this character.</p>
            )}

            <div className="access-role-editor__actions">
                <button
                    type="submit"
                    disabled={
                        isPending ||
                        selectedCharacter === "" ||
                        selectedCapabilityCode === ""
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
