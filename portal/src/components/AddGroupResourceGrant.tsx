import { useId, useState } from "react"
import { ResourceTargetSelector } from "./ResourceTargetSelector"
import { useAddGroupResourceGrant } from "../hooks/useAddGroupResourceGrant"
import type {
    AccessResourceGrantSummary,
    AssignableCharacter,
    GrantableResourceCapability,
} from "../types/accessOverview"
import type { ResourceGrantEffect, ResourceGrantTargetField } from "../types/resourceGrantTarget"
import { humanizeCode } from "../utils/humanize"

interface AddGroupResourceGrantProps {
    campaignId: string
    accessGroupId: string
    groupName: string
    assignableCharacters: AssignableCharacter[]
    grantableCapabilities: GrantableResourceCapability[]
    existingGrants: AccessResourceGrantSummary[]
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(kind: "pending" | "success" | "denied" | "conflict" | "error"): string {
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

function targetFieldForType(targetType: string): ResourceGrantTargetField {
    return `${targetType}_id` as ResourceGrantTargetField
}

// One control per group — the identical selector, effect, and cascade
// AddResourceGrant.tsx uses for a member grantee, reused here rather than
// duplicated (PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §8.5's "the same
// selector reused for group grantees").
export function AddGroupResourceGrant({
    campaignId,
    accessGroupId,
    groupName,
    assignableCharacters,
    grantableCapabilities,
    existingGrants,
    onChanged,
    onMutationStart,
}: AddGroupResourceGrantProps) {
    const typeSelectId = useId()
    const resourceLabelId = useId()
    const effectGroupId = useId()
    const capabilitySelectId = useId()
    const statusId = useId()

    const [isEditing, setIsEditing] = useState(false)
    const [denyConfirmed, setDenyConfirmed] = useState(false)

    const targetTypes = Array.from(
        new Set(grantableCapabilities.map((capability) => capability.target_type)),
    )
    // See AddResourceGrant's identical usableTargetTypes for why
    // "character" is excluded here when nothing is assignable, but the
    // four async kinds cannot be pre-checked the same way.
    const usableTargetTypes = targetTypes.filter(
        (targetType) => targetType !== "character" || assignableCharacters.length > 0,
    )

    const [selectedTargetType, setSelectedTargetType] = useState(usableTargetTypes[0] ?? "")
    const [selectedResource, setSelectedResource] = useState<{
        targetType: string
        id: string
    }>({ targetType: "", id: "" })
    const [selectedEffect, setSelectedEffect] = useState<ResourceGrantEffect>("allow")
    const [selectedCapability, setSelectedCapability] = useState<{
        targetType: string
        resourceId: string
        effect: ResourceGrantEffect
        code: string
    }>({ targetType: "", resourceId: "", effect: "allow", code: "" })

    const { status, submit, reset } = useAddGroupResourceGrant(campaignId, () =>
        onChanged(selectedEffect === "deny" ? "Resource denial added." : "Resource access added."),
    )

    const isPending = status.kind === "pending"

    const selectedResourceId =
        selectedResource.targetType === selectedTargetType ? selectedResource.id : ""

    const capabilitiesForType = grantableCapabilities.filter(
        (capability) => capability.target_type === selectedTargetType,
    )
    const activeCapabilityCodesForSelectedResource = new Set(
        existingGrants
            .filter(
                (grant) =>
                    grant.target_type === selectedTargetType &&
                    grant.target_id === selectedResourceId &&
                    grant.effect === selectedEffect,
            )
            .map((grant) => grant.capability_code),
    )
    const availableCapabilitiesForSelectedResource = capabilitiesForType.filter(
        (capability) => !activeCapabilityCodesForSelectedResource.has(capability.code),
    )

    let selectedCapabilityCode = selectedCapability.code
    if (
        selectedCapability.targetType !== selectedTargetType ||
        selectedCapability.resourceId !== selectedResourceId ||
        selectedCapability.effect !== selectedEffect
    ) {
        selectedCapabilityCode = availableCapabilitiesForSelectedResource[0]?.code ?? ""
        setSelectedCapability({
            targetType: selectedTargetType,
            resourceId: selectedResourceId,
            effect: selectedEffect,
            code: selectedCapabilityCode,
        })
    }

    if (usableTargetTypes.length === 0) {
        // No grantable capability of any kind, or the only kind available
        // is "character" with none assignable — never show a control
        // with nowhere safe to send it.
        return null
    }

    if (!isEditing) {
        return (
            <button
                type="button"
                className="access-role-editor__trigger"
                onClick={() => {
                    reset()
                    setSelectedTargetType(usableTargetTypes[0] ?? "")
                    setSelectedEffect("allow")
                    setDenyConfirmed(false)
                    setIsEditing(true)
                }}
            >
                Add resource access
            </button>
        )
    }

    const canSubmit =
        selectedTargetType !== "" &&
        selectedResourceId !== "" &&
        selectedCapabilityCode !== "" &&
        (selectedEffect === "allow" || denyConfirmed)

    return (
        <form
            className="access-role-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (!canSubmit) {
                    return
                }
                onMutationStart()
                submit(
                    accessGroupId,
                    { field: targetFieldForType(selectedTargetType), id: selectedResourceId },
                    selectedCapabilityCode,
                    selectedEffect,
                )
            }}
        >
            <label htmlFor={typeSelectId}>Add resource access for {groupName}</label>

            <select
                id={typeSelectId}
                value={selectedTargetType}
                disabled={isPending || usableTargetTypes.length <= 1}
                onChange={(event) => {
                    setSelectedTargetType(event.currentTarget.value)
                }}
            >
                {usableTargetTypes.map((targetType) => (
                    <option key={targetType} value={targetType}>
                        {humanizeCode(targetType)}
                    </option>
                ))}
            </select>

            <label id={resourceLabelId}>{humanizeCode(selectedTargetType)}</label>
            <ResourceTargetSelector
                campaignId={campaignId}
                targetType={selectedTargetType}
                assignableCharacters={assignableCharacters}
                value={selectedResourceId}
                disabled={isPending}
                labelId={resourceLabelId}
                onChange={(option) => {
                    setSelectedResource({
                        targetType: selectedTargetType,
                        id: option?.id ?? "",
                    })
                }}
            />

            <fieldset id={effectGroupId}>
                <legend>Effect</legend>
                <label>
                    <input
                        type="radio"
                        name={effectGroupId}
                        value="allow"
                        checked={selectedEffect === "allow"}
                        disabled={isPending}
                        onChange={() => {
                            setSelectedEffect("allow")
                            setDenyConfirmed(false)
                        }}
                    />
                    Allow
                </label>
                <label>
                    <input
                        type="radio"
                        name={effectGroupId}
                        value="deny"
                        checked={selectedEffect === "deny"}
                        disabled={isPending}
                        onChange={() => {
                            setSelectedEffect("deny")
                            setDenyConfirmed(false)
                        }}
                    />
                    Deny
                </label>
            </fieldset>

            {selectedEffect === "deny" && (
                <label className="access-role-editor__confirm-text">
                    <input
                        type="checkbox"
                        checked={denyConfirmed}
                        disabled={isPending}
                        onChange={(event) => setDenyConfirmed(event.currentTarget.checked)}
                    />
                    I understand this explicitly denies this capability for every member of{" "}
                    {groupName}, even if another role or grant would otherwise allow it.
                </label>
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
                            effect: selectedEffect,
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
                <p>Every available permission is already granted for this resource and effect.</p>
            )}

            <div className="access-role-editor__actions">
                <button type="submit" disabled={isPending || !canSubmit} aria-busy={isPending}>
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
                    status.kind === "denied" || status.kind === "conflict" || status.kind === "error"
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
