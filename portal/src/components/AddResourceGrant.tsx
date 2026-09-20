import { useId, useState } from "react"
import { useAddResourceGrant } from "../hooks/useAddResourceGrant"
import type {
    AccessResourceGrantSummary,
    AssignableCharacter,
    GrantableResourceCapability,
} from "../types/accessOverview"
import { humanizeCode } from "../utils/humanize"

interface AddResourceGrantProps {
    campaignId: string
    campaignName: string
    campaignMembershipId: string
    memberDisplayName: string
    assignableCharacters: AssignableCharacter[]
    grantableCapabilities: GrantableResourceCapability[]
    existingGrants: AccessResourceGrantSummary[]
    onChanged: (message: string) => void
    onMutationStart: () => void
}

interface ResourceOption {
    id: string
    display_name: string
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
            return "This member's resource access changed elsewhere. Reload the page to see the current state."
        case "error":
            return "The resource access could not be added. Try again."
    }
}

// Every resource type this checkpoint's portal knows how to safely search
// and display — currently just "character" (dnd_ai.queries.access_overview.
// list_assignable_campaign_characters). A future increment that adds a
// safe display/search contract for another target kind needs only a new
// case here, matching the equally general grantable_resource_capabilities
// metadata the server already returns for every kind it allows.
function resourceOptionsForType(
    targetType: string,
    assignableCharacters: AssignableCharacter[],
): ResourceOption[] {
    if (targetType === "character") {
        return assignableCharacters.map((character) => ({
            id: character.character_id,
            display_name: character.display_name,
        }))
    }
    return []
}

// One control per member (never per resource): "add resource access"
// names a member, a resource type, a specific resource, and a capability
// to grant. A guided, server-driven sequence — resource type, then
// resource, then capability — with each lower selection reset whenever a
// higher one changes, mirroring AddCharacterRelationship's own identical
// cascade for character/relationship-type. Capability choices are always
// narrowed to dnd_ai.domain.access.RESOURCE_GRANT_CAPABILITY_CATALOG (via
// the server-supplied grantableCapabilities list) and to whichever are not
// already actively granted for the *currently selected* resource — the
// server independently re-validates and enforces its own delegation
// policy regardless (dnd_ai.commands.access_grants.create_resource_grant).
export function AddResourceGrant({
    campaignId,
    campaignName,
    campaignMembershipId,
    memberDisplayName,
    assignableCharacters,
    grantableCapabilities,
    existingGrants,
    onChanged,
    onMutationStart,
}: AddResourceGrantProps) {
    const typeSelectId = useId()
    const resourceSelectId = useId()
    const capabilitySelectId = useId()
    const statusId = useId()

    const [isEditing, setIsEditing] = useState(false)

    const targetTypes = Array.from(
        new Set(grantableCapabilities.map((capability) => capability.target_type)),
    )

    const [selectedTargetType, setSelectedTargetType] = useState(
        targetTypes[0] ?? "",
    )

    // Tracks its own "which type was this chosen for" alongside the chosen
    // resource id, purely so a type change can be detected and reset
    // during render (React's own documented "adjusting state when a prop
    // changes" pattern) without an effect — mirrors AddCharacterRelationship's
    // identical character/type cascade, one level deeper here.
    const [selectedResource, setSelectedResource] = useState<{
        targetType: string
        id: string
    }>({ targetType: "", id: "" })
    const [selectedCapability, setSelectedCapability] = useState<{
        targetType: string
        resourceId: string
        code: string
    }>({ targetType: "", resourceId: "", code: "" })

    const { status, submit, reset } = useAddResourceGrant(campaignId, () =>
        onChanged("Resource access added."),
    )

    const isPending = status.kind === "pending"

    const resourceOptions = resourceOptionsForType(
        selectedTargetType,
        assignableCharacters,
    )

    let selectedResourceId = selectedResource.id
    if (selectedResource.targetType !== selectedTargetType) {
        selectedResourceId = resourceOptions[0]?.id ?? ""
        setSelectedResource({ targetType: selectedTargetType, id: selectedResourceId })
    }

    const capabilitiesForType = grantableCapabilities.filter(
        (capability) => capability.target_type === selectedTargetType,
    )
    const activeCapabilityCodesForSelectedResource = new Set(
        existingGrants
            .filter(
                (grant) =>
                    grant.target_type === selectedTargetType &&
                    grant.target_id === selectedResourceId &&
                    grant.effect === "allow",
            )
            .map((grant) => grant.capability_code),
    )
    const availableCapabilitiesForSelectedResource = capabilitiesForType.filter(
        (capability) => !activeCapabilityCodesForSelectedResource.has(capability.code),
    )

    let selectedCapabilityCode = selectedCapability.code
    if (
        selectedCapability.targetType !== selectedTargetType ||
        selectedCapability.resourceId !== selectedResourceId
    ) {
        selectedCapabilityCode =
            availableCapabilitiesForSelectedResource[0]?.code ?? ""
        setSelectedCapability({
            targetType: selectedTargetType,
            resourceId: selectedResourceId,
            code: selectedCapabilityCode,
        })
    }

    if (targetTypes.length === 0 || assignableCharacters.length === 0) {
        // Nothing the contract marks as a grantable capability, or nothing
        // eligible to target — never show a control with nowhere safe to
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
                    setSelectedTargetType(targetTypes[0] ?? "")
                    setIsEditing(true)
                }}
            >
                Add direct resource access
            </button>
        )
    }

    return (
        <form
            className="access-role-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (
                    selectedTargetType === "" ||
                    selectedResourceId === "" ||
                    selectedCapabilityCode === ""
                ) {
                    return
                }
                onMutationStart()
                submit(
                    campaignMembershipId,
                    selectedResourceId,
                    selectedCapabilityCode,
                )
            }}
        >
            <label htmlFor={typeSelectId}>
                Add direct resource access for {memberDisplayName} in{" "}
                {campaignName}
            </label>

            <select
                id={typeSelectId}
                value={selectedTargetType}
                disabled={isPending || targetTypes.length <= 1}
                onChange={(event) => {
                    setSelectedTargetType(event.currentTarget.value)
                }}
            >
                {targetTypes.map((targetType) => (
                    <option key={targetType} value={targetType}>
                        {humanizeCode(targetType)}
                    </option>
                ))}
            </select>

            <label htmlFor={resourceSelectId}>
                {humanizeCode(selectedTargetType)}
            </label>

            {resourceOptions.length > 0 ? (
                <select
                    id={resourceSelectId}
                    value={selectedResourceId}
                    disabled={isPending}
                    onChange={(event) => {
                        setSelectedResource({
                            targetType: selectedTargetType,
                            id: event.currentTarget.value,
                        })
                    }}
                >
                    {resourceOptions.map((resource) => (
                        <option key={resource.id} value={resource.id}>
                            {resource.display_name}
                        </option>
                    ))}
                </select>
            ) : (
                <p>No eligible resource of this type is available.</p>
            )}

            <label htmlFor={capabilitySelectId}>Permission</label>

            {availableCapabilitiesForSelectedResource.length > 0 ? (
                <select
                    id={capabilitySelectId}
                    value={selectedCapabilityCode}
                    disabled={isPending}
                    onChange={(event) => {
                        setSelectedCapability({
                            targetType: selectedTargetType,
                            resourceId: selectedResourceId,
                            code: event.currentTarget.value,
                        })
                    }}
                >
                    {availableCapabilitiesForSelectedResource.map((capability) => (
                        <option key={capability.code} value={capability.code}>
                            {capability.display_name}
                        </option>
                    ))}
                </select>
            ) : (
                <p>Every available permission is already granted for this resource.</p>
            )}

            <div className="access-role-editor__actions">
                <button
                    type="submit"
                    disabled={
                        isPending ||
                        selectedResourceId === "" ||
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
