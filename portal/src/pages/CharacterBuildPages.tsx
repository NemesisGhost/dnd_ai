import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import {
    activateBuild,
    buildOptionsPath,
    characterBuildsPath,
    createBuild,
    initializeCharacterState,
} from "../api/characterBuilds"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { useAnnounce } from "../components/authoring/announcer"
import { SelectField, TextField } from "../components/authoring/fields"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
    StaleWriteNotice,
} from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import type {
    BuildOptions,
    BuildReceipt,
    BuildSummary,
    CharacterBuilds,
    CreateBuildBody,
} from "../types/characterBuilds"
import {
    EMPTY_BUILD,
    isBuildDirty,
    isWholeNumber,
    toBuildBody,
    validateBuild,
} from "../utils/characterBuildForm"
import type { BuildFormValues } from "../utils/characterBuildForm"
import "../components/authoring/authoring.css"

const base = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`
const buildsPage = (campaignId: string, characterId: string): string =>
    `${base(campaignId)}/characters/${encodeURIComponent(characterId)}/builds`

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    build_option_not_available:
        "One of the selected rules options is not available for this campaign. Reload and choose again.",
    build_character_invalid: "This character cannot have a build.",
    character_not_published: "Publish the character before changing its build during play.",
    clock_required: "Set the campaign time on Campaign Home before changing a character's build.",
    character_state_missing: "Set the character's starting state before activating a build.",
    character_state_exists: "This character already has starting state.",
    build_already_active: "That build is already the active build.",
}

function Unavailable({ noun }: { noun: string }) {
    return <p role="alert">This {noun} does not exist, or you do not have access to it.</p>
}

// /app/:campaignId/characters/:characterId/builds — a character's builds, its
// starting state, and which build is active. Editors only (the read is a 403/404
// for anyone else, so a player sees only "unavailable").
export function CharacterBuildsPage() {
    const { campaignId = "", characterId = "" } = useParams()
    const resource = useAuthoringResource<CharacterBuilds>(characterBuildsPath(campaignId, characterId))
    const ready = resource.state.kind === "ready"
    const headingRef = usePageArrival(ready)
    const data = resource.state.kind === "ready" ? resource.state.data : null

    return (
        <section className="authoring-page" aria-labelledby="builds-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={`${base(campaignId)}/world`}>World</Link>
                {data !== null ? (
                    <>
                        {" / "}
                        <Link
                            to={`${base(campaignId)}/world/character/${encodeURIComponent(characterId)}`}
                        >
                            {data.character.name}
                        </Link>
                    </>
                ) : null}
            </p>
            <h1 id="builds-heading" ref={headingRef} tabIndex={-1}>
                Builds
            </h1>
            {resource.state.kind === "loading" ? (
                <p role="status">Loading builds…</p>
            ) : resource.state.kind === "error" ? (
                <p role="alert">The builds could not be loaded. Try reloading the page.</p>
            ) : data === null ? (
                <Unavailable noun="character" />
            ) : (
                <>
                    <StateSection
                        campaignId={campaignId}
                        characterId={characterId}
                        data={data}
                        refetch={resource.refetch}
                    />
                    <BuildList
                        campaignId={campaignId}
                        characterId={characterId}
                        data={data}
                        refetch={resource.refetch}
                    />
                </>
            )}
        </section>
    )
}

function StateSection({
    campaignId,
    characterId,
    data,
    refetch,
}: {
    campaignId: string
    characterId: string
    data: CharacterBuilds
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [maximum, setMaximum] = useState("")
    const [current, setCurrent] = useState("")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const mutation = useAuthoringMutation<
        { maximum_hit_points: number; current_hit_points: number | null },
        BuildReceipt
    >({
        scopeKey: `init-state:${campaignId}:${characterId}`,
        request: (body, ctx) => initializeCharacterState(campaignId, characterId, body, ctx),
        onSuccess: async () => {
            await refetch()
            announce("Starting state saved")
        },
    })

    if (data.state.initialized) {
        return (
            <p>
                Hit points: {data.state.current_hit_points} of {data.state.maximum_hit_points}
            </p>
        )
    }
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const pending = mutation.status.kind === "pending"

    function submit() {
        const found: FieldError[] = []
        if (!isWholeNumber(maximum) || Number(maximum) < 1) {
            found.push({
                fieldId: "state-maximum",
                message: "Maximum hit points must be a whole number of at least 1.",
            })
        }
        if (current.trim() !== "" && !isWholeNumber(current)) {
            found.push({
                fieldId: "state-current",
                message: "Current hit points must be a whole number.",
            })
        } else if (
            current.trim() !== "" &&
            isWholeNumber(maximum) &&
            Number(current) > Number(maximum)
        ) {
            found.push({
                fieldId: "state-current",
                message: "Current hit points cannot be higher than the maximum.",
            })
        }
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        mutation.submit({
            maximum_hit_points: Number(maximum),
            current_hit_points: current.trim() === "" ? null : Number(current),
        })
    }

    const errorFor = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null
    return (
        <AuthoringForm label="Set starting state" onSubmit={submit}>
            <h2>Starting state</h2>
            <p>
                This character has no state in this campaign yet. Set its hit points before activating a
                build.
            </p>
            <ErrorSummary errors={errors} attempt={attempt} />
            {message !== null ? (
                <p role="alert">{message}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            <TextField
                id="state-maximum"
                label="Maximum hit points"
                value={maximum}
                onChange={setMaximum}
                required
                error={errorFor("state-maximum")}
            />
            <TextField
                id="state-current"
                label="Current hit points"
                hint="Leave empty to start at the maximum."
                value={current}
                onChange={setCurrent}
                error={errorFor("state-current")}
            />
            <FormActions
                pending={pending}
                saveLabel="Set starting state"
                onCancel={() => {
                    setMaximum("")
                    setCurrent("")
                    setErrors([])
                }}
                cancelLabel="Clear"
            />
        </AuthoringForm>
    )
}

function BuildList({
    campaignId,
    characterId,
    data,
    refetch,
}: {
    campaignId: string
    characterId: string
    data: CharacterBuilds
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [target, setTarget] = useState<BuildSummary | null>(null)
    const mutation = useAuthoringMutation<BuildSummary, BuildReceipt>({
        scopeKey: `activate-build:${campaignId}:${characterId}`,
        request: (build, ctx) =>
            activateBuild(campaignId, characterId, build.character_build_id, data.active_build_id, ctx),
        onSuccess: async () => {
            setTarget(null)
            await refetch()
            announce("Build activated")
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const pending = mutation.status.kind === "pending"

    return (
        <>
            <h2>Builds</h2>
            <p className="authoring-page__actions-row">
                <Link
                    className="authoring-button"
                    to={`${buildsPage(campaignId, characterId)}/new`}
                >
                    New build
                </Link>
            </p>
            {error?.kind === "stale" ? (
                <StaleWriteNotice
                    onLoadLatest={() => {
                        mutation.reset()
                        setTarget(null)
                        void refetch()
                    }}
                />
            ) : null}
            {data.builds.length === 0 ? (
                <p>No builds yet.</p>
            ) : (
                <ul className="authoring-choice-list">
                    {data.builds.map((build) => (
                        <li key={build.character_build_id}>
                            <strong>{build.label ?? "Untitled build"}</strong>
                            {build.is_active ? " (active)" : ""}
                            <p>
                                {build.counts.classes} classes, {build.counts.abilities} ability scores,{" "}
                                {build.counts.proficiencies} proficiencies, {build.counts.features} features
                            </p>
                            {!build.is_active ? (
                                <button
                                    type="button"
                                    className="authoring-button"
                                    disabled={!data.state.initialized}
                                    aria-describedby={
                                        data.state.initialized ? undefined : "activate-needs-state"
                                    }
                                    onClick={() => {
                                        mutation.reset()
                                        setTarget(build)
                                    }}
                                >
                                    Activate {build.label ?? "build"}
                                </button>
                            ) : null}
                        </li>
                    ))}
                </ul>
            )}
            {!data.state.initialized && data.builds.length > 0 ? (
                <p id="activate-needs-state" className="authoring-note">
                    Set the starting state before activating a build.
                </p>
            ) : null}
            <ConfirmDialog
                open={target !== null}
                title="Activate this build?"
                description="This becomes the build the character sheet uses on this timeline. A change after the first activation is recorded in the campaign's history."
                confirmLabel="Activate build"
                pending={pending}
                error={
                    message !== null ? (
                        <p role="alert">{message}</p>
                    ) : error !== null && error.kind !== "stale" ? (
                        <MutationStatusMessage
                            error={error}
                            onRetry={mutation.retry}
                            onCheckSession={reload}
                        />
                    ) : null
                }
                onConfirm={() => target !== null && mutation.submit(target)}
                onCancel={() => {
                    setTarget(null)
                    mutation.reset()
                }}
            />
        </>
    )
}

// /app/:campaignId/characters/:characterId/builds/new
export function CreateCharacterBuildPage() {
    const { campaignId = "", characterId = "" } = useParams()
    const options = useAuthoringResource<BuildOptions>(buildOptionsPath(campaignId))
    const headingRef = usePageArrival(options.state.kind === "ready")
    return (
        <section className="authoring-page" aria-labelledby="new-build-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={buildsPage(campaignId, characterId)}>Builds</Link>
            </p>
            <h1 id="new-build-heading" ref={headingRef} tabIndex={-1}>
                New build
            </h1>
            {options.state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : options.state.kind === "error" ? (
                <p role="alert">The form could not be loaded. Try reloading the page.</p>
            ) : options.state.kind !== "ready" ? (
                <p role="alert">You do not have permission to create builds in this campaign.</p>
            ) : (
                <BuildForm campaignId={campaignId} characterId={characterId} options={options.state.data} />
            )}
        </section>
    )
}

function BuildForm({
    campaignId,
    characterId,
    options,
}: {
    campaignId: string
    characterId: string
    options: BuildOptions
}) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const [values, setValues] = useState<BuildFormValues>(EMPTY_BUILD)
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const guard = useUnsavedChangesGuard(isBuildDirty(values))
    const mutation = useAuthoringMutation<CreateBuildBody, BuildReceipt>({
        scopeKey: `create-build:${campaignId}:${characterId}`,
        request: (body, ctx) => createBuild(campaignId, characterId, body, ctx),
        onSuccess: () => {
            guard.release()
            void navigate(buildsPage(campaignId, characterId), {
                replace: true,
                state: { announce: "Build created" },
            })
        },
    })
    const pending = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const errorFor = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null

    const set = (patch: Partial<BuildFormValues>) => setValues((v) => ({ ...v, ...patch }))
    const toggle = (list: string[], id: string) =>
        list.includes(id) ? list.filter((x) => x !== id) : [...list, id]
    const freeTypes = options.proficiency_types.filter((t) => t.target_kind === "free_text")
    const skillOffered = options.proficiency_types.some((t) => t.target_kind === "skill")
    const saveOffered = options.proficiency_types.some((t) => t.target_kind === "saving_throw")

    function submit() {
        const found = validateBuild(values, options)
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length === 0) mutation.submit(toBuildBody(values, options))
    }

    return (
        <>
            <p className="authoring-page__lead">
                A build is saved as it is and cannot be edited later; to change a character, create a new
                build and activate it.
            </p>
            <AuthoringForm label="New build" onSubmit={submit}>
                <ErrorSummary errors={errors} attempt={attempt} />
                {message !== null ? (
                    <p role="alert">{message}</p>
                ) : error !== null ? (
                    <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                ) : null}
                <TextField
                    id="build-label"
                    label="Label"
                    hint="For example: Level 3 Fighter."
                    value={values.label}
                    onChange={(label) => set({ label })}
                    maxLength={options.limits.label_max_length}
                    error={errorFor("build-label")}
                />

                <fieldset className="authoring-fieldset">
                    <legend>Ability scores</legend>
                    {options.abilities.map((ability) => (
                        <TextField
                            key={ability.id}
                            id={`build-score-${ability.id}`}
                            label={ability.name}
                            value={values.scores[ability.id] ?? ""}
                            onChange={(text) => set({ scores: { ...values.scores, [ability.id]: text } })}
                            error={errorFor(`build-score-${ability.id}`)}
                        />
                    ))}
                </fieldset>

                <fieldset className="authoring-fieldset">
                    <legend>Classes</legend>
                    {values.classes.map((row, index) => {
                        const subclasses = options.subclasses.filter((s) => s.class_id === row.classId)
                        const update = (patch: Partial<typeof row>) =>
                            set({
                                classes: values.classes.map((r, i) => (i === index ? { ...r, ...patch } : r)),
                            })
                        return (
                            <div key={index} className="authoring-field-group">
                                <SelectField
                                    id={`build-class-${index}`}
                                    label={`Class ${index + 1}`}
                                    value={row.classId}
                                    placeholder="Choose a class"
                                    required
                                    options={options.classes.map((c) => ({ value: c.id, label: c.name }))}
                                    onChange={(classId) => update({ classId, subclassId: "" })}
                                    error={errorFor(`build-class-${index}`)}
                                />
                                <SelectField
                                    id={`build-subclass-${index}`}
                                    label={`Subclass ${index + 1}`}
                                    value={row.subclassId}
                                    placeholder="None"
                                    options={subclasses.map((s) => ({ value: s.id, label: s.name }))}
                                    onChange={(subclassId) => update({ subclassId })}
                                />
                                <TextField
                                    id={`build-level-${index}`}
                                    label={`Level ${index + 1}`}
                                    value={row.level}
                                    required
                                    onChange={(level) => update({ level })}
                                    error={errorFor(`build-level-${index}`)}
                                />
                                <button
                                    type="button"
                                    className="authoring-button"
                                    onClick={() =>
                                        set({ classes: values.classes.filter((_, i) => i !== index) })
                                    }
                                >
                                    Remove class {index + 1}
                                </button>
                            </div>
                        )
                    })}
                    <button
                        type="button"
                        className="authoring-button"
                        onClick={() =>
                            set({ classes: [...values.classes, { classId: "", subclassId: "", level: "1" }] })
                        }
                    >
                        Add a class
                    </button>
                </fieldset>

                {skillOffered ? (
                    <fieldset className="authoring-fieldset">
                        <legend>Skill proficiencies</legend>
                        {options.skills.map((skill) => (
                            <label key={skill.id} className="authoring-checkbox">
                                <input
                                    type="checkbox"
                                    checked={values.skills.includes(skill.id)}
                                    onChange={() => set({ skills: toggle(values.skills, skill.id) })}
                                />{" "}
                                {skill.name}
                            </label>
                        ))}
                    </fieldset>
                ) : null}

                {saveOffered ? (
                    <fieldset className="authoring-fieldset">
                        <legend>Saving throw proficiencies</legend>
                        {options.abilities.map((ability) => (
                            <label key={ability.id} className="authoring-checkbox">
                                <input
                                    type="checkbox"
                                    checked={values.saves.includes(ability.id)}
                                    onChange={() => set({ saves: toggle(values.saves, ability.id) })}
                                />{" "}
                                {ability.name} saving throw
                            </label>
                        ))}
                    </fieldset>
                ) : null}

                {freeTypes.length > 0 ? (
                    <fieldset className="authoring-fieldset">
                        <legend>Weapon, armor, and tool proficiencies</legend>
                        {values.freeText.map((row, index) => {
                            const update = (patch: Partial<typeof row>) =>
                                set({
                                    freeText: values.freeText.map((r, i) =>
                                        i === index ? { ...r, ...patch } : r,
                                    ),
                                })
                            return (
                                <div key={index} className="authoring-field-group">
                                    <SelectField
                                        id={`build-free-type-${index}`}
                                        label={`Kind ${index + 1}`}
                                        value={row.typeId}
                                        placeholder="Choose a kind"
                                        required
                                        options={freeTypes.map((t) => ({ value: t.id, label: t.name }))}
                                        onChange={(typeId) => update({ typeId })}
                                        error={errorFor(`build-free-type-${index}`)}
                                    />
                                    <TextField
                                        id={`build-free-label-${index}`}
                                        label={`Name ${index + 1}`}
                                        value={row.label}
                                        required
                                        onChange={(label) => update({ label })}
                                        error={errorFor(`build-free-label-${index}`)}
                                    />
                                    <button
                                        type="button"
                                        className="authoring-button"
                                        onClick={() =>
                                            set({ freeText: values.freeText.filter((_, i) => i !== index) })
                                        }
                                    >
                                        Remove proficiency {index + 1}
                                    </button>
                                </div>
                            )
                        })}
                        <button
                            type="button"
                            className="authoring-button"
                            onClick={() =>
                                set({ freeText: [...values.freeText, { typeId: "", label: "" }] })
                            }
                        >
                            Add a proficiency
                        </button>
                    </fieldset>
                ) : null}

                <fieldset className="authoring-fieldset">
                    <legend>Features</legend>
                    {options.features.length === 0 ? <p>No features are available.</p> : null}
                    {options.features.map((feature) => (
                        <label key={feature.id} className="authoring-checkbox">
                            <input
                                type="checkbox"
                                checked={values.features.includes(feature.id)}
                                onChange={() => set({ features: toggle(values.features, feature.id) })}
                            />{" "}
                            {feature.name}
                        </label>
                    ))}
                </fieldset>

                <fieldset className="authoring-fieldset">
                    <legend>Spellcasting</legend>
                    {values.spellcasting.map((row, index) => {
                        const update = (patch: Partial<typeof row>) =>
                            set({
                                spellcasting: values.spellcasting.map((r, i) =>
                                    i === index ? { ...r, ...patch } : r,
                                ),
                            })
                        return (
                            <div key={index} className="authoring-field-group">
                                <SelectField
                                    id={`build-cast-class-${index}`}
                                    label={`Casting class ${index + 1}`}
                                    value={row.classId}
                                    placeholder="No class"
                                    options={options.classes.map((c) => ({ value: c.id, label: c.name }))}
                                    onChange={(classId) => update({ classId })}
                                />
                                <SelectField
                                    id={`build-cast-ability-${index}`}
                                    label={`Casting ability ${index + 1}`}
                                    value={row.abilityId}
                                    placeholder="Choose an ability"
                                    required
                                    options={options.abilities.map((a) => ({ value: a.id, label: a.name }))}
                                    onChange={(abilityId) => update({ abilityId })}
                                    error={errorFor(`build-cast-ability-${index}`)}
                                />
                                {options.spells.length > 0 ? (
                                    <>
                                        <fieldset className="authoring-fieldset">
                                            <legend>Known spells {index + 1}</legend>
                                            {options.spells.map((spell) => (
                                                <label key={spell.id} className="authoring-checkbox">
                                                    <input
                                                        type="checkbox"
                                                        checked={row.known.includes(spell.id)}
                                                        onChange={() =>
                                                            update({ known: toggle(row.known, spell.id) })
                                                        }
                                                    />{" "}
                                                    {spell.name} (level {spell.level})
                                                </label>
                                            ))}
                                        </fieldset>
                                        <fieldset className="authoring-fieldset">
                                            <legend>Prepared spells {index + 1}</legend>
                                            {options.spells.map((spell) => (
                                                <label key={spell.id} className="authoring-checkbox">
                                                    <input
                                                        type="checkbox"
                                                        checked={row.prepared.includes(spell.id)}
                                                        onChange={() =>
                                                            update({
                                                                prepared: toggle(row.prepared, spell.id),
                                                            })
                                                        }
                                                    />{" "}
                                                    {spell.name} (level {spell.level})
                                                </label>
                                            ))}
                                        </fieldset>
                                    </>
                                ) : null}
                                <button
                                    type="button"
                                    className="authoring-button"
                                    onClick={() =>
                                        set({
                                            spellcasting: values.spellcasting.filter((_, i) => i !== index),
                                        })
                                    }
                                >
                                    Remove spellcasting {index + 1}
                                </button>
                            </div>
                        )
                    })}
                    <button
                        type="button"
                        className="authoring-button"
                        onClick={() =>
                            set({ spellcasting: [...values.spellcasting, { classId: "", abilityId: "", known: [], prepared: [] }] })
                        }
                    >
                        Add spellcasting
                    </button>
                </fieldset>

                <FormActions
                    pending={pending}
                    saveLabel="Create build"
                    pendingLabel="Creating…"
                    onCancel={() => void navigate(buildsPage(campaignId, characterId))}
                />
            </AuthoringForm>
            <ConfirmDialog
                open={guard.blocked}
                title="Discard this new build?"
                description="You have entered details that have not been saved."
                confirmLabel="Discard"
                cancelLabel="Keep editing"
                onConfirm={guard.discard}
                onCancel={guard.stay}
            />
        </>
    )
}
