import { useId, useState } from "react"
import { useCreateAccessGroup } from "../hooks/useCreateAccessGroup"

// Mirrors dnd_ai.commands.access_groups.ACCESS_GROUP_NAME_MAX_LENGTH/
// ACCESS_GROUP_DESCRIPTION_MAX_LENGTH exactly — the server remains
// authoritative (both are re-enforced there, at the Pydantic and command
// layers), but matching bounds here means a caller sees the rejection
// before ever submitting rather than after a round trip.
const NAME_MAX_LENGTH = 200
const DESCRIPTION_MAX_LENGTH = 2000

interface CreateAccessGroupProps {
    campaignId: string
    campaignName: string
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Creating access group…"
        case "success":
            return "Access group created."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "An access group with that name already exists, or the campaign is not currently active."
        case "error":
            return "The access group could not be created. Try again."
    }
}

// One control for the whole "Access groups" section (never per-group) —
// "create a group" names no existing group to act on. Client-side name
// validation (trim, non-blank) mirrors the server's own rule so an empty
// submission never round-trips; the server remains authoritative regardless
// (dnd_ai.commands.access_groups.create_access_group).
export function CreateAccessGroup({
    campaignId,
    campaignName,
    onChanged,
    onMutationStart,
}: CreateAccessGroupProps) {
    const nameInputId = useId()
    const descriptionInputId = useId()
    const statusId = useId()

    const [isEditing, setIsEditing] = useState(false)
    const [name, setName] = useState("")
    const [description, setDescription] = useState("")

    const { status, submit, reset } = useCreateAccessGroup(campaignId, () =>
        onChanged("Access group created."),
    )

    const isPending = status.kind === "pending"
    const trimmedName = name.trim()
    const isNameTooLong = trimmedName.length > NAME_MAX_LENGTH
    const trimmedDescription = description.trim()
    const isDescriptionTooLong = trimmedDescription.length > DESCRIPTION_MAX_LENGTH

    if (!isEditing) {
        return (
            <button
                type="button"
                className="access-role-editor__trigger"
                onClick={() => {
                    reset()
                    setName("")
                    setDescription("")
                    setIsEditing(true)
                }}
            >
                Create access group
            </button>
        )
    }

    return (
        <form
            className="access-role-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (trimmedName === "" || isNameTooLong || isDescriptionTooLong) {
                    return
                }
                onMutationStart()
                submit(trimmedName, trimmedDescription === "" ? null : trimmedDescription)
            }}
        >
            <label htmlFor={nameInputId}>
                New access group name in {campaignName}
            </label>
            <input
                id={nameInputId}
                type="text"
                value={name}
                disabled={isPending}
                maxLength={NAME_MAX_LENGTH}
                onChange={(event) => {
                    setName(event.currentTarget.value)
                }}
            />
            {isNameTooLong && (
                <p role="alert">
                    Access group name must be {NAME_MAX_LENGTH} characters or fewer.
                </p>
            )}

            <label htmlFor={descriptionInputId}>
                Description (optional)
            </label>
            <textarea
                id={descriptionInputId}
                value={description}
                disabled={isPending}
                maxLength={DESCRIPTION_MAX_LENGTH}
                onChange={(event) => {
                    setDescription(event.currentTarget.value)
                }}
            />
            {isDescriptionTooLong && (
                <p role="alert">
                    Description must be {DESCRIPTION_MAX_LENGTH} characters or fewer.
                </p>
            )}

            <div className="access-role-editor__actions">
                <button
                    type="submit"
                    disabled={
                        isPending ||
                        trimmedName === "" ||
                        isNameTooLong ||
                        isDescriptionTooLong
                    }
                    aria-busy={isPending}
                >
                    {isPending ? "Creating…" : "Save"}
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
