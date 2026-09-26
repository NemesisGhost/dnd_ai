import { useId, useState } from "react"
import { ResourceTargetSelector } from "./ResourceTargetSelector"
import { useAddResourceGrant } from "../hooks/useAddResourceGrant"
import type {
    AccessResourceGrantSummary,
    AssignableCharacter,
    GrantableResourceCapability,
} from "../types/accessOverview"
import type { ResourceGrantEffect, ResourceGrantTargetField } from "../types/resourceGrantTarget"
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

function statusMessage(kind: "pending" | "success" | "denied" | "conflict" | "error"): string {
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

// Mirrors dnd_ai.commands.access_grants._RESOURCE_GRANT_TARGET_FIELDS'
// own "target_type = target_column.removesuffix('_id')" derivation
// (dnd_ai.queries.access_overview), inverted — every target_type this
// checkpoint's grantableCapabilities ever names is exactly one of these
// six kinds, so the inverse is total.
function targetFieldForType(targetType: string): ResourceGrantTargetField {
    return `${targetType}_id` as ResourceGrantTargetField
}

// One control per member (never per resource): "add resource access"
// names a member, a resource type, a specific resource, an effect, and a
// capability to grant. A guided, server-driven sequence — resource type,
// then resource (via ResourceTargetSelector, §8.5), then effect, then
// capability — with each lower selection reset whenever a higher one
// changes, mirroring AddCharacterRelationship's own identical cascade.
// Capability choices are always narrowed to dnd_ai.domain.access.
// RESOURCE_GRANT_CAPABILITY_CATALOG (via the server-supplied
// grantableCapabilities list) and to whichever are not already actively
// granted, with the same effect, for the *currently selected* resource —
// the server independently re-validates and enforces its own delegation
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
    const resourceLabelId = useId()
    const effectGroupId = useId()
    const capabilitySelectId = useId()
    const statusId = useId()

    const [isEditing, setIsEditing] = useState(false)
    const [denyConfirmed, setDenyConfirmed] = useState(false)

    const targetTypes = Array.from(
        new Set(grantableCapabilities.map((capability) => capability.target_type)),
    )
    // "character" is the one target kind resolved synchronously from a
    // prop rather than an async read hook, so it is the one kind this
    // component can still know ahead of time has nothing to offer —
    // excluded here so the trigger is never shown for a form that can
    // only ever land on an empty character picker with no other target
    // kind to fall back to. The four async kinds cannot be pre-checked
    // this way; an empty result for one of those still opens the form,
    // which then shows "No eligible resource of this type is available."
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

    const { status, submit, reset } = useAddResourceGrant(campaignId, () =>
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
        // Nothing the contract marks as a grantable capability, or the
        // only kind available is "character" with none assignable — never
        // show a control with nowhere safe to send it.
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
                Add direct resource access
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
                    campaignMembershipId,
                    { field: targetFieldForType(selectedTargetType), id: selectedResourceId },
                    selectedCapabilityCode,
                    selectedEffect,
                )
            }}
        >
            <label htmlFor={typeSelectId}>
                Add direct resource access for {memberDisplayName} in {campaignName}
            </label>

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
                    I understand this explicitly denies this capability for {memberDisplayName}, even
                    if another role or grant would otherwise allow it.
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
