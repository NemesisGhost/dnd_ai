import { useState } from "react"
import { useNavigate } from "react-router"
import { entityLifecyclePath, runEntityAction } from "../api/entityLifecycle"
import { useSession } from "../context/SessionContext"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type {
    EntityLifecycleView,
    EntityTransitionBody,
    EntityTransitionResponse,
    ReplacementCandidate,
    SupersedeBody,
} from "../types/entityLifecycle"
import { validateReason } from "../utils/authoringValidation"
import { describeBlockedReason } from "../utils/blockedReason"
import { useAnnounce } from "./authoring/announcer"
import { ConfirmDialog } from "./authoring/ConfirmDialog"
import { LifecycleBadge, MutationStatusMessage } from "./authoring/feedback"
import { EntitySourcesSection } from "./EntitySourcesSection"
import { SupersedeEntityDialog } from "./SupersedeEntityDialog"
import "./authoring/authoring.css"

// The action travels with the body so a submit never depends on state that has
// not rendered yet (the immediate path sets the action and submits together).
interface Submission {
    action: string
    body: EntityTransitionBody | SupersedeBody
}

interface ActionSpec {
    label: string
    title: string
    description: string
    done: string
    // "none": no reason field; "optional" / "required": shown in the dialog.
    reason: "none" | "optional" | "required"
    // Submitting for review is non-destructive and skips the confirmation.
    immediate?: boolean
}

const ACTIONS: Readonly<Record<string, ActionSpec>> = {
    submit_for_review: {
        label: "Submit for review",
        title: "Submit for review?",
        description: "A reviewer can then approve or reject it.",
        done: "Submitted for review",
        reason: "none",
        immediate: true,
    },
    return_to_draft: {
        label: "Return to draft",
        title: "Return to draft?",
        description: "It leaves review and can be edited again.",
        done: "Returned to draft",
        reason: "optional",
    },
    approve: {
        label: "Approve",
        title: "Approve this record?",
        description: "It is approved but not yet part of canon until published.",
        done: "Approved",
        reason: "none",
    },
    reject: {
        label: "Reject",
        title: "Reject this record?",
        description: "It is kept as rejected and can be returned to draft.",
        done: "Rejected",
        reason: "optional",
    },
    publish: {
        label: "Publish as canon",
        title: "Publish as canon?",
        description: "Players will be able to see it wherever their access allows.",
        done: "Published as canon",
        reason: "none",
    },
    archive: {
        label: "Archive",
        title: "Archive this record?",
        description: "It is hidden from players and lists by default, and kept as history.",
        done: "Archived",
        reason: "optional",
    },
    restore: {
        label: "Restore",
        title: "Restore this record?",
        description: "It becomes active again. Say why it is being restored.",
        done: "Restored",
        reason: "required",
    },
    delete_draft: {
        label: "Delete draft",
        title: "Delete this draft?",
        description: "The draft is permanently removed. This cannot be undone.",
        done: "Draft deleted",
        reason: "required",
    },
}

const ORDER = [
    "submit_for_review",
    "return_to_draft",
    "approve",
    "reject",
    "publish",
    "supersede",
    "archive",
    "restore",
    "delete_draft",
]

const STATUS_LABEL: Readonly<Record<string, string>> = {
    draft: "Draft",
    proposed: "In review",
    approved: "Approved",
    canon: "Canon",
    superseded: "Superseded",
    rejected: "Rejected",
}

function actionLabel(code: string): string {
    return code === "supersede" ? "Supersede" : (ACTIONS[code]?.label ?? code)
}

interface EntityLifecyclePanelProps {
    campaignId: string
    entityId: string
    // The World category, so the sources section can link to the provenance page.
    category?: string
    // Called after a successful transition so the page above can refetch.
    onChanged?: () => void
}

// Server-driven lifecycle controls for one world record. It renders only for a
// campaign member whose bootstrap lists `canon.edit`, and only the actions the
// server's `available_actions` reports; blocked actions are explained, not
// disabled in place. Players (no capability) trigger no request at all.
export function EntityLifecyclePanel({ campaignId, entityId, category, onChanged }: EntityLifecyclePanelProps) {
    // Players (and any render without a session) mount nothing and send no
    // request; the loading hooks live in the inner component.
    if (!useCampaignCapability(campaignId, "canon.edit")) {
        return null
    }
    return <LoadedPanel campaignId={campaignId} entityId={entityId} category={category} onChanged={onChanged} />
}

function LoadedPanel({ campaignId, entityId, category, onChanged }: EntityLifecyclePanelProps) {
    const { state, refetch } = useAuthoringResource<EntityLifecycleView>(
        entityLifecyclePath(campaignId, entityId),
    )
    if (state.kind !== "ready" || !state.data.lifecycle_managed) {
        return null
    }
    return (
        <>
            <Panel
                key={state.data.row_version}
                campaignId={campaignId}
                view={state.data}
                refetch={refetch}
                onChanged={onChanged}
            />
            <EntitySourcesSection campaignId={campaignId} entityId={entityId} category={category} />
        </>
    )
}

interface PanelProps {
    campaignId: string
    view: EntityLifecycleView
    refetch: () => Promise<void>
    onChanged?: () => void
}

function Panel({ campaignId, view, refetch, onChanged }: PanelProps) {
    const navigate = useNavigate()
    const announce = useAnnounce()
    const { reload } = useSession()
    const [action, setAction] = useState<string | null>(null)
    const [reason, setReason] = useState("")
    const [reasonError, setReasonError] = useState<string | null>(null)
    const available = new Set(view.available_actions)
    const spec = action === null ? undefined : ACTIONS[action]

    const mutation = useAuthoringMutation<Submission, EntityTransitionResponse>({
        scopeKey: `entity:${view.entity_id}:${view.row_version}`,
        request: (submission, ctx) =>
            runEntityAction(campaignId, view.entity_id, submission.action, submission.body, ctx),
        onSuccess: async (result) => {
            const message = action === "supersede" ? "Record superseded" : (spec?.done ?? "Updated")
            setAction(null)
            setReason("")
            if (result.deleted === true) {
                void navigate(`/app/${encodeURIComponent(campaignId)}/world`, {
                    state: { announce: message },
                })
                return
            }
            await refetch()
            onChanged?.()
            announce(message)
        },
    })

    function open(next: string) {
        mutation.reset()
        setReason("")
        setReasonError(null)
        setAction(next)
        if (ACTIONS[next]?.immediate === true) {
            mutation.submit({ action: next, body: { expected_row_version: view.row_version } })
        }
    }

    function confirm() {
        if (spec === undefined) return
        const problem = validateReason(reason, spec.reason === "required")
        setReasonError(problem)
        if (problem) return
        mutation.submit({
            action: action ?? "",
            body: {
                expected_row_version: view.row_version,
                ...(spec.reason === "none" ? {} : { reason: reason.trim() === "" ? null : reason.trim() }),
            },
        })
    }

    function confirmSupersede(replacement: ReplacementCandidate) {
        mutation.submit({
            action: "supersede",
            body: {
                expected_row_version: view.row_version,
                replacement_entity_id: replacement.entity_id,
                replacement_expected_row_version: replacement.row_version,
            },
        })
    }

    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const errorNode =
        error === null ? null : error.kind === "stale" ? (
            <div role="alert" className="authoring-message authoring-message--warning">
                <div>
                    <p>Someone else changed this record. Reload it to see the latest version.</p>
                    <button
                        type="button"
                        className="authoring-button"
                        onClick={() => {
                            mutation.reset()
                            setAction(null)
                            void refetch().then(() => onChanged?.())
                        }}
                    >
                        Load latest version
                    </button>
                </div>
            </div>
        ) : (
            <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
        )
    const pending = mutation.status.kind === "pending"
    const visible = ORDER.filter((code) => available.has(code))
    const blocked = view.blocked_actions.filter((b) => b.action !== "all")
    const dialogAction = action !== null && action !== "supersede" && spec !== undefined && spec.immediate !== true

    return (
        <section className="authoring-section" aria-labelledby="entity-lifecycle-heading">
            <h2 id="entity-lifecycle-heading">Lifecycle</h2>
            <p>
                <LifecycleBadge status={view.canon_status} />{" "}
                {view.lifecycle_status === "archived" ? <LifecycleBadge status="archived" /> : null}
                <span className="authoring-field__hint"> {STATUS_LABEL[view.canon_status] ?? view.canon_status}</span>
            </p>
            {view.superseded_by !== null ? <p>Replaced by {view.superseded_by.canonical_name}.</p> : null}
            {spec?.immediate === true ? errorNode : null}
            {visible.length > 0 ? (
                <div className="authoring-actions">
                    {visible.map((code) => (
                        <button
                            key={code}
                            type="button"
                            className="authoring-button"
                            disabled={pending}
                            onClick={() => open(code)}
                        >
                            {code === "supersede" ? "Supersede…" : actionLabel(code)}
                        </button>
                    ))}
                </div>
            ) : (
                <p className="authoring-note">No lifecycle actions are available right now.</p>
            )}
            {blocked.length > 0 ? (
                <ul className="authoring-note" aria-label="Unavailable lifecycle actions">
                    {blocked.map((b) => (
                        <li key={b.action}>
                            {actionLabel(b.action)} unavailable:{" "}
                            {describeBlockedReason(b.reason)}
                        </li>
                    ))}
                </ul>
            ) : null}

            {dialogAction ? (
                <ConfirmDialog
                    open
                    title={spec.title}
                    description={spec.description}
                    confirmLabel={spec.label}
                    onConfirm={confirm}
                    onCancel={() => setAction(null)}
                    pending={pending}
                    reason={
                        spec.reason === "none"
                            ? undefined
                            : {
                                  label: spec.reason === "required" ? "Reason" : "Reason (optional)",
                                  required: spec.reason === "required",
                                  value: reason,
                                  onChange: setReason,
                                  error: reasonError,
                              }
                    }
                    error={errorNode}
                />
            ) : null}
            <SupersedeEntityDialog
                open={action === "supersede"}
                campaignId={campaignId}
                entityId={view.entity_id}
                entityName={view.canonical_name}
                onConfirm={confirmSupersede}
                onCancel={() => setAction(null)}
                pending={pending}
                error={errorNode}
            />
        </section>
    )
}
