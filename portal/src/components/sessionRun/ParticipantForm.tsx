import { useEffect, useRef, useState } from "react"
import { addSessionParticipant } from "../../api/sessionAuthoring"
import { fetchWorldEntities } from "../../api/world"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import type { CharacterKind } from "../../types/character"
import type { CampaignSessionDetail, PlayReceipt } from "../../types/campaignSession"
import { characterKindLabel, characterKindOfTypeCode } from "../../utils/characterKind"
import { useAnnounce } from "../authoring/announcer"
import { SelectField } from "../authoring/fields"
import { AuthoringForm, ErrorSummary, FormActions, MutationStatusMessage, StaleWriteNotice } from "../authoring/feedback"
import type { FieldError } from "../authoring/feedback"
import { ReferenceCombobox } from "../authoring/ReferenceCombobox"
import type { ReferenceOption } from "../authoring/ReferenceCombobox"
import { CODE_MESSAGE } from "./runMessages"
import { ROLE_LABEL, effectiveRole, rolesForKind } from "./participantRoles"

const CHARACTER_FIELD = "participant-character"

// A chosen character together with its kind, taken from the search card's entity type.
interface ChosenCharacter extends ReferenceOption {
    kind: CharacterKind
}

interface AddBody {
    characterId: string
    role: string
    // Captured when the user submits, so a retry of an unconfirmed add repeats the exact request
    // (and idempotency key) rather than picking up a version that moved in the meantime.
    expectedRowVersion: number
}

export function ParticipantForm({
    campaignId,
    session,
    presentCharacterIds,
    refetch,
}: {
    campaignId: string
    session: CampaignSessionDetail
    presentCharacterIds: ReadonlySet<string>
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [character, setCharacter] = useState<ChosenCharacter | null>(null)
    const [wantsGuest, setWantsGuest] = useState(false)
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    // The kind each searched character came from (the search card's entity type), kept by id so
    // the form reads structured data and never parses the label shown in the list.
    const kinds = useRef(new Map<string, CharacterKind>())

    const roles = rolesForKind(session.participant_role_options, character?.kind ?? null)
    const role = effectiveRole(roles, wantsGuest)

    const add = useAuthoringMutation<AddBody, PlayReceipt>({
        scopeKey: `add-participant:${session.session_id}`,
        request: (body, ctx) =>
            addSessionParticipant(
                campaignId,
                session.session_id,
                {
                    expected_row_version: body.expectedRowVersion,
                    character_id: body.characterId,
                    participation_role: body.role,
                },
                ctx,
            ),
        onSuccess: async () => {
            setCharacter(null)
            setWantsGuest(false)
            setErrors([])
            await refetch()
            announce("Participant added")
        },
    })
    const error = add.status.kind === "error" ? add.status.error : null
    const message = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null

    // A duplicate means the roster this page shows is out of date: reload it. The failure stays
    // on screen (the mutation scope does not follow the row version).
    useEffect(() => {
        if (error?.code === "session_participant_exists") {
            void refetch()
        }
    }, [error, refetch])

    async function searchCharacters(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchWorldEntities(campaignId, { category: "character", query, limit: 20 }, signal)
        return page.items
            .filter((item) => !presentCharacterIds.has(item.entity_id))
            .map((item) => {
                const itemKind = characterKindOfTypeCode(item.entity_type_code)
                kinds.current.set(item.entity_id, itemKind)
                return { id: item.entity_id, label: item.name, detail: characterKindLabel(itemKind) }
            })
    }

    function refuse(fieldMessage: string) {
        setErrors([{ fieldId: CHARACTER_FIELD, message: fieldMessage }])
        setAttempt((n) => n + 1)
    }

    function submit() {
        if (add.status.kind === "pending") {
            return
        }
        if (character === null) {
            refuse("Choose a character.")
            return
        }
        if (presentCharacterIds.has(character.id)) {
            refuse(CODE_MESSAGE.session_participant_exists!)
            return
        }
        if (role === "") {
            refuse("This character cannot take part in a session.")
            return
        }
        setErrors([])
        add.submit({ characterId: character.id, role, expectedRowVersion: session.row_version ?? 1 })
    }

    const roleOptions = roles.map((value) => ({ value, label: ROLE_LABEL[value] ?? value }))

    return (
        <AuthoringForm label="Add a participant" onSubmit={submit}>
            <ErrorSummary errors={errors} attempt={attempt} />
            {error?.kind === "stale" ? (
                <StaleWriteNotice
                    onLoadLatest={() => {
                        // Clear the notice only once the new version is in, so a resubmit can't reuse the old one.
                        void refetch().then(() => add.reset())
                    }}
                />
            ) : message !== null ? (
                <p role="alert">{message}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={add.retry} onCheckSession={reload} />
            ) : null}
            <ReferenceCombobox
                id={CHARACTER_FIELD}
                label="Character"
                hint="Only published characters can take part."
                value={character}
                onChange={(chosen) =>
                    setCharacter(
                        chosen === null ? null : { ...chosen, kind: kinds.current.get(chosen.id) ?? "character" },
                    )
                }
                search={searchCharacters}
                error={errors.find((e) => e.fieldId === CHARACTER_FIELD)?.message ?? null}
                placeholder="Search characters"
            />
            <SelectField
                id="participant-role"
                label="Role"
                value={role}
                options={roleOptions}
                disabled={roleOptions.length === 0}
                hint={
                    character === null
                        ? "Choose a character to see the roles it can take."
                        : roleOptions.length === 0
                          ? "This character cannot take part in a session."
                          : "Guest is allowed for any character."
                }
                onChange={(value) => setWantsGuest(value === "guest")}
            />
            <FormActions
                pending={add.status.kind === "pending"}
                saveLabel="Add participant"
                onCancel={() => {
                    setCharacter(null)
                    setWantsGuest(false)
                }}
                cancelLabel="Clear"
            />
        </AuthoringForm>
    )
}
