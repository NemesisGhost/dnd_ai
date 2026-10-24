import { useEffect, useState } from "react"
import type { ReactNode } from "react"
import { Link } from "react-router"
import { attachSource, createSource, detachSource, provenancePath, sourcesPath } from "../api/sources"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { UseAuthoringResourceResult } from "../hooks/useAuthoringResource"
import type { Provenance, SourceList } from "../types/provenance"
import { useAnnounce } from "./authoring/announcer"
import { SelectField, TextAreaField, TextField } from "./authoring/fields"
import { MutationStatusMessage } from "./authoring/feedback"
import { DetailPanel } from "./DetailPanel"
import "./authoring/authoring.css"

interface Props {
    campaignId: string
    entityId: string
    // The World category of the record, for the provenance link.
    category?: string
    // Reports whether something typed in the forms is not yet attached or written, so the page can
    // protect it when the person leaves.
    onDirtyChange?: (dirty: boolean) => void
    // Where the provenance page's back link returns to (the page that holds this section).
    returnTo?: string
    // Router state to carry with `returnTo` (where the record was opened from), so the way back
    // from the provenance page keeps it. The provenance page validates it.
    returnState?: object
    // The page already supplies the surface, the heading and the labelled region (a staged
    // section panel): render the content only, with no panel, heading or region of its own.
    embedded?: boolean
    // Plain-language context shown above the sources.
    intro?: ReactNode
    // The record's provenance, when the page already loads it (to show a count elsewhere), so the
    // two never disagree after an attach or detach.
    provenance?: UseAuthoringResourceResult<Provenance>
}

type Command =
    | { op: "attach"; sourceId: string }
    | { op: "detach"; sourceId: string }
    | { op: "create"; source_type: string; title: string; reference: string | null }

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    source_invalid: "Choose a source that belongs to this world.",
    source_already_attached: "That source is already attached.",
    source_not_attached: "That source is not attached.",
}

// Editor-only: the sources attached to a record, with a way to attach another (an existing one,
// or a new one written here) or detach one, and a link to the full provenance. Detaching keeps
// the history. Mounts nothing, and sends nothing, for anyone whose provenance read is refused.
export function EntitySourcesSection({
    campaignId,
    entityId,
    category,
    onDirtyChange,
    returnTo,
    returnState,
    embedded = false,
    intro,
    provenance: shared,
}: Props) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const own = useAuthoringResource<Provenance>(shared === undefined ? provenancePath(campaignId, entityId) : null)
    const provenance = shared ?? own
    const sources = useAuthoringResource<SourceList>(sourcesPath(campaignId))
    const [choice, setChoice] = useState("")
    const [type, setType] = useState("")
    const [title, setTitle] = useState("")
    const [reference, setReference] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    const [done, setDone] = useState<string | null>(null)
    const [adding, setAdding] = useState(false)
    const mutation = useAuthoringMutation<Command, unknown>({
        scopeKey: `sources:${entityId}`,
        request: async (command, ctx) => {
            if (command.op === "create") {
                // Two commands, so two keys derived from this one: a retry replays each step, and
                // the server never sees one key used for different commands.
                const created = await createSource(
                    campaignId,
                    { source_type: command.source_type, title: command.title, reference: command.reference },
                    { ...ctx, idempotencyKey: `${ctx.idempotencyKey}.create` },
                )
                return attachSource(campaignId, entityId, created.source_id, {
                    ...ctx,
                    idempotencyKey: `${ctx.idempotencyKey}.attach`,
                })
            }
            return command.op === "attach"
                ? attachSource(campaignId, entityId, command.sourceId, ctx)
                : detachSource(campaignId, entityId, command.sourceId, ctx)
        },
        onSuccess: async () => {
            const message = done
            setDone(null)
            setChoice("")
            setType("")
            setTitle("")
            setReference("")
            await Promise.all([provenance.refetch(), sources.refetch()])
            if (message !== null) announce(message)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const busy = mutation.status.kind === "pending"
    const dirty = choice !== "" || type !== "" || title.trim() !== "" || reference.trim() !== ""
    useEffect(() => {
        onDirtyChange?.(dirty)
        return () => onDirtyChange?.(false)
    }, [dirty, onDirtyChange])

    if (provenance.state.kind !== "ready" || sources.state.kind !== "ready") return null
    const view = provenance.state.data
    const list = sources.state.data
    const attachedIds = new Set(view.links.filter((l) => l.is_attached).map((l) => l.source_id))
    const available = list.items.filter((s) => !attachedIds.has(s.source_id))
    const attached = view.links.filter((l) => l.is_attached)
    // A Reviewer reads where a record came from; changing its sources edits the definition.
    const readOnly = view.can_edit === false
    const run = (command: Command, message: string) => {
        setProblem(null)
        setDone(message)
        mutation.submit(command)
    }

    // The forms stay mounted behind "Add source" while closed, so what was typed (and any error)
    // is still there when they are reopened.
    const body = (
        <>
            {intro}
            {explained !== null ? (
                <p role="alert">{explained}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            {problem !== null ? <p role="alert">{problem}</p> : null}
            <p>
                Created from: <strong>{view.origin?.title ?? "an unrecorded source"}</strong>
                {view.created_by_name !== null ? ` by ${view.created_by_name}` : ""}.{" "}
                <Link
                    to={`/app/${encodeURIComponent(campaignId)}/world/${encodeURIComponent(category ?? "record")}/${encodeURIComponent(entityId)}/provenance`}
                    state={returnTo === undefined ? undefined : { ...returnState, returnTo }}
                >
                    View provenance
                </Link>
            </p>
            {attached.length === 0 ? <p>No further sources attached.</p> : null}
            {readOnly ? (
                <p className="authoring-note">
                    Changing a record's sources edits the shared definition and needs the world Editor role.
                </p>
            ) : (
                <p>
                    <button
                        type="button"
                        className="authoring-button"
                        aria-expanded={adding}
                        aria-controls={`add-source-${entityId}`}
                        onClick={() => setAdding(!adding)}
                    >
                        {adding ? "Hide add source" : "Add source"}
                    </button>
                </p>
            )}
            <ul className="op-list">
                {attached.map((l) => (
                    <li key={l.source_id}>
                        {l.title} ({l.source_type_label})
                        {l.reference !== null ? `: ${l.reference}` : ""}{" "}
                        {readOnly ? null : (
                            <button
                                type="button"
                                className="authoring-button"
                                disabled={busy}
                                onClick={() => run({ op: "detach", sourceId: l.source_id }, "Source detached")}
                            >
                                Detach {l.title}
                            </button>
                        )}
                    </li>
                ))}
            </ul>
            <div id={`add-source-${entityId}`} hidden={readOnly || !adding}>
                {available.length > 0 ? (
                    <form
                        noValidate
                        aria-label="Attach an existing source"
                        className="authoring-form"
                        onSubmit={(event) => {
                            event.preventDefault()
                            if (choice === "") {
                                setProblem("Choose a source to attach.")
                                return
                            }
                            run({ op: "attach", sourceId: choice }, "Source attached")
                        }}
                    >
                        <SelectField
                            id={`attach-source-${entityId}`}
                            label="Source"
                            value={choice}
                            placeholder="Choose a source"
                            options={available.map((s) => ({ value: s.source_id, label: `${s.title} (${s.source_type_label})` }))}
                            onChange={setChoice}
                        />
                        <button type="submit" className="authoring-button" disabled={busy}>
                            Attach source
                        </button>
                    </form>
                ) : null}
                <form
                    noValidate
                    aria-label="Write a new source"
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (type === "" || title.trim() === "") {
                            setProblem("Choose a type and enter a title for the new source.")
                            return
                        }
                        run(
                            {
                                op: "create",
                                source_type: type,
                                title: title.trim(),
                                reference: reference.trim() === "" ? null : reference.trim(),
                            },
                            "Source written and attached",
                        )
                    }}
                >
                    <SelectField
                        id={`new-source-type-${entityId}`}
                        label="Type of source"
                        value={type}
                        placeholder="Choose a type"
                        options={list.source_types}
                        onChange={setType}
                    />
                    <TextField
                        id={`new-source-title-${entityId}`}
                        label="Title"
                        value={title}
                        onChange={setTitle}
                        maxLength={list.limits.title_max_length}
                    />
                    <TextAreaField
                        id={`new-source-reference-${entityId}`}
                        label="Reference (optional)"
                        hint="A page, a section or a note. Only people who can edit canon see it."
                        value={reference}
                        onChange={setReference}
                        maxLength={list.limits.reference_max_length}
                    />
                    <button type="submit" className="authoring-button" disabled={busy}>
                        Write and attach source
                    </button>
                </form>
            </div>
        </>
    )
    return embedded ? (
        <div className="sources-body">{body}</div>
    ) : (
        <DetailPanel title="Sources" headingId={`sources-${entityId}`}>
            {body}
        </DetailPanel>
    )
}
