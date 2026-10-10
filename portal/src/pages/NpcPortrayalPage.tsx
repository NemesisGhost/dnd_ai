import { useState } from "react"
import { Link, useParams } from "react-router"
import { apiRequest } from "../api/http"
import { npcPortrayalPath, saveNpcPortrayal, setNpcDetailLevel } from "../api/npcPortrayal"
import { useAnnounce } from "../components/authoring/announcer"
import { SelectField, TextAreaField, TextField } from "../components/authoring/fields"
import { MutationStatusMessage, StaleWriteNotice } from "../components/authoring/feedback"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import type { NpcPortrayalView } from "../types/npcPortrayal"
import "../components/authoring/authoring.css"

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    portrayal_version_not_found: "That version does not exist.",
}

const nullable = (value: string): string | null => (value.trim() === "" ? null : value.trim())

// /app/:campaignId/characters/:characterId/portrayal — how to play an NPC, GM only. Each save
// appends a version; nothing here is shown to players or read by the AI yet.
export function NpcPortrayalPage() {
    const { campaignId = "", characterId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const { state, refetch } = useAuthoringResource<NpcPortrayalView>(
        npcPortrayalPath(campaignId, characterId),
    )
    const headingRef = usePageArrival(state.kind === "ready")
    return (
        <section className="authoring-page" aria-labelledby="portrayal-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={`/app/${encodeURIComponent(campaignId)}/world/character/${encodeURIComponent(characterId)}`}>
                    {state.kind === "ready" ? state.data.name : "Character"}
                </Link>
            </p>
            <h1 id="portrayal-heading" ref={headingRef} tabIndex={-1}>
                Portrayal
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to edit how this NPC is played.</p>
            ) : state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : state.kind !== "ready" ? (
                <p role="alert">This NPC does not exist, or you do not have access to it.</p>
            ) : (
                <Loaded
                    key={`${state.data.current_version}:${state.data.row_version}`}
                    campaignId={campaignId}
                    view={state.data}
                    refetch={refetch}
                />
            )}
        </section>
    )
}

function Loaded({
    campaignId,
    view,
    refetch,
}: {
    campaignId: string
    view: NpcPortrayalView
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [values, setValues] = useState<Record<string, string>>(
        Object.fromEntries(view.field_labels.map((f) => [f.name, view.fields[f.name] ?? ""])),
    )
    const [note, setNote] = useState("")
    const [level, setLevel] = useState(view.detail_level)
    const [done, setDone] = useState<string | null>(null)
    const [problem, setProblem] = useState<string | null>(null)
    const [shown, setShown] = useState<NpcPortrayalView | null>(null)

    const saveMutation = useAuthoringMutation<Record<string, string | number | null>, NpcPortrayalView>({
        scopeKey: `portrayal:${view.npc_id}`,
        request: (body, ctx) => saveNpcPortrayal(campaignId, view.npc_id, body, ctx),
        onSuccess: async () => {
            const message = done
            setDone(null)
            setNote("")
            await refetch()
            if (message !== null) announce(message)
        },
    })
    const levelMutation = useAuthoringMutation<
        { expected_row_version: number; detail_level: string },
        NpcPortrayalView
    >({
        scopeKey: `detail-level:${view.npc_id}`,
        request: (body, ctx) => setNpcDetailLevel(campaignId, view.npc_id, body, ctx),
        onSuccess: async () => {
            await refetch()
            announce("Detail level saved")
        },
    })
    const error =
        saveMutation.status.kind === "error"
            ? saveMutation.status.error
            : levelMutation.status.kind === "error"
              ? levelMutation.status.error
              : null
    const busy = saveMutation.status.kind === "pending" || levelMutation.status.kind === "pending"
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const max = view.limits.field_max_length

    async function showVersion(version: number) {
        setShown(
            await apiRequest<NpcPortrayalView>("GET", npcPortrayalPath(campaignId, view.npc_id, version)),
        )
    }

    return (
        <>
            {error?.kind === "stale" ? (
                <StaleWriteNotice
                    onLoadLatest={() => {
                        saveMutation.reset()
                        levelMutation.reset()
                        void refetch()
                    }}
                />
            ) : explained !== null ? (
                <p role="alert">{explained}</p>
            ) : error !== null ? (
                <MutationStatusMessage
                    error={error}
                    onRetry={() => (saveMutation.retry(), levelMutation.retry())}
                    onCheckSession={reload}
                />
            ) : null}
            <p className="authoring-note">
                Only people who can edit canon see this. It is not shown to players and is not used
                by the AI.
            </p>
            {view.can_edit ? (
                <form
                    noValidate
                    aria-label="Detail level"
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        levelMutation.submit({
                            expected_row_version: view.row_version,
                            detail_level: level,
                        })
                    }}
                >
                    <SelectField
                        id="npc-detail-level"
                        label="Detail level"
                        hint="How much authoring this NPC deserves."
                        value={level}
                        options={view.detail_levels}
                        onChange={setLevel}
                    />
                    <button type="submit" className="authoring-button" disabled={busy || level === view.detail_level}>
                        Save detail level
                    </button>
                </form>
            ) : (
                <p>This NPC cannot be edited right now.</p>
            )}
            <h2>Profile (version {view.current_version === 0 ? "none yet" : view.current_version})</h2>
            {view.can_edit ? (
                <form
                    noValidate
                    aria-label="Portrayal profile"
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        const tooLong = view.field_labels.find((f) => (values[f.name] ?? "").trim().length > max)
                        if (tooLong !== undefined) {
                            setProblem(`${tooLong.label} must be ${max} characters or fewer.`)
                            return
                        }
                        setProblem(null)
                        setDone("Portrayal saved as a new version")
                        saveMutation.submit({
                            expected_version: view.current_version,
                            ...Object.fromEntries(
                                view.field_labels.map((f) => [f.name, nullable(values[f.name] ?? "")]),
                            ),
                            change_note: nullable(note),
                        })
                    }}
                >
                    {view.field_labels.map((f, index) => (
                        <TextAreaField
                            key={f.name}
                            id={`portrayal-${f.name}`}
                            label={f.label}
                            value={values[f.name] ?? ""}
                            onChange={(value) => setValues({ ...values, [f.name]: value })}
                            maxLength={max}
                            error={index === 0 ? problem : null}
                        />
                    ))}
                    <TextField
                        id="portrayal-note"
                        label="Change note (optional)"
                        value={note}
                        onChange={setNote}
                        maxLength={view.limits.note_max_length}
                    />
                    <button type="submit" className="authoring-button" disabled={busy}>
                        Save new version
                    </button>
                </form>
            ) : null}
            <h2>Versions</h2>
            {view.versions.length === 0 ? (
                <p>No versions saved yet.</p>
            ) : (
                <ul className="authoring-choice-list">
                    {view.versions.map((v) => (
                        <li key={v.version_number}>
                            Version {v.version_number}, {new Date(v.created_at).toLocaleString()}
                            {v.change_note !== null ? `: ${v.change_note}` : ""}{" "}
                            <button
                                type="button"
                                className="authoring-button"
                                onClick={() => void showVersion(v.version_number)}
                            >
                                Show version {v.version_number}
                            </button>
                        </li>
                    ))}
                </ul>
            )}
            {shown !== null ? (
                <section aria-label={`Version ${shown.shown_version}`}>
                    <h3>Version {shown.shown_version}</h3>
                    <dl className="authoring-fact-list">
                        {shown.field_labels.map((f) => (
                            <div key={f.name}>
                                <dt>{f.label}</dt>
                                <dd>{shown.fields[f.name] ?? "(empty)"}</dd>
                            </div>
                        ))}
                    </dl>
                    {view.can_edit ? (
                        <button
                            type="button"
                            className="authoring-button"
                            onClick={() => {
                                setValues(
                                    Object.fromEntries(
                                        shown.field_labels.map((f) => [f.name, shown.fields[f.name] ?? ""]),
                                    ),
                                )
                                setShown(null)
                            }}
                        >
                            Use version {shown.shown_version} as the starting point
                        </button>
                    ) : null}
                </section>
            ) : null}
        </>
    )
}
