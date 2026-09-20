import { useId, useState } from "react"
import { useUpdateAccessGroup } from "../hooks/useUpdateAccessGroup"

interface EditAccessGroupProps {
    campaignId: string
    accessGroupId: string
    currentName: string
    currentDescription: string | null
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Saving access group…"
        case "success":
            return "Access group updated."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This group changed elsewhere, or that name is already in use. Reload the page to see the current state."
        case "error":
            return "The access group could not be updated. Try again."
    }
}

// One control per group — renames/redescribes only; membership and grants
// are managed by their own separate controls. Client-side mirrors the
// server's own two rules (non-blank name, must actually change something)
// so a no-op or empty submission never round-trips.
export function EditAccessGroup({
    campaignId,
    accessGroupId,
    currentName,
    currentDescription,
    onChanged,
    onMutationStart,
}: EditAccessGroupProps) {
    const nameInputId = useId()
    const descriptionInputId = useId()
    const statusId = useId()

    const [isEditing, setIsEditing] = useState(false)
    const [name, setName] = useState(currentName)
    const [description, setDescription] = useState(currentDescription ?? "")

    const { status, submit, reset } = useUpdateAccessGroup(campaignId, () =>
        onChanged("Access group updated."),
    )

    const isPending = status.kind === "pending"
    const trimmedName = name.trim()
    const trimmedDescription = description.trim() === "" ? null : description.trim()
    const isUnchanged =
        trimmedName === currentName && trimmedDescription === currentDescription

    if (!isEditing) {
        return (
            <button
                type="button"
                className="access-role-editor__trigger"
                onClick={() => {
                    reset()
                    setName(currentName)
                    setDescription(currentDescription ?? "")
                    setIsEditing(true)
                }}
            >
                Edit
            </button>
        )
    }

    return (
        <form
            className="access-role-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (trimmedName === "" || isUnchanged) {
                    return
                }
                onMutationStart()
                submit(accessGroupId, trimmedName, trimmedDescription)
            }}
        >
            <label htmlFor={nameInputId}>Access group name</label>
            <input
                id={nameInputId}
                type="text"
                value={name}
                disabled={isPending}
                maxLength={200}
                onChange={(event) => {
                    setName(event.currentTarget.value)
                }}
            />

            <label htmlFor={descriptionInputId}>
                Description (optional)
            </label>
            <textarea
                id={descriptionInputId}
                value={description}
                disabled={isPending}
                onChange={(event) => {
                    setDescription(event.currentTarget.value)
                }}
            />

            <div className="access-role-editor__actions">
                <button
                    type="submit"
                    disabled={isPending || trimmedName === "" || isUnchanged}
                    aria-busy={isPending}
                >
                    {isPending ? "Saving…" : "Save"}
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
