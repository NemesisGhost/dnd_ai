import { useState } from "react"
import { relationshipAuthoringPath, runRelationshipCommand } from "../api/relationshipAuthoring"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { RefetchOutcome } from "../hooks/useAuthoringResource"
import type { RelationshipCommand, RelationshipView } from "../types/relationshipAuthoring"
import { RELATIONSHIP_CODE_MESSAGE } from "../utils/relationshipForm"
import { useAnnounce } from "./authoring/announcer"
import { SelectField, TextField } from "./authoring/fields"
import { MutationStatusMessage, StaleWriteNotice } from "./authoring/feedback"
import { WorldTimePicker } from "./authoring/WorldTimePicker"
import "./authoring/authoring.css"

type Mode = "correct" | "change" | "end"

const PUBLIC_OPTIONS = [
    { value: "yes", label: "Yes" },
    { value: "no", label: "No, only editors see it" },
]

const clean = (value: string): string | null => (value.trim() === "" ? null : value.trim())
const text = (value: unknown): string => (typeof value === "string" ? value : "")

interface Props {
    campaignId: string
    relationshipId: string
    memberName: string
    // The membership was recorded or ended: the roster reads again and closes this editor.
    onSaved: () => Promise<RefetchOutcome>
    // The roster saved a change it could not read back; the panel reports it and announces it once it can.
    onUnread: (message: string) => void
    onCancel: () => void
}

// One membership, opened from its roster row. It reads the membership itself (so the version, the
// start and the actions it offers are the server's, not guessed from the roster) and offers the
// three different things an editor can mean:
//   - Correct: fix what was entered wrongly, in place (the member and organization never change);
//   - Change office: the member's office or rank changed in the story. The current stint ends at the
//     effective time and a new one starts there, so the earlier office stays in the history;
//   - End: the member left, at a time after they joined.
// Only the form being used is open, each saves on its own, and a refused save keeps what was typed.
export function OrganizationMemberEditor({ campaignId, relationshipId, memberName, onSaved, onUnread, onCancel }: Props) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const { state, refetch } = useAuthoringResource<RelationshipView>(
        relationshipAuthoringPath(campaignId, relationshipId),
    )
    const [mode, setMode] = useState<Mode | null>(null)
    const [done, setDone] = useState("")
    const mutation = useAuthoringMutation<RelationshipCommand, RelationshipView>({
        scopeKey: `org-member:${relationshipId}`,
        request: (command, ctx) => runRelationshipCommand(campaignId, relationshipId, command, ctx),
        // The roster panel reports a change it could not read back, with its own notice.
        ownsRefreshNotice: true,
        onSuccess: async () => {
            const outcome = await onSaved()
            if (outcome === "ok") announce(done)
            else onUnread(done)
            return outcome
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const busy = mutation.status.kind === "pending"
    const explained = error?.code ? (RELATIONSHIP_CODE_MESSAGE[error.code] ?? null) : null
    const run = (command: RelationshipCommand, message: string) => {
        setDone(message)
        mutation.submit(command)
    }

    if (state.kind === "loading") return <p role="status">Loading the membership…</p>
    if (state.kind !== "ready") return <p role="alert">This membership could not be loaded.</p>
    const view = state.data
    const can = (action: string) => view.available_actions.includes(action)
    const modes: { mode: Mode; label: string }[] = [
        ...(can("update") ? [{ mode: "correct" as const, label: "Correct details" }] : []),
        ...(can("update") && can("end") ? [{ mode: "change" as const, label: "Change office or rank" }] : []),
        ...(can("end") ? [{ mode: "end" as const, label: "End membership" }] : []),
    ]
    const active = mode !== null && modes.some((m) => m.mode === mode) ? mode : (modes[0]?.mode ?? null)

    return (
        <div className="member-roster__editor" role="group" aria-label={`Edit membership of ${memberName}`}>
            {error?.kind === "stale" ? (
                <StaleWriteNotice
                    onLoadLatest={() => {
                        mutation.reset()
                        void refetch()
                    }}
                />
            ) : explained !== null ? (
                <p role="alert">{explained}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            {modes.length === 0 ? (
                <p className="authoring-note">This membership cannot be changed here. Restore it from Relationships first.</p>
            ) : (
                <div className="member-roster__modes" role="group" aria-label="What to do">
                    {modes.map((m) => (
                        <button
                            key={m.mode}
                            type="button"
                            className="authoring-button"
                            aria-pressed={active === m.mode}
                            onClick={() => setMode(m.mode)}
                        >
                            {m.label}
                        </button>
                    ))}
                </div>
            )}
            {active === "correct" ? (
                <CorrectForm key={view.row_version} view={view} campaignId={campaignId} busy={busy} run={run} onCancel={onCancel} />
            ) : null}
            {active === "change" ? (
                <ChangeForm key={view.row_version} view={view} campaignId={campaignId} busy={busy} run={run} onCancel={onCancel} />
            ) : null}
            {active === "end" ? (
                <EndForm key={view.row_version} view={view} campaignId={campaignId} busy={busy} run={run} onCancel={onCancel} />
            ) : null}
            {modes.length === 0 ? (
                <div className="authoring-actions">
                    <button type="button" className="authoring-button" onClick={onCancel}>
                        Close
                    </button>
                </div>
            ) : null}
        </div>
    )
}

type Run = (command: RelationshipCommand, message: string) => void

interface FormProps {
    view: RelationshipView
    campaignId: string
    busy: boolean
    run: Run
    onCancel: () => void
}

function Buttons({ busy, label, onCancel }: { busy: boolean; label: string; onCancel: () => void }) {
    return (
        <div className="authoring-actions">
            <button type="submit" className="authoring-button authoring-button--primary" disabled={busy}>
                {label}
            </button>
            <button type="button" className="authoring-button" disabled={busy} onClick={onCancel}>
                Cancel
            </button>
        </div>
    )
}

// Fixes a mistake in place. The description is sent back as it is: this form does not touch it.
function CorrectForm({ view, campaignId, busy, run, onCancel }: FormProps) {
    const id = view.relationship_id
    const [office, setOffice] = useState(text(view.typed.role))
    const [rank, setRank] = useState(text(view.typed.rank))
    const [isPublic, setIsPublic] = useState(view.typed.is_public === false ? "no" : "yes")
    const [start, setStart] = useState(view.started_world_time_id ?? "")
    const [problem, setProblem] = useState<string | null>(null)
    return (
        <form
            noValidate
            aria-label="Correct membership"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (start === "") {
                    setProblem("Choose when the membership began.")
                    return
                }
                setProblem(null)
                run(
                    {
                        op: "update",
                        body: {
                            expected_row_version: view.row_version,
                            description: view.description,
                            started_world_time_id: start,
                            role: clean(office),
                            rank: clean(rank),
                            is_public: isPublic === "yes",
                        },
                    },
                    "Membership corrected",
                )
            }}
        >
            <p className="authoring-note">
                Fix something entered wrongly. The earlier values are replaced; to record that the office changed in
                the story, use Change office or rank.
            </p>
            <div className="member-roster__fields">
                <TextField id={`member-office-${id}`} label="Office or role" value={office} onChange={setOffice} />
                <TextField id={`member-rank-${id}`} label="Rank" value={rank} onChange={setRank} />
                <SelectField
                    id={`member-public-${id}`}
                    label="Known to the public"
                    value={isPublic}
                    options={PUBLIC_OPTIONS}
                    onChange={setIsPublic}
                />
                <WorldTimePicker
                    campaignId={campaignId}
                    id={`member-start-${id}`}
                    label="Joined"
                    value={start}
                    onChange={setStart}
                    error={problem}
                />
            </div>
            <Buttons busy={busy} label="Save correction" onCancel={onCancel} />
        </form>
    )
}

// An in-world change: the stint ends and a successor starts at the same time.
function ChangeForm({ view, campaignId, busy, run, onCancel }: FormProps) {
    const id = view.relationship_id
    const [office, setOffice] = useState(text(view.typed.role))
    const [rank, setRank] = useState(text(view.typed.rank))
    const [isPublic, setIsPublic] = useState(view.typed.is_public === false ? "no" : "yes")
    const [when, setWhen] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    const unchanged =
        clean(office) === (clean(text(view.typed.role))) &&
        clean(rank) === (clean(text(view.typed.rank))) &&
        (isPublic === "yes") === (view.typed.is_public !== false)
    return (
        <form
            noValidate
            aria-label="Change office or rank"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (unchanged) {
                    setProblem("Change the office, the rank or who can see it first.")
                    return
                }
                if (when === "") {
                    setProblem("Choose when the change took effect.")
                    return
                }
                setProblem(null)
                run(
                    {
                        op: "change_office",
                        body: {
                            expected_row_version: view.row_version,
                            effective_world_time_id: when,
                            role: clean(office),
                            rank: clean(rank),
                            is_public: isPublic === "yes",
                        },
                    },
                    "Office changed",
                )
            }}
        >
            <p className="authoring-note">
                The current office ends at the time you choose and the new one starts then. The earlier office stays
                in the member&rsquo;s history.
            </p>
            <div className="member-roster__fields">
                <TextField id={`change-office-${id}`} label="New office or role" value={office} onChange={setOffice} />
                <TextField id={`change-rank-${id}`} label="New rank" value={rank} onChange={setRank} />
                <SelectField
                    id={`change-public-${id}`}
                    label="Known to the public"
                    value={isPublic}
                    options={PUBLIC_OPTIONS}
                    onChange={setIsPublic}
                />
                <WorldTimePicker
                    campaignId={campaignId}
                    id={`change-when-${id}`}
                    label="Effective"
                    hint={view.started === null ? undefined : `Must be after ${view.started}.`}
                    value={when}
                    onChange={setWhen}
                    error={problem}
                />
            </div>
            <Buttons busy={busy} label="Record change" onCancel={onCancel} />
        </form>
    )
}

function EndForm({ view, campaignId, busy, run, onCancel }: FormProps) {
    const id = view.relationship_id
    const [when, setWhen] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    return (
        <form
            noValidate
            aria-label="End membership"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (when === "") {
                    setProblem("Choose when the membership ended.")
                    return
                }
                setProblem(null)
                run(
                    { op: "end", body: { expected_row_version: view.row_version, ended_world_time_id: when } },
                    "Membership ended",
                )
            }}
        >
            <p className="authoring-note">
                The member stays in the roster as a past member; nothing is deleted.
            </p>
            <WorldTimePicker
                campaignId={campaignId}
                id={`member-end-${id}`}
                label="Ended"
                hint={view.started === null ? undefined : `Must be after ${view.started}.`}
                value={when}
                onChange={setWhen}
                error={problem}
            />
            <Buttons busy={busy} label="End membership" onCancel={onCancel} />
        </form>
    )
}
