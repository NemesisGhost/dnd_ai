import { useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router"
import { createWorld } from "../api/worlds"
import { RULESETS_PATH } from "../api/rulesets"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { SelectField, TextAreaField, TextField } from "../components/authoring/fields"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
} from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import { useSession } from "../context/SessionContext"
import { useAuthenticatedSession } from "../layouts/useAuthenticatedSession"
import { NotFoundContent } from "./NotFoundPage"
import type {
    CreateWorldRequest,
    CreateWorldResponse,
    RulesetListResponse,
    RulesetOption,
} from "../types/worldAuthoring"
import {
    DESCRIPTION_MAX,
    NAME_MAX,
    MAX_ALLOWED_RULESETS,
    fieldForErrorCode,
    validateDescription,
    validateName,
    validateRulesetSelection,
} from "../utils/authoringValidation"
import { canCreateWorlds } from "../utils/worldAccess"
import "../components/authoring/authoring.css"

const DEFAULT_TIMELINE_NAME = "Main Timeline"

// Only a campaign-setup return target is honoured, so the query string can never
// redirect somewhere else.
function safeReturnTarget(value: string | null): string | null {
    return value === "/campaigns/new" ? value : null
}

// The route guard in App.tsx (CreateWorldRoute) keeps a user without the
// server-computed `world.create` from mounting this page at all. This repeats
// that check as defense in depth, before any request or form state exists; the
// server's own authorization of POST /worlds remains the enforcement boundary.
export function CreateWorldPage() {
    const { bootstrap } = useAuthenticatedSession()
    if (!canCreateWorlds(bootstrap)) {
        return <NotFoundContent />
    }
    return <AuthorizedCreateWorldPage />
}

function AuthorizedCreateWorldPage() {
    const { state } = useAuthoringResource<RulesetListResponse>(RULESETS_PATH)
    const headingRef = usePageArrival(state.kind !== "loading")

    return (
        <div className="world-page">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to="/worlds">Worlds</Link>
                </p>
                <h1 ref={headingRef} tabIndex={-1}>
                    Create a world
                </h1>
                {state.kind === "loading" ? (
                    <p role="status">Loading rulesets…</p>
                ) : state.kind === "ready" ? (
                    state.data.items.length === 0 ? (
                        <p role="alert">
                            No rulesets are available, so a world cannot be created yet.
                        </p>
                    ) : (
                        <CreateWorldForm rulesets={state.data.items} />
                    )
                ) : (
                    <p role="alert">Rulesets could not be loaded. Try reloading the page.</p>
                )}
            </div>
        </div>
    )
}

interface CreateWorldFormProps {
    rulesets: RulesetOption[]
}

function CreateWorldForm({ rulesets }: CreateWorldFormProps) {
    const navigate = useNavigate()
    const [params] = useSearchParams()
    const returnTo = safeReturnTarget(params.get("returnTo"))
    const { reload } = useSession()

    const [touched, setTouched] = useState(false)
    const [name, setName] = useState("")
    const [description, setDescription] = useState("")
    const [selectedState, setSelectedState] = useState<string[] | null>(null)
    const [defaultState, setDefaultState] = useState<string | null>(null)
    const [timelineName, setTimelineName] = useState(DEFAULT_TIMELINE_NAME)
    const [timelineDescription, setTimelineDescription] = useState("")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)

    // With a single ruleset there is nothing to choose: it is preselected.
    const selected =
        selectedState ?? (rulesets.length === 1 ? [rulesets[0]!.ruleset_id] : [])
    const defaultId =
        defaultState ?? (selected.length === 1 ? selected[0]! : "")

    const guard = useUnsavedChangesGuard(touched)

    const mutation = useAuthoringMutation<CreateWorldRequest, CreateWorldResponse>({
        scopeKey: "create-world",
        request: (body, ctx) => createWorld(body, ctx),
        onSuccess: (result) => {
            guard.release()
            const state = { announce: "World created" }
            if (returnTo !== null) {
                void navigate(
                    `${returnTo}?worldId=${encodeURIComponent(result.world_id)}&timelineId=${encodeURIComponent(result.primary_timeline_id)}`,
                    { state },
                )
            } else {
                void navigate(`/worlds/${result.world_id}`, { state })
            }
        },
    })

    const pending = mutation.status.kind === "pending"
    const serverError = mutation.status.kind === "error" ? mutation.status.error : null
    const serverFieldId = serverError ? fieldForErrorCode(serverError.code) : null
    const serverFieldError: FieldError[] =
        serverError !== null && serverFieldId === "rulesets"
            ? [{ fieldId: "world-rulesets", message: "One of the selected rulesets is not available." }]
            : []

    function touch<T>(setter: (value: T) => void) {
        return (value: T) => {
            setTouched(true)
            setter(value)
        }
    }

    function toggleRuleset(rulesetId: string, on: boolean) {
        setTouched(true)
        const next = on
            ? [...selected, rulesetId]
            : selected.filter((id) => id !== rulesetId)
        setSelectedState(next)
        if (!next.includes(defaultId)) {
            setDefaultState(next.length === 1 ? next[0]! : "")
        }
    }

    function handleSubmit() {
        const found: FieldError[] = []
        const nameError = validateName(name)
        if (nameError) found.push({ fieldId: "world-name", message: nameError })
        const descriptionError = validateDescription(description)
        if (descriptionError) {
            found.push({ fieldId: "world-description", message: descriptionError })
        }
        const rulesetError = validateRulesetSelection(selected, defaultId)
        if (rulesetError) {
            found.push({
                fieldId: selected.length === 0 ? "world-rulesets" : "world-default-ruleset",
                message: rulesetError,
            })
        }
        const timelineNameError = validateName(timelineName, "Timeline name")
        if (timelineNameError) {
            found.push({ fieldId: "timeline-name", message: timelineNameError })
        }
        const timelineDescriptionError = validateDescription(timelineDescription)
        if (timelineDescriptionError) {
            found.push({ fieldId: "timeline-description", message: timelineDescriptionError })
        }
        setErrors(found)
        setAttempt((current) => current + 1)
        if (found.length > 0) {
            return
        }
        mutation.submit({
            name: name.trim(),
            description: description.trim() === "" ? null : description.trim(),
            ruleset_ids: selected,
            default_ruleset_id: defaultId,
            primary_timeline: {
                name: timelineName.trim(),
                description: timelineDescription.trim() === "" ? null : timelineDescription.trim(),
            },
        })
    }

    function errorFor(fieldId: string): string | null {
        return [...errors, ...serverFieldError].find((e) => e.fieldId === fieldId)?.message ?? null
    }

    const summaryErrors = [...errors, ...serverFieldError]

    return (
        <>
            <p className="authoring-page__lead">
                A world is the persistent setting your campaigns are played in. You become its
                owner, and it starts with one primary timeline.
            </p>
            <AuthoringForm label="Create world" onSubmit={handleSubmit}>
                <ErrorSummary errors={summaryErrors} attempt={attempt} />
                {serverError !== null && serverFieldId === null ? (
                    <MutationStatusMessage
                        error={serverError}
                        onRetry={mutation.retry}
                        onCheckSession={reload}
                    />
                ) : null}

                <TextField
                    id="world-name"
                    label="World name"
                    value={name}
                    onChange={touch(setName)}
                    required
                    maxLength={NAME_MAX}
                    error={errorFor("world-name")}
                />
                <TextAreaField
                    id="world-description"
                    label="Description"
                    value={description}
                    onChange={touch(setDescription)}
                    maxLength={DESCRIPTION_MAX}
                    error={errorFor("world-description")}
                />

                <fieldset
                    id="world-rulesets"
                    tabIndex={-1}
                    className={
                        errorFor("world-rulesets")
                            ? "authoring-field authoring-field--invalid"
                            : "authoring-field"
                    }
                    aria-invalid={errorFor("world-rulesets") ? true : undefined}
                    aria-describedby={errorFor("world-rulesets") ? "world-rulesets-error" : undefined}
                >
                    <legend className="authoring-field__label">Allowed rulesets (required)</legend>
                    <p className="authoring-field__hint">
                        Campaigns in this world can only use these rulesets. This cannot be changed
                        later. Choose up to {MAX_ALLOWED_RULESETS}.
                    </p>
                    <ul className="authoring-checklist">
                        {rulesets.map((ruleset) => {
                            const id = `ruleset-${ruleset.ruleset_id}`
                            return (
                                <li key={ruleset.ruleset_id}>
                                    <label htmlFor={id}>
                                        <input
                                            id={id}
                                            type="checkbox"
                                            checked={selected.includes(ruleset.ruleset_id)}
                                            onChange={(event) =>
                                                toggleRuleset(ruleset.ruleset_id, event.target.checked)
                                            }
                                        />
                                        {ruleset.display_name}
                                    </label>
                                </li>
                            )
                        })}
                    </ul>
                    {errorFor("world-rulesets") ? (
                        <p className="authoring-field__error" id="world-rulesets-error">
                            <span className="visually-hidden">Error: </span>
                            {errorFor("world-rulesets")}
                        </p>
                    ) : null}
                </fieldset>

                <SelectField
                    id="world-default-ruleset"
                    label="Default ruleset"
                    value={defaultId}
                    placeholder="Choose a default"
                    required
                    options={rulesets
                        .filter((r) => selected.includes(r.ruleset_id))
                        .map((r) => ({ value: r.ruleset_id, label: r.display_name }))}
                    onChange={touch(setDefaultState)}
                    error={errorFor("world-default-ruleset")}
                />

                <TextField
                    id="timeline-name"
                    label="Primary timeline name"
                    value={timelineName}
                    onChange={touch(setTimelineName)}
                    required
                    maxLength={NAME_MAX}
                    error={errorFor("timeline-name")}
                />
                <TextAreaField
                    id="timeline-description"
                    label="Primary timeline description"
                    value={timelineDescription}
                    onChange={touch(setTimelineDescription)}
                    maxLength={DESCRIPTION_MAX}
                    error={errorFor("timeline-description")}
                />

                <FormActions
                    pending={pending}
                    saveLabel="Create world"
                    pendingLabel="Creating…"
                    onCancel={() => void navigate(returnTo ?? "/worlds")}
                />
            </AuthoringForm>

            <ConfirmDialog
                open={guard.blocked}
                title="Discard unsaved changes?"
                description="You have entered details for a new world that have not been saved."
                confirmLabel="Discard changes"
                onConfirm={guard.discard}
                onCancel={guard.stay}
                cancelLabel="Keep editing"
            />
        </>
    )
}
