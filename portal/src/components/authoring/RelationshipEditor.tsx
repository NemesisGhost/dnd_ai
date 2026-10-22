import { useCallback, useEffect, useRef, useState } from "react"
import type { ReactNode } from "react"
import { Link } from "react-router"
import { relationshipAuthoringPath, runRelationshipCommand } from "../../api/relationshipAuthoring"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import { useKeptData } from "../../hooks/useKeptData"
import type {
    PerspectiveView,
    RelationshipCommand,
    RelationshipOptions,
    RelationshipView,
    TypedFields,
} from "../../types/relationshipAuthoring"
import { RELATIONSHIP_CODE_MESSAGE, counterparts, periodSummary } from "../../utils/relationshipForm"
import { DraftConflict } from "../quests/DraftConflict"
import { useUnsavedReport } from "../quests/useUnsavedReport"
import type { ReportUnsaved } from "../quests/useUnsavedReport"
import { StaleReadNotice } from "../StaleReadNotice"
import { useAnnounce } from "./announcer"
import { ConfirmDialog } from "./ConfirmDialog"
import { SelectField, TextAreaField, TextField } from "./fields"
import { MutationStatusMessage, StaleWriteNotice } from "./feedback"
import { focusSoon } from "./focusSoon"
import { useRowDraft } from "./useRowDraft"
import { WorldTimePicker } from "./WorldTimePicker"
import "./authoring.css"

interface Props {
    campaignId: string
    relationshipId: string
    // The record whose page this is, for naming the counterpart.
    entityId: string
    options: RelationshipOptions
    // Where a membership is managed (its Members and offices section), for a membership.
    manage: { to: string; label: string } | null
    // Runs after a write, once this editor has read the record again: the roster reads its list.
    onChanged: (change?: { archived?: boolean }) => Promise<void>
    onUnsaved: ReportUnsaved
}

type Mode = "details" | "perspectives" | "end"

const num = (value: string): number | null => (value.trim() === "" ? null : Number(value))
const text = (value: unknown): string => (value === null || value === undefined ? "" : String(value))
const orNull = (value: string): string | null => (value.trim() === "" ? null : value.trim())
const PUBLIC_OPTIONS = [
    { value: "yes", label: "Yes" },
    { value: "no", label: "No, only editors see it" },
]
const YES_NO = [
    { value: "no", label: "No" },
    { value: "yes", label: "Yes" },
]

// What every form of one editor shares: where to write, how to read again afterwards, and the two
// small registries (unsaved input, requests in flight) that let the editor name them. Each form keeps
// its own draft and its own request, so saving or failing in one never touches another.
interface Shared {
    campaignId: string
    relationshipId: string
    busy: boolean
    markDirty: (key: string, label: string | null) => void
    markPending: (key: string, pending: boolean) => void
    afterWrite: (result: RelationshipView, message: string, change?: { archived?: boolean }) => Promise<string>
    loadLatest: () => void
}

// One form's request, with its own status. The values the form sent are accepted into its draft when
// the server confirms, before the record is read again, so the form is clean whether or not that
// read succeeds.
function useFormCommand(shared: Shared, scope: string) {
    const { reload } = useSession()
    const meta = useRef<{ accept: () => void; message: string; change?: { archived?: boolean } } | null>(null)
    const [note, setNote] = useState<string | null>(null)
    const mutation = useAuthoringMutation<RelationshipCommand, RelationshipView>({
        scopeKey: `relationship:${shared.relationshipId}:${scope}`,
        request: (command, ctx) => runRelationshipCommand(shared.campaignId, shared.relationshipId, command, ctx),
        onSuccess: async (result) => {
            const sent = meta.current
            if (sent === null) return
            sent.accept()
            setNote(await shared.afterWrite(result, sent.message, sent.change))
        },
    })
    const pending = mutation.status.kind === "pending"
    const { markPending } = shared
    useEffect(() => {
        markPending(scope, pending)
        return () => markPending(scope, false)
    }, [markPending, scope, pending])
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const explained = error?.code ? (RELATIONSHIP_CODE_MESSAGE[error.code] ?? null) : null
    const run = (
        command: RelationshipCommand,
        sent: { accept: () => void; message: string; change?: { archived?: boolean } },
    ) => {
        meta.current = sent
        setNote(null)
        mutation.submit(command)
    }
    const feedback: ReactNode =
        error?.kind === "stale" ? (
            <>
                <StaleWriteNotice
                    onLoadLatest={() => {
                        mutation.reset()
                        shared.loadLatest()
                    }}
                />
                <p className="authoring-note">What you typed in this form is kept; nothing was saved.</p>
            </>
        ) : explained !== null ? (
            <p role="alert">{explained}</p>
        ) : error !== null ? (
            <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
        ) : null
    return { run, pending, note, feedback, disabled: shared.busy || pending }
}

// The form's own report that its last save went through; shown only while nothing further is unsent.
function SavedNote({ note, dirty }: { note: string | null; dirty: boolean }) {
    if (note === null || dirty) return null
    return (
        <p role="status" className="authoring-note">
            {note}
        </p>
    )
}

// Registers a form's unsent input with the editor for as long as the form is mounted.
function useDirtyMark(shared: Shared, key: string, label: string, dirty: boolean) {
    const { markDirty } = shared
    useEffect(() => {
        markDirty(key, dirty ? label : null)
        return () => markDirty(key, null)
    }, [markDirty, key, label, dirty])
}

// One relationship, expanded under its row: its details, how each participant sees it, and how it
// ends or is archived. Every change names the version the editor last read.
export function RelationshipEditor({
    campaignId,
    relationshipId,
    entityId,
    options,
    manage,
    onChanged,
    onUnsaved,
}: Props) {
    const announce = useAnnounce()
    const detail = useAuthoringResource<RelationshipView>(relationshipAuthoringPath(campaignId, relationshipId))
    const { data: view, stale } = useKeptData(detail.state)
    const [dirty, setDirty] = useState<Record<string, string>>({})
    const [pending, setPending] = useState<Record<string, boolean>>({})
    const [mode, setMode] = useState<Mode>("details")
    const [confirmArchive, setConfirmArchive] = useState(false)
    const headingId = `relationship-editor-heading-${relationshipId}`

    const markDirty = useCallback((key: string, label: string | null) => {
        setDirty((current) => {
            if ((current[key] ?? null) === label) return current
            const next = { ...current }
            if (label === null) delete next[key]
            else next[key] = label
            return next
        })
    }, [])
    const markPending = useCallback((key: string, value: boolean) => {
        setPending((current) => {
            if ((current[key] ?? false) === value) return current
            return { ...current, [key]: value }
        })
    }, [])
    const labels = Object.values(dirty)
    useUnsavedReport(onUnsaved, `relationships:editor:${relationshipId}`, labels)
    const busy = Object.values(pending).some(Boolean)

    // After a write: read this record again, say what happened (including when the read failed, so
    // nobody repeats a command that already went through), then let the roster read its list.
    const afterWrite = async (result: RelationshipView, message: string, change?: { archived?: boolean }) => {
        await detail.refetch()
        const note = !detail.refreshOk.current
            ? "Saved. The latest version could not be loaded; do not save it again."
            : result.changed === false
              ? "Nothing changed"
              : message
        announce(note)
        await onChanged(change)
        return note
    }
    const shared: Shared = {
        campaignId,
        relationshipId,
        busy,
        markDirty,
        markPending,
        afterWrite,
        loadLatest: () => void detail.refetch(),
    }
    const lifecycle = useFormCommand(shared, "lifecycle")

    // Focus the heading once, when the record first appears.
    const focused = useRef(false)
    const ready = view !== null
    useEffect(() => {
        if (ready && !focused.current) {
            focused.current = true
            focusSoon(headingId)
        }
    }, [ready, headingId])

    if (view === null) {
        return detail.state.kind === "loading" ? (
            <p role="status">Loading the relationship…</p>
        ) : (
            <div role="alert">
                <p>This relationship could not be loaded.</p>
                <button type="button" className="authoring-button" onClick={() => void detail.refetch()}>
                    Try again
                </button>
            </div>
        )
    }

    const can = (action: string) => view.available_actions.includes(action)
    // A membership is the same record the organization's Members and offices edits. Its office, rank,
    // visibility, start and end are corrected, changed and ended there (a change of office keeps its
    // history); only archive, restore and the participants' views exist nowhere else, so they stay.
    const isMembership = view.kind === "membership"
    const archived = view.lifecycle_status !== "active"
    const who = counterparts(view.participants, entityId)
    const unsavedIn = (prefix: string) => Object.keys(dirty).some((key) => key.startsWith(prefix))
    const holders = view.participants.filter((p, i, all) => all.findIndex((q) => q.entity_id === p.entity_id) === i)
    const mark = (prefix: string) => (unsavedIn(prefix) ? " (unsaved)" : "")
    // Archiving replaces the editing forms with read-only text, so unsent input there would be lost.
    const unsentEdits = Object.entries(dirty)
        .filter(([key]) => key === "details" || key.startsWith("perspective:"))
        .map(([, label]) => label)
    const archive = () =>
        lifecycle.run(
            { op: "archive", body: { expected_row_version: view.row_version } },
            { accept: () => undefined, message: "Relationship archived", change: { archived: true } },
        )
    const modes: { mode: Mode; label: string; prefix: string }[] = [
        { mode: "details", label: "Details", prefix: "details" },
        { mode: "perspectives", label: "Perspectives", prefix: "perspective:" },
        { mode: "end", label: "End or archive", prefix: "end" },
    ]

    return (
        <div className="relationship-editor" aria-label={`Relationship ${view.relationship_type_label}`}>
            {stale ? <StaleReadNotice what="relationship" onRetry={() => void detail.refetch()} /> : null}
            <h4 id={headingId} tabIndex={-1} className="relationship-editor__heading">
                {view.relationship_type_label} with {who}
            </h4>
            <p className="relationship-editor__summary">
                {view.kind_label} · {periodSummary(view)}
                {view.kind === "political" && typeof view.typed.is_active === "boolean"
                    ? ` · In force: ${view.typed.is_active ? "Yes" : "No"}`
                    : ""}
                {view.current_status_label ? ` · Timeline status: ${view.current_status_label}` : ""}
            </p>
            {view.policy_conflicts.length > 0 ? (
                <p className="authoring-note" role="status">
                    This relationship does not fit the current rules: {view.policy_conflicts.join(" ")} You can still
                    correct its details, end it or archive it; to connect different records, end or archive it and add
                    a new one.
                </p>
            ) : null}
            <dl className="relationship-editor__participants">
                {view.participants.map((p) => (
                    <div key={`${p.entity_id}-${p.role}`}>
                        <dt>{p.role_label}</dt>
                        <dd>{p.name}</dd>
                    </div>
                ))}
            </dl>
            <div className="relationship-roster__modes" role="group" aria-label="Sections of this relationship">
                {modes.map((m) => (
                    <button
                        key={m.mode}
                        type="button"
                        className="authoring-button"
                        aria-pressed={mode === m.mode}
                        onClick={() => setMode(m.mode)}
                    >
                        {m.label}
                        {mark(m.prefix)}
                    </button>
                ))}
            </div>

            <div hidden={mode !== "details"}>
                {archived ? (
                    <ArchivedFacts view={view} />
                ) : isMembership ? (
                    <MembershipFacts view={view} manage={manage} />
                ) : can("update") ? (
                    <DetailsForm view={view} options={options} shared={shared} campaignId={campaignId} />
                ) : (
                    <p className="authoring-note">Nothing in this relationship can be corrected here.</p>
                )}
            </div>

            <div hidden={mode !== "perspectives"}>
                {can("set_perspective") ? (
                    <PerspectiveSection view={view} holders={holders} options={options} shared={shared} />
                ) : (
                    <p className="authoring-note">
                        {archived ? "Restore it to set perspectives." : "Perspectives cannot be set here."}
                    </p>
                )}
            </div>

            <div hidden={mode !== "end"}>
                <ul className="relationship-editor__explain">
                    <li>
                        <strong>Correct</strong> a mistake in Details.
                    </li>
                    <li>
                        <strong>End</strong> records that it stopped in the story and keeps it in history.
                    </li>
                    <li>
                        <strong>Archive</strong> takes it out of use and hides it from players. Restore brings it back.
                    </li>
                </ul>
                {isMembership && !archived ? (
                    <p className="authoring-note">
                        Ending a membership is done in{" "}
                        {manage === null ? "the organization’s Members and offices" : <Link to={manage.to}>Members and offices</Link>}
                        , where a change of office is kept as history.
                    </p>
                ) : null}
                {can("end") && !isMembership ? (
                    <EndForm view={view} shared={shared} campaignId={campaignId} />
                ) : !archived && !isMembership ? (
                    <p className="authoring-note">
                        {view.ended !== null
                            ? `Ended ${view.ended}.`
                            : view.started === null
                              ? "Set when it started (in Details) before ending it."
                              : "It cannot be ended here."}
                    </p>
                ) : null}
                {lifecycle.feedback}
                <div className="authoring-actions">
                    {can("archive") ? (
                        <button
                            type="button"
                            className="authoring-button"
                            disabled={lifecycle.disabled}
                            onClick={() => (unsentEdits.length > 0 ? setConfirmArchive(true) : archive())}
                        >
                            Archive relationship
                        </button>
                    ) : null}
                    {can("restore") ? (
                        <button
                            type="button"
                            className="authoring-button"
                            disabled={lifecycle.disabled}
                            onClick={() =>
                                lifecycle.run(
                                    { op: "restore", body: { expected_row_version: view.row_version } },
                                    { accept: () => undefined, message: "Relationship restored" },
                                )
                            }
                        >
                            Restore relationship
                        </button>
                    ) : null}
                </div>
                <SavedNote note={lifecycle.note} dirty={false} />
            </div>
            <ConfirmDialog
                open={confirmArchive}
                title="Archive and discard unsaved input?"
                description={`Archiving closes the editing forms; your unsaved ${unsentEdits.join(" and ")} will be discarded.`}
                confirmLabel="Archive and discard"
                cancelLabel="Keep editing"
                onConfirm={() => {
                    setConfirmArchive(false)
                    archive()
                }}
                onCancel={() => setConfirmArchive(false)}
            />
        </div>
    )
}

// What the record says, read-only: a membership's, or any archived relationship's.
function Facts({ rows }: { rows: [string, string][] }) {
    return (
        <dl className="authoring-fact-list">
            {rows.map(([label, value]) => (
                <div key={label} className="authoring-fact-list__row">
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                </div>
            ))}
        </dl>
    )
}

// A membership's details, read-only. They are managed in the organization's Members and offices.
function MembershipFacts({ view, manage }: { view: RelationshipView; manage: { to: string; label: string } | null }) {
    const office = text(view.typed.role)
    const rank = text(view.typed.rank)
    return (
        <>
            <Facts
                rows={[
                    ["Office", office === "" ? "None" : office],
                    ["Rank", rank === "" ? "None" : rank],
                    ["Known to the public", view.typed.is_public === false ? "No, only editors see it" : "Yes"],
                ]}
            />
            <p className="authoring-note">
                Office, rank, dates and ending a membership are managed in the organization&rsquo;s{" "}
                {manage === null ? "Members and offices" : <Link to={manage.to}>Members and offices</Link>}, where a
                change of office is kept as history.
            </p>
        </>
    )
}

function ArchivedFacts({ view }: { view: RelationshipView }) {
    const rows: [string, string][] = [
        ["Description", view.description ?? "None"],
        ["Period", periodSummary(view)],
    ]
    const typed = view.typed
    if (view.kind === "family") rows.push(["Family name", text(typed.family_unit_name) || "None"])
    if (view.kind === "employment") rows.push(["Job title", text(typed.job_title) || "None"])
    if (view.kind === "ownership") {
        rows.push(["Share", typed.ownership_share === null || typed.ownership_share === undefined ? "None" : `${text(typed.ownership_share)}%`])
        rows.push(["Known to the public", typed.is_public === false ? "No, only editors see it" : "Yes"])
    }
    if (view.kind === "political") {
        rows.push(["In force", typed.is_active === false ? "No" : "Yes"])
        rows.push(["Terms", text(typed.treaty_terms) || "None"])
    }
    if (view.kind === "route") {
        rows.push(["Distance", text(typed.distance_text) || "None"])
        rows.push(["Travel time", text(typed.travel_time_text) || "None"])
        rows.push(["Mode of travel", text(typed.travel_mode) || "None"])
        rows.push(["Concealed", typed.is_hidden === true ? "Yes" : "No"])
    }
    if (view.kind === "membership") {
        rows.push(["Office", text(typed.role) || "None"])
        rows.push(["Rank", text(typed.rank) || "None"])
        rows.push(["Known to the public", typed.is_public === false ? "No, only editors see it" : "Yes"])
    }
    return (
        <>
            <Facts rows={rows} />
            <p className="authoring-note">This relationship is archived. Restore it to make changes.</p>
        </>
    )
}

// The editable fields of this kind only, as the form holds them.
function serverDetails(view: RelationshipView): Record<string, string> {
    const values: Record<string, string> = {
        description: view.description ?? "",
        start: view.started_world_time_id ?? "",
    }
    const typed = view.typed
    if (view.kind === "family") values.unit = text(typed.family_unit_name)
    if (view.kind === "employment") values.title = text(typed.job_title)
    if (view.kind === "ownership") {
        values.share = text(typed.ownership_share)
        values.isPublic = typed.is_public === false ? "no" : "yes"
    }
    if (view.kind === "political") {
        values.active = typed.is_active === false ? "no" : "yes"
        values.terms = text(typed.treaty_terms)
    }
    if (view.kind === "route") {
        values.distance = text(typed.distance_text)
        values.duration = text(typed.travel_time_text)
        values.mode = text(typed.travel_mode)
        values.hidden = typed.is_hidden === true ? "yes" : "no"
    }
    return values
}

function DetailsForm({
    view,
    options,
    shared,
    campaignId,
}: {
    view: RelationshipView
    options: RelationshipOptions
    shared: Shared
    campaignId: string
}) {
    const draft = useRowDraft(serverDetails(view))
    const command = useFormCommand(shared, "details")
    useDirtyMark(shared, "details", "relationship details", draft.dirty)
    const [problem, setProblem] = useState<string | null>(null)
    const v = draft.values
    const set = (name: string) => (value: string) => draft.setValues({ ...v, [name]: value })
    const id = view.relationship_id

    function typedFields(): TypedFields {
        const typed: TypedFields = {}
        if (view.kind === "family") typed.family_unit_name = orNull(v.unit ?? "")
        if (view.kind === "employment") typed.job_title = orNull(v.title ?? "")
        if (view.kind === "ownership") {
            typed.ownership_share = num(v.share ?? "")
            typed.is_public = v.isPublic === "yes"
        }
        if (view.kind === "route") {
            typed.distance_text = orNull(v.distance ?? "")
            typed.travel_time_text = orNull(v.duration ?? "")
            typed.travel_mode = orNull(v.mode ?? "")
            typed.is_hidden = v.hidden === "yes"
        }
        if (view.kind === "political") {
            typed.is_active = v.active === "yes"
            typed.treaty_terms = orNull(v.terms ?? "")
        }
        return typed
    }

    return (
        <form
            noValidate
            aria-label="Edit relationship"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (draft.conflict) return
                const parsed = num(v.share ?? "")
                if (view.kind === "ownership" && parsed !== null && (!Number.isInteger(parsed) || parsed < 0 || parsed > 100)) {
                    setProblem("Share is a whole number from 0 to 100.")
                    return
                }
                setProblem(null)
                const sent = { ...v }
                command.run(
                    {
                        op: "update",
                        body: {
                            expected_row_version: view.row_version,
                            description: orNull(v.description ?? ""),
                            started_world_time_id: v.start === "" ? null : (v.start ?? null),
                            ...typedFields(),
                        },
                    },
                    { accept: () => draft.accept(sent), message: "Relationship saved" },
                )
            }}
        >
            <p className="authoring-note">
                Saving corrects the record. To record that it stopped in the story, use End or archive.
            </p>
            {draft.conflict ? (
                <DraftConflict what="These details" onLatest={draft.loadLatest} onKeep={draft.keepMine} />
            ) : null}
            {command.feedback}
            <TextAreaField
                id={`rel-description-${id}`}
                label="Description"
                value={v.description ?? ""}
                onChange={set("description")}
                maxLength={options.limits.text_max_length}
            />
            <WorldTimePicker
                campaignId={campaignId}
                id={`rel-start-${id}`}
                label="Started"
                value={v.start ?? ""}
                onChange={set("start")}
            />
            {view.kind === "family" ? (
                <TextField id={`rel-unit-${id}`} label="Family name" value={v.unit ?? ""} onChange={set("unit")} />
            ) : null}
            {view.kind === "employment" ? (
                <TextField id={`rel-title-${id}`} label="Job title" value={v.title ?? ""} onChange={set("title")} />
            ) : null}
            {view.kind === "ownership" ? (
                <>
                    <TextField
                        id={`rel-share-${id}`}
                        label="Share (0 to 100)"
                        value={v.share ?? ""}
                        onChange={set("share")}
                        error={problem}
                    />
                    <SelectField
                        id={`rel-public-${id}`}
                        label="Known to the public"
                        value={v.isPublic ?? "yes"}
                        options={PUBLIC_OPTIONS}
                        onChange={set("isPublic")}
                    />
                </>
            ) : null}
            {view.kind === "route" ? (
                <>
                    <TextField id={`rel-distance-${id}`} label="Distance" value={v.distance ?? ""} onChange={set("distance")} />
                    <TextField id={`rel-duration-${id}`} label="Travel time" value={v.duration ?? ""} onChange={set("duration")} />
                    <TextField id={`rel-mode-${id}`} label="Mode of travel" value={v.mode ?? ""} onChange={set("mode")} />
                    <SelectField
                        id={`rel-hidden-${id}`}
                        label="Concealed"
                        hint="Only editors see a concealed route."
                        value={v.hidden ?? "no"}
                        options={YES_NO}
                        onChange={set("hidden")}
                    />
                </>
            ) : null}
            {view.kind === "political" ? (
                <>
                    <SelectField
                        id={`rel-active-${id}`}
                        label="In force"
                        value={v.active ?? "yes"}
                        options={[
                            { value: "yes", label: "Yes" },
                            { value: "no", label: "No" },
                        ]}
                        onChange={set("active")}
                    />
                    <TextAreaField id={`rel-terms-${id}`} label="Terms" value={v.terms ?? ""} onChange={set("terms")} />
                </>
            ) : null}
            <button type="submit" className="authoring-button authoring-button--primary" disabled={command.disabled || draft.conflict}>
                Save relationship
            </button>
            <SavedNote note={command.note} dirty={draft.dirty} />
        </form>
    )
}

function EndForm({ view, shared, campaignId }: { view: RelationshipView; shared: Shared; campaignId: string }) {
    const [when, setWhen] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    const command = useFormCommand(shared, "end")
    useDirtyMark(shared, "end", "an end time", when !== "")
    return (
        <form
            noValidate
            aria-label="End relationship"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (when === "") {
                    setProblem("Choose when it ended.")
                    return
                }
                setProblem(null)
                command.run(
                    { op: "end", body: { expected_row_version: view.row_version, ended_world_time_id: when } },
                    { accept: () => setWhen(""), message: "Relationship ended" },
                )
            }}
        >
            {command.feedback}
            <WorldTimePicker
                campaignId={campaignId}
                id={`rel-end-${view.relationship_id}`}
                label="Ended"
                value={when}
                onChange={setWhen}
                error={problem}
            />
            <button type="submit" className="authoring-button" disabled={command.disabled}>
                End relationship
            </button>
            <SavedNote note={command.note} dirty={when !== ""} />
        </form>
    )
}

type Holder = RelationshipView["participants"][number]

// Every participant's view has its own form and draft, all kept mounted: choosing another
// participant only shows another form, so nothing typed in one is lost.
function PerspectiveSection({
    view,
    holders,
    options,
    shared,
}: {
    view: RelationshipView
    holders: Holder[]
    options: RelationshipOptions
    shared: Shared
}) {
    const [holder, setHolder] = useState(holders[0]?.entity_id ?? "")
    const [unsaved, setUnsaved] = useState<Record<string, boolean>>({})
    const markHolder = useCallback((id: string, value: boolean) => {
        setUnsaved((current) => ((current[id] ?? false) === value ? current : { ...current, [id]: value }))
    }, [])
    return (
        <section aria-label="How each participant sees it">
            <h4>How each participant sees it</h4>
            <div className="relationship-roster__modes" role="group" aria-label="Participant">
                {holders.map((p) => (
                    <button
                        key={p.entity_id}
                        type="button"
                        className="authoring-button"
                        aria-pressed={holder === p.entity_id}
                        onClick={() => setHolder(p.entity_id)}
                    >
                        {p.name}
                        {unsaved[p.entity_id] === true ? " (unsaved)" : ""}
                    </button>
                ))}
            </div>
            {holders.map((p) => (
                <div key={p.entity_id} hidden={holder !== p.entity_id}>
                    <PerspectiveForm
                        view={view}
                        holder={p}
                        existing={view.perspectives.find((x) => x.holder_entity_id === p.entity_id)}
                        options={options}
                        shared={shared}
                        onUnsaved={markHolder}
                    />
                </div>
            ))}
        </section>
    )
}

const RATINGS = ["affinity", "trust", "respect", "fear", "obligation"] as const

function serverPerspective(existing: PerspectiveView | undefined): Record<string, string> {
    return {
        affinity: text(existing?.affinity),
        trust: text(existing?.trust),
        respect: text(existing?.respect),
        fear: text(existing?.fear),
        obligation: text(existing?.obligation),
        tone: existing?.emotional_tone ?? "",
        interpretation: existing?.private_interpretation ?? "",
    }
}

function PerspectiveForm({
    view,
    holder,
    existing,
    options,
    shared,
    onUnsaved,
}: {
    view: RelationshipView
    holder: Holder
    existing: PerspectiveView | undefined
    options: RelationshipOptions
    shared: Shared
    onUnsaved: (holderId: string, unsaved: boolean) => void
}) {
    const draft = useRowDraft(serverPerspective(existing))
    const command = useFormCommand(shared, `perspective:${holder.entity_id}`)
    useDirtyMark(shared, `perspective:${holder.entity_id}`, `${holder.name}’s perspective`, draft.dirty)
    useEffect(() => {
        onUnsaved(holder.entity_id, draft.dirty)
    }, [onUnsaved, holder.entity_id, draft.dirty])
    const [problem, setProblem] = useState<string | null>(null)
    const v = draft.values
    const { stance_min: min, stance_max: max } = options.limits
    const key = `${view.relationship_id}-${holder.entity_id}`
    return (
        <form
            noValidate
            aria-label="Set perspective"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (draft.conflict) return
                const ratings = RATINGS.map((name) => num(v[name] ?? ""))
                if (ratings.some((n) => n !== null && (!Number.isInteger(n) || n < min || n > max))) {
                    setProblem(`Each rating is a whole number from ${min} to ${max}.`)
                    return
                }
                setProblem(null)
                const sent = { ...v }
                command.run(
                    {
                        op: "perspective",
                        body: {
                            expected_row_version: view.row_version,
                            holder_entity_id: holder.entity_id,
                            affinity: ratings[0] ?? null,
                            trust: ratings[1] ?? null,
                            respect: ratings[2] ?? null,
                            fear: ratings[3] ?? null,
                            obligation: ratings[4] ?? null,
                            emotional_tone: orNull(v.tone ?? ""),
                            private_interpretation: orNull(v.interpretation ?? ""),
                        },
                    },
                    { accept: () => draft.accept(sent), message: `Perspective saved for ${holder.name}` },
                )
            }}
        >
            {draft.conflict ? (
                <DraftConflict
                    what={`${holder.name}’s perspective`}
                    onLatest={draft.loadLatest}
                    onKeep={draft.keepMine}
                />
            ) : null}
            {command.feedback}
            {RATINGS.map((name) => (
                <TextField
                    key={name}
                    id={`persp-${name}-${key}`}
                    label={name[0]!.toUpperCase() + name.slice(1)}
                    value={v[name] ?? ""}
                    onChange={(value) => draft.setValues({ ...v, [name]: value })}
                    error={name === "affinity" ? problem : null}
                />
            ))}
            <TextField
                id={`persp-tone-${key}`}
                label="Emotional tone"
                value={v.tone ?? ""}
                onChange={(value) => draft.setValues({ ...v, tone: value })}
            />
            <TextAreaField
                id={`persp-private-${key}`}
                label="Private interpretation"
                hint="Only editors see this."
                value={v.interpretation ?? ""}
                onChange={(value) => draft.setValues({ ...v, interpretation: value })}
            />
            <button type="submit" className="authoring-button authoring-button--primary" disabled={command.disabled || draft.conflict}>
                Save perspective
            </button>
            <SavedNote note={command.note} dirty={draft.dirty} />
        </form>
    )
}
