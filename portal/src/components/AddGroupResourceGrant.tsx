import { useId, useState } from "react"
import { CharacterDenyFeedback, CharacterDenyFields } from "./CharacterDenyFields"
import { ResourceTargetSelector } from "./ResourceTargetSelector"
import { useAddGroupResourceGrant } from "../hooks/useAddGroupResourceGrant"
import type {
    AccessResourceGrantSummary,
    AssignableCharacter,
    DeniableCharacterCapability,
    GrantableResourceCapability,
} from "../types/accessOverview"
import type { WriteNotice } from "../types/accessWrite"
import type { ResourceGrantEffect, ResourceGrantTargetField } from "../types/resourceGrantTarget"
import {
    CHARACTER_DENY_KIND,
    CHARACTER_DENY_KIND_LABEL,
    availableDenyCapabilities,
    canOfferCharacterDeny,
} from "../utils/characterDenies"
import { humanizeCode } from "../utils/humanize"

interface AddGroupResourceGrantProps {
    campaignId: string
    accessGroupId: string
    groupName: string
    assignableCharacters: AssignableCharacter[]
    grantableCapabilities: GrantableResourceCapability[]
    existingGrants: AccessResourceGrantSummary[]
    // The server's list of permissions a character may be denied. Absent or empty: no character denial is offered.
    deniableCapabilities?: DeniableCharacterCapability[]
    // A read of the access list (sends nothing): the one recovery offered after a 404 or 409 on a character denial.
    onRefreshAccess?: () => void
    onChanged: (message: string, notice?: WriteNotice) => void
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
    deniableCapabilities,
    onRefreshAccess,
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
    const offersCharacterDeny = canOfferCharacterDeny(deniableCapabilities, assignableCharacters)
    const usableTargetTypes = [
        ...targetTypes.filter(
            (targetType) => targetType !== "character" || assignableCharacters.length > 0,
        ),
        // The one pseudo-kind: a deny on a character, offered only from the server's list. It comes last, so
        // the form still opens on the first existing kind.
        ...(offersCharacterDeny ? [CHARACTER_DENY_KIND] : []),
    ]

    const [selectedTargetType, setSelectedTargetType] = useState(usableTargetTypes[0] ?? "")
    const [selectedResource, setSelectedResource] = useState<{
        targetType: string
        id: string
    }>({ targetType: "", id: "" })
    const [selectedEffect, setSelectedEffect] = useState<ResourceGrantEffect>("allow")
    // The character-deny kind keeps its own selections. None is implicit: a character and a permission are chosen.
    const [denyCharacterId, setDenyCharacterId] = useState("")
    const [denyCode, setDenyCode] = useState("")
    const [selectedCapability, setSelectedCapability] = useState<{
        targetType: string
        resourceId: string
        effect: ResourceGrantEffect
        code: string
    }>({ targetType: "", resourceId: "", effect: "allow", code: "" })

    const isCharacterDeny = selectedTargetType === CHARACTER_DENY_KIND

    const { status, failureStatus, submit, reset } = useAddGroupResourceGrant(campaignId, () => {
        if (isCharacterDeny) {
            // Focus, if the re-read displaces it, returns to this card's grants heading (D-5).
            onChanged("Denial added.", { focusGrantsOf: accessGroupId })
            return
        }
        onChanged(selectedEffect === "deny" ? "Resource denial added." : "Resource access added.")
    })

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

    const denyAvailable = availableDenyCapabilities(
        deniableCapabilities ?? [],
        existingGrants,
        denyCharacterId,
    )
    const denyChosen = denyAvailable.some((capability) => capability.code === denyCode)

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
                    setDenyCharacterId("")
                    setDenyCode("")
                    setIsEditing(true)
                }}
            >
                Add resource access
            </button>
        )
    }

    // A definitive 404 on a character deny (the character or grantee is gone) ends this attempt: the form
    // cannot send it again. Only Cancel (then reopening) or a re-read of the list, which unmounts the
    // form and so starts it afresh, clears this; a failed re-read leaves it locked (O13, S04-R1).
    const attemptRefused = isCharacterDeny && status.kind === "denied" && failureStatus === 404
    const canSubmit = isCharacterDeny
        ? denyCharacterId !== "" && denyChosen && denyConfirmed && !attemptRefused
        : selectedTargetType !== "" &&
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
                if (isCharacterDeny) {
                    // The server's rule for a character deny: `entity_id`, effect deny (never an allow).
                    submit(
                        accessGroupId,
                        { field: "entity_id", id: denyCharacterId },
                        denyCode,
                        "deny",
                    )
                    return
                }
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
                        {targetType === CHARACTER_DENY_KIND
                            ? CHARACTER_DENY_KIND_LABEL
                            : humanizeCode(targetType)}
                    </option>
                ))}
            </select>

            {isCharacterDeny ? (
                <CharacterDenyFields
                    granteeKind="group"
                    granteeName={groupName}
                    characters={assignableCharacters}
                    deniable={deniableCapabilities ?? []}
                    existingGrants={existingGrants}
                    characterId={denyCharacterId}
                    onCharacterChange={setDenyCharacterId}
                    code={denyChosen ? denyCode : ""}
                    onCodeChange={setDenyCode}
                    confirmed={denyConfirmed}
                    onConfirmedChange={setDenyConfirmed}
                    isPending={isPending}
                />
            ) : (
            <>
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
            </>
            )}

            <div className="access-role-editor__actions">
                <button type="submit" disabled={isPending || !canSubmit} aria-busy={isPending}>
                    {isPending
                        ? "Adding…"
                        : isCharacterDeny && status.kind === "error"
                          ? "Try again"
                          : "Add"}
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

            {isCharacterDeny ? (
                <CharacterDenyFeedback
                    kind={status.kind}
                    failureStatus={failureStatus}
                    granteeKind="group"
                    onRefresh={() => onRefreshAccess?.()}
                />
            ) : (
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
            )}
        </form>
    )
}
