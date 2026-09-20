import { useId, useState } from "react"
import { useAddCampaignMember } from "../hooks/useAddCampaignMember"
import { useEligibleAccountLookup } from "../hooks/useEligibleAccountLookup"
import type { AssignableRole } from "../types/accessOverview"

interface AddCampaignMemberProps {
    campaignId: string
    campaignName: string
    assignableRoles: AssignableRole[]
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function lookupStatusMessage(
    kind: "pending" | "not_found" | "denied" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Looking up account…"
        case "not_found":
            return "No eligible account found for that login name."
        case "denied":
            return "You do not have permission to look up accounts."
        case "error":
            return "The account lookup failed. Try again."
    }
}

function addStatusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Adding member…"
        case "success":
            return "Member added."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This account can no longer be added — it may already be a member, or the campaign or role may no longer be available. Reload the page to see the current state."
        case "error":
            return "The member could not be added. Try again."
    }
}

// One control for the whole Access page (never per-member, unlike
// AddMemberRole/RevokeMemberRole below it): "add a campaign member" names
// an *existing* account to select, not an existing membership to act on.
// Never implies account creation or invitations — the lookup step only
// ever resolves an already-existing, eligible account
// (dnd_ai.queries.access_overview.find_eligible_campaign_account's own
// exact-match, non-directory design).
export function AddCampaignMember({
    campaignId,
    campaignName,
    assignableRoles,
    onChanged,
    onMutationStart,
}: AddCampaignMemberProps) {
    const loginNameInputId = useId()
    const roleSelectId = useId()
    const lookupStatusId = useId()
    const addStatusId = useId()

    const [isEditing, setIsEditing] = useState(false)
    const [loginName, setLoginName] = useState("")
    const [selectedRoleId, setSelectedRoleId] = useState(
        assignableRoles[0]?.role_id ?? "",
    )

    const {
        status: lookupStatus,
        lookup,
        reset: resetLookup,
    } = useEligibleAccountLookup(campaignId)

    const { status: addStatus, submit, reset: resetAdd } =
        useAddCampaignMember(campaignId, () =>
            onChanged("Member added."),
        )

    const isLookupPending = lookupStatus.kind === "pending"
    const isAddPending = addStatus.kind === "pending"
    const isPending = isLookupPending || isAddPending

    if (assignableRoles.length === 0) {
        // No role this campaign could offer as an initial assignment —
        // never show a control that could never complete.
        return null
    }

    function closeAndReset(): void {
        resetLookup()
        resetAdd()
        setLoginName("")
        setSelectedRoleId(assignableRoles[0]?.role_id ?? "")
        setIsEditing(false)
    }

    if (!isEditing) {
        return (
            <button
                type="button"
                className="access-role-editor__trigger"
                onClick={() => {
                    resetLookup()
                    resetAdd()
                    setLoginName("")
                    setSelectedRoleId(
                        assignableRoles[0]?.role_id ?? "",
                    )
                    setIsEditing(true)
                }}
            >
                Add campaign member
            </button>
        )
    }

    const foundAccount =
        lookupStatus.kind === "found"
            ? lookupStatus.account
            : null

    const canSave =
        foundAccount !== null &&
        selectedRoleId !== "" &&
        !isPending

    return (
        <form
            className="access-add-member"
            aria-label={`Add a campaign member to ${campaignName}`}
            onSubmit={(event) => {
                event.preventDefault()
                if (foundAccount === null) {
                    lookup(loginName)
                    return
                }
                if (!canSave) {
                    return
                }
                onMutationStart()
                submit(foundAccount.user_id, selectedRoleId)
            }}
        >
            <div className="access-add-member__field">
                <label htmlFor={loginNameInputId}>
                    Login name
                </label>
                <input
                    id={loginNameInputId}
                    type="text"
                    value={loginName}
                    disabled={isPending}
                    autoComplete="off"
                    onChange={(event) => {
                        setLoginName(event.currentTarget.value)
                        if (lookupStatus.kind !== "idle") {
                            resetLookup()
                        }
                    }}
                    aria-describedby={lookupStatusId}
                />
                <button
                    type="button"
                    disabled={
                        isPending || loginName.trim() === ""
                    }
                    onClick={() => lookup(loginName)}
                >
                    {isLookupPending
                        ? "Looking up…"
                        : "Find account"}
                </button>
            </div>

            <p
                id={lookupStatusId}
                className={
                    lookupStatus.kind === "denied" ||
                    lookupStatus.kind === "error"
                        ? "access-role-editor__status access-role-editor__status--error"
                        : "access-role-editor__status"
                }
                role="status"
                aria-live="polite"
            >
                {lookupStatus.kind === "idle" ||
                lookupStatus.kind === "found"
                    ? ""
                    : lookupStatusMessage(lookupStatus.kind)}
            </p>

            {foundAccount !== null && (
                <div className="access-add-member__field">
                    <p>
                        Selected account:{" "}
                        <strong>
                            {foundAccount.display_name}
                        </strong>
                    </p>

                    <label htmlFor={roleSelectId}>
                        Initial role
                    </label>
                    <select
                        id={roleSelectId}
                        value={selectedRoleId}
                        disabled={isPending}
                        onChange={(event) => {
                            setSelectedRoleId(
                                event.currentTarget.value,
                            )
                        }}
                    >
                        {assignableRoles.map((role) => (
                            <option
                                key={role.role_id}
                                value={role.role_id}
                            >
                                {role.display_name}
                            </option>
                        ))}
                    </select>
                </div>
            )}

            <div className="access-role-editor__actions">
                {foundAccount !== null && (
                    <button
                        type="submit"
                        disabled={!canSave}
                        aria-busy={isAddPending}
                    >
                        {isAddPending ? "Adding…" : "Save"}
                    </button>
                )}
                <button
                    type="button"
                    disabled={isPending}
                    onClick={closeAndReset}
                >
                    Cancel
                </button>
            </div>

            <p
                id={addStatusId}
                className={
                    addStatus.kind === "denied" ||
                    addStatus.kind === "conflict" ||
                    addStatus.kind === "error"
                        ? "access-role-editor__status access-role-editor__status--error"
                        : "access-role-editor__status"
                }
                role="status"
                aria-live="polite"
            >
                {addStatus.kind === "idle"
                    ? ""
                    : addStatusMessage(addStatus.kind)}
            </p>
        </form>
    )
}
