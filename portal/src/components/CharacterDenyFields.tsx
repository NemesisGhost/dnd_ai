import { useId } from "react"
import type {
    AccessResourceGrantSummary,
    AssignableCharacter,
    DeniableCharacterCapability,
} from "../types/accessOverview"
import { availableDenyCapabilities, denyHint, denyLabel } from "../utils/characterDenies"

interface CharacterDenyFieldsProps {
    granteeKind: "member" | "group"
    granteeName: string
    characters: AssignableCharacter[]
    deniable: DeniableCharacterCapability[]
    existingGrants: AccessResourceGrantSummary[]
    characterId: string
    onCharacterChange: (characterId: string) => void
    code: string
    onCodeChange: (code: string) => void
    confirmed: boolean
    onConfirmedChange: (confirmed: boolean) => void
    isPending: boolean
}

// The "Character (deny only)" fields of both resource-grant forms. Everything is controlled by the form, so
// the selections die with it. There is deliberately no implicit target: the character and the permission both
// start unchosen, and the effect is fixed to Deny (an allow of either permission on a character is refused by
// the server). Which permissions exist is the server's list; the words for the two known ones are in
// utils/characterDenies.
export function CharacterDenyFields({
    granteeKind,
    granteeName,
    characters,
    deniable,
    existingGrants,
    characterId,
    onCharacterChange,
    code,
    onCodeChange,
    confirmed,
    onConfirmedChange,
    isPending,
}: CharacterDenyFieldsProps) {
    const characterSelectId = useId()
    const permissionSelectId = useId()
    const hintId = useId()

    const available = availableDenyCapabilities(deniable, existingGrants, characterId)
    const chosen = available.find((capability) => capability.code === code)
    const hint = chosen === undefined ? null : denyHint(chosen.code)
    const everyoneDenied = characterId !== "" && available.length === 0
    const who = granteeKind === "group" ? `every member of ${granteeName}` : granteeName

    return (
        <>
            <label htmlFor={characterSelectId}>Character</label>
            <select
                id={characterSelectId}
                value={characterId}
                disabled={isPending}
                onChange={(event) => onCharacterChange(event.currentTarget.value)}
            >
                <option value="">Choose a character</option>
                {characters.map((character) => (
                    <option key={character.character_id} value={character.character_id}>
                        {character.display_name}
                    </option>
                ))}
            </select>

            <p>Effect: Deny. This form only denies; it never grants access to a character.</p>

            <label htmlFor={permissionSelectId}>What to deny</label>
            {everyoneDenied ? (
                <p>Both denials are already in place for this character.</p>
            ) : (
                <select
                    id={permissionSelectId}
                    value={chosen?.code ?? ""}
                    disabled={isPending || characterId === ""}
                    aria-describedby={hint === null ? undefined : hintId}
                    onChange={(event) => onCodeChange(event.currentTarget.value)}
                >
                    <option value="">Choose what to deny</option>
                    {available.map((capability) => (
                        <option key={capability.code} value={capability.code}>
                            {denyLabel(capability)}
                        </option>
                    ))}
                </select>
            )}
            {hint !== null && <p id={hintId}>{hint}</p>}

            <label className="access-role-editor__confirm-text">
                <input
                    type="checkbox"
                    checked={confirmed}
                    disabled={isPending}
                    onChange={(event) => onConfirmedChange(event.currentTarget.checked)}
                />
                I understand this explicitly denies this for {who}, even if another role or grant would
                otherwise allow it.
            </label>
        </>
    )
}

interface CharacterDenyFeedbackProps {
    kind: "idle" | "pending" | "success" | "denied" | "conflict" | "error"
    // 403 or 404 for a denied outcome: the two are told apart here (the generic forms say one thing for both).
    failureStatus: number | null
    granteeKind: "member" | "group"
    onRefresh: () => void
}

function feedbackText(
    kind: CharacterDenyFeedbackProps["kind"],
    failureStatus: number | null,
    granteeKind: "member" | "group",
): string {
    switch (kind) {
        case "pending":
            return "Adding denial…"
        case "denied":
            return failureStatus === 403
                ? "You no longer have permission to manage access."
                : `That character or ${granteeKind} is no longer available for a denial.`
        case "conflict":
            return "This denial may already be in place. Refresh the access list to see the current state."
        case "error":
            return "We couldn't confirm whether the denial was added. Trying again sends the same request and can't add it twice."
        default:
            return ""
    }
}

// The status line of the character-deny kind and, where a read would help, its one recovery: a read of the
// list, which sends nothing. A confirmed write is announced by the page's persistent region, not here.
export function CharacterDenyFeedback({ kind, failureStatus, granteeKind, onRefresh }: CharacterDenyFeedbackProps) {
    const text = feedbackText(kind, failureStatus, granteeKind)
    const offersRefresh = kind === "conflict" || (kind === "denied" && failureStatus === 404)
    const isError = kind === "denied" || kind === "conflict" || kind === "error"
    return (
        <>
            <p
                className={
                    isError
                        ? "access-role-editor__status access-role-editor__status--error"
                        : "access-role-editor__status"
                }
                role="status"
                aria-live="polite"
            >
                {text}
            </p>
            {offersRefresh && (
                <button type="button" onClick={onRefresh}>
                    Refresh access list
                </button>
            )}
        </>
    )
}
