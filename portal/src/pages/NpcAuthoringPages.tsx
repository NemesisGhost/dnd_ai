import { fetchLocationParentOptions } from "../api/locationAuthoring"
import { createNpc, npcAuthoringPath, npcOptionsPath, updateNpc } from "../api/npcAuthoring"
import {
    createPlayerCharacter,
    playerCharacterAuthoringPath,
    playerCharacterOptionsPath,
    updatePlayerCharacter,
} from "../api/playerCharacterAuthoring"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { Link, useParams } from "react-router"
import { ContentCreatePage } from "../components/authoring/ContentCreatePage"
import type { ContentCreateConfig } from "../components/authoring/ContentCreatePage"
import { ContentEditPage } from "../components/authoring/ContentEditPage"
import type { ContentEditConfig } from "../components/authoring/ContentEditPage"
import type { FieldError } from "../components/authoring/feedback"
import { SelectField, TextAreaField, TextField } from "../components/authoring/fields"
import { ReferenceCombobox } from "../components/authoring/ReferenceCombobox"
import type { ReferenceOption } from "../components/authoring/ReferenceCombobox"
import type {
    CreateNpcBody,
    NpcAuthoringView,
    NpcFieldsBody,
    NpcOptions,
    PlayerCharacterAuthoringView,
} from "../types/npcAuthoring"
import {
    DESCRIPTION_MAX,
    NAME_MAX,
    validateDescription,
    validateName,
} from "../utils/authoringValidation"
import { statusDetail } from "../utils/locationForm"
import type { NpcReceipt, PlayerCharacterReceipt } from "../types/contentAuthoring"

interface NpcFormValues {
    name: string
    summary: string
    speciesId: string
    size: string
    origin: ReferenceOption | null
    background: string
    appearance: string
    notes: string
}

const EMPTY: NpcFormValues = {
    name: "",
    summary: "",
    speciesId: "",
    size: "",
    origin: null,
    background: "",
    appearance: "",
    notes: "",
}

const FIELD = {
    name: "npc-name",
    summary: "npc-summary",
    species: "npc-species",
    size: "npc-size",
    origin: "npc-origin",
    background: "npc-background",
    appearance: "npc-appearance",
    notes: "npc-notes",
} as const

const TEXT_MAX = 4000

const worldBase = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}/world`

function same(a: NpcFormValues, b: NpcFormValues): boolean {
    return (
        a.name.trim() === b.name.trim() &&
        a.summary.trim() === b.summary.trim() &&
        a.speciesId === b.speciesId &&
        a.size === b.size &&
        (a.origin?.id ?? null) === (b.origin?.id ?? null) &&
        a.background.trim() === b.background.trim() &&
        a.appearance.trim() === b.appearance.trim() &&
        a.notes.trim() === b.notes.trim()
    )
}

function validate(values: NpcFormValues): FieldError[] {
    const errors: FieldError[] = []
    const nameError = validateName(values.name)
    if (nameError) errors.push({ fieldId: FIELD.name, message: nameError })
    const summaryError = validateDescription(values.summary)
    if (summaryError) {
        errors.push({ fieldId: FIELD.summary, message: summaryError.replace("Description", "Summary") })
    }
    if (values.speciesId === "") errors.push({ fieldId: FIELD.species, message: "Choose a species." })
    if (values.size === "") errors.push({ fieldId: FIELD.size, message: "Choose a size." })
    for (const [key, label] of [
        ["background", "Background"],
        ["appearance", "Appearance"],
        ["notes", "GM notes"],
    ] as const) {
        if (values[key].trim().length > TEXT_MAX) {
            errors.push({
                fieldId: FIELD[key],
                message: `${label} must be ${TEXT_MAX} characters or fewer.`,
            })
        }
    }
    return errors
}

function toBody(values: NpcFormValues): NpcFieldsBody {
    const text = (value: string) => (value.trim() === "" ? null : value.trim())
    return {
        name: values.name.trim(),
        summary: text(values.summary),
        species_id: values.speciesId,
        size_category: values.size,
        origin_location_id: values.origin?.id ?? null,
        background: text(values.background),
        appearance: text(values.appearance),
        notes: text(values.notes),
    }
}

function fromView(view: NpcAuthoringView): NpcFormValues {
    return {
        name: view.name,
        summary: view.summary ?? "",
        speciesId: view.species.species_id,
        size: view.size.code,
        origin:
            view.origin === null
                ? null
                : {
                      id: view.origin.entity_id,
                      label: view.origin.name,
                      detail: statusDetail(view.origin.canon_status, view.origin.lifecycle_status),
                  },
        background: view.background ?? "",
        appearance: view.appearance ?? "",
        notes: view.notes ?? "",
    }
}

function Fields({
    campaignId,
    options,
    values,
    setValues,
    errorFor,
    currentSpeciesName,
}: {
    campaignId: string
    options: NpcOptions
    values: NpcFormValues
    setValues: (values: NpcFormValues) => void
    errorFor: (fieldId: string) => string | null
    currentSpeciesName?: string
}) {
    async function searchOrigins(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchLocationParentOptions(campaignId, query, null, signal)
        return page.items.map((item) => ({
            id: item.location_id,
            label: item.name,
            detail: `${item.category.label}, ${statusDetail(item.canon_status, "active")}`,
        }))
    }

    // The NPC's current species may no longer be offered (a newer ruleset
    // version); keep it selectable so an unrelated edit does not silently drop it.
    const offered = options.species.some((s) => s.species_id === values.speciesId)
    const speciesOptions = [
        ...(values.speciesId !== "" && !offered
            ? [{ value: values.speciesId, label: currentSpeciesName ?? "Current species" }]
            : []),
        ...options.species.map((s) => ({ value: s.species_id, label: `${s.name} (${s.ruleset_name})` })),
    ]

    return (
        <>
            <TextField
                id={FIELD.name}
                label="Name"
                value={values.name}
                onChange={(name) => setValues({ ...values, name })}
                required
                maxLength={NAME_MAX}
                error={errorFor(FIELD.name)}
            />
            <TextAreaField
                id={FIELD.summary}
                label="Summary"
                value={values.summary}
                onChange={(summary) => setValues({ ...values, summary })}
                maxLength={DESCRIPTION_MAX}
                error={errorFor(FIELD.summary)}
            />
            <SelectField
                id={FIELD.species}
                label="Species"
                value={values.speciesId}
                placeholder="Choose a species"
                required
                options={speciesOptions}
                error={errorFor(FIELD.species)}
                onChange={(speciesId) => setValues({ ...values, speciesId })}
            />
            <SelectField
                id={FIELD.size}
                label="Size"
                value={values.size}
                placeholder="Choose a size"
                required
                options={options.sizes.map((s) => ({ value: s.code, label: s.label }))}
                error={errorFor(FIELD.size)}
                onChange={(size) => setValues({ ...values, size })}
            />
            <ReferenceCombobox
                id={FIELD.origin}
                label="Origin"
                hint="Where this character comes from."
                value={values.origin}
                onChange={(origin) => setValues({ ...values, origin })}
                search={searchOrigins}
                error={errorFor(FIELD.origin)}
                placeholder="Search locations"
            />
            <TextAreaField
                id={FIELD.background}
                label="Background"
                value={values.background}
                onChange={(background) => setValues({ ...values, background })}
                maxLength={TEXT_MAX}
                error={errorFor(FIELD.background)}
            />
            <TextAreaField
                id={FIELD.appearance}
                label="Appearance"
                value={values.appearance}
                onChange={(appearance) => setValues({ ...values, appearance })}
                maxLength={TEXT_MAX}
                error={errorFor(FIELD.appearance)}
            />
            <TextAreaField
                id={FIELD.notes}
                label="GM notes"
                hint="Visible only to people who can edit canon. Never shown to players."
                value={values.notes}
                onChange={(notes) => setValues({ ...values, notes })}
                maxLength={TEXT_MAX}
                error={errorFor(FIELD.notes)}
            />
        </>
    )
}

const renderCreateFields: ContentCreateConfig<
    NpcOptions,
    NpcFormValues,
    CreateNpcBody,
    unknown
>["renderFields"] = ({ campaignId, options, values, setValues, errorFor }) => (
    <Fields
        campaignId={campaignId}
        options={options}
        values={values}
        setValues={setValues}
        errorFor={errorFor}
    />
)

const createConfig: ContentCreateConfig<NpcOptions, NpcFormValues, CreateNpcBody, NpcReceipt> = {
    noun: "NPC",
    heading: "New NPC",
    lead: "A new NPC is saved as a draft. Only people who can edit canon see it until it is published. This sets who the character is; stats, inventory, and behavior are managed elsewhere.",
    breadcrumbLabel: "World",
    worldPath: worldBase,
    optionsPath: npcOptionsPath,
    canCreate: (options) => options.can_create,
    initialValues: () => EMPTY,
    isDirty: (values, initial) => !same(values, initial),
    validate: (values) => validate(values),
    toBody: (values) => toBody(values),
    create: createNpc,
    resultPath: (campaignId, created) =>
        `${worldBase(campaignId)}/character/${encodeURIComponent(created.npc_id)}`,
    announce: "NPC created as a draft",
    saveLabel: "Create NPC",
    pendingLabel: "Creating…",
    renderFields: renderCreateFields,
}

// Create an NPC draft: /app/:campaignId/characters/npc/new.
export function CreateNpcPage() {
    return <ContentCreatePage config={createConfig} />
}

const playerCharacterCreateConfig: ContentCreateConfig<
    NpcOptions,
    NpcFormValues,
    CreateNpcBody,
    PlayerCharacterReceipt
> = {
    ...createConfig,
    noun: "player character",
    campaignOriginated: true,
    heading: "New player character",
    lead: "A new player character is saved as a draft. Only people who can edit canon see it until it is published. Linking a player to it is done in Access, after it is published.",
    optionsPath: playerCharacterOptionsPath,
    create: createPlayerCharacter,
    resultPath: (campaignId, created) =>
        `${worldBase(campaignId)}/character/${encodeURIComponent(created.player_character_id)}`,
    announce: "Player character created as a draft",
    saveLabel: "Create player character",
}

// Create a player-character draft: /app/:campaignId/characters/pc/new.
export function CreatePlayerCharacterPage() {
    return <ContentCreatePage config={playerCharacterCreateConfig} />
}

const summarize: ContentEditConfig<
    NpcAuthoringView,
    NpcOptions,
    NpcFormValues,
    NpcFieldsBody
>["summarize"] = (values) => (
    <dl className="authoring-fact-list">
        <dt>Name</dt>
        <dd>{values.name}</dd>
        <dt>Summary</dt>
        <dd>{values.summary || "(empty)"}</dd>
        <dt>Size</dt>
        <dd>{values.size || "(none)"}</dd>
        <dt>Origin</dt>
        <dd>{values.origin?.label ?? "(none)"}</dd>
        <dt>Background</dt>
        <dd>{values.background || "(empty)"}</dd>
        <dt>Appearance</dt>
        <dd>{values.appearance || "(empty)"}</dd>
        <dt>GM notes</dt>
        <dd>{values.notes || "(empty)"}</dd>
    </dl>
)

const editConfig: ContentEditConfig<NpcAuthoringView, NpcOptions, NpcFormValues, NpcFieldsBody> = {
    noun: "NPC",
    heading: "Edit NPC",
    entityParam: "characterId",
    breadcrumbLabel: "World",
    worldPath: worldBase,
    detailPath: (campaignId, id) => `${worldBase(campaignId)}/character/${encodeURIComponent(id)}`,
    viewPath: npcAuthoringPath,
    optionsPath: npcOptionsPath,
    name: (view) => view.name,
    valuesFromView: fromView,
    same,
    validate: (values) => validate(values),
    toBody: (values) => toBody(values),
    update: updateNpc,
    renderFields: ({ campaignId, view, options, values, setValues, errorFor }) => (
        <Fields
            campaignId={campaignId}
            options={options}
            values={values}
            setValues={setValues}
            errorFor={errorFor}
            currentSpeciesName={view.species.name}
        />
    ),
    summarize,
    canonWarning:
        "This NPC is published. People with access will see the change. For a change in meaning, create a replacement and supersede this NPC instead.",
    saved: "NPC saved",
}

// Edit an NPC's identity (reached through EditCharacterPage).
export function EditNpcPage() {
    return <ContentEditPage config={editConfig} />
}

const playerCharacterEditConfig: ContentEditConfig<
    PlayerCharacterAuthoringView,
    NpcOptions,
    NpcFormValues,
    NpcFieldsBody
> = {
    ...(editConfig as unknown as ContentEditConfig<
        PlayerCharacterAuthoringView,
        NpcOptions,
        NpcFormValues,
        NpcFieldsBody
    >),
    noun: "player character",
    campaignOriginated: true,
    heading: "Edit player character",
    viewPath: playerCharacterAuthoringPath,
    optionsPath: playerCharacterOptionsPath,
    update: updatePlayerCharacter,
    canonWarning:
        "This player character is published. People with access will see the change. For a change in meaning, create a replacement and supersede this character instead.",
    saved: "Player character saved",
}

export function EditPlayerCharacterPage() {
    return <ContentEditPage config={playerCharacterEditConfig} />
}

// One edit route for both kinds: /app/:campaignId/characters/:characterId/edit.
// Each kind's authoring read is a 404 for the other, so the NPC read decides:
// found -> the NPC editor; otherwise -> the player-character editor, which shows
// its own "does not exist or no access" state for anything else.
export function EditCharacterPage() {
    const params = useParams()
    const probe = useAuthoringResource<NpcAuthoringView>(
        npcAuthoringPath(params.campaignId ?? "", params.characterId ?? ""),
    )
    if (probe.state.kind === "loading") {
        return <p role="status">Loading character…</p>
    }
    return probe.state.kind === "ready" ? <EditNpcPage /> : <EditPlayerCharacterPage />
}

// Create a character: /app/:campaignId/characters/new. The two kinds are never
// guessed -- the author chooses one explicitly.
export function ChooseCharacterTypePage() {
    const params = useParams()
    const base = `/app/${encodeURIComponent(params.campaignId ?? "")}/characters`
    return (
        <section className="authoring-page" aria-labelledby="choose-character-heading">
            <h1 id="choose-character-heading">New character</h1>
            <p className="authoring-page__lead">What kind of character is this?</p>
            <ul className="authoring-choice-list">
                <li>
                    <Link className="authoring-button" to={`${base}/npc/new`}>
                        New NPC
                    </Link>
                    <p>A character the GM or AI portrays.</p>
                </li>
                <li>
                    <Link className="authoring-button" to={`${base}/pc/new`}>
                        New player character
                    </Link>
                    <p>
                        A character a player will control. Link the player in Access once it is
                        published.
                    </p>
                </li>
            </ul>
        </section>
    )
}
