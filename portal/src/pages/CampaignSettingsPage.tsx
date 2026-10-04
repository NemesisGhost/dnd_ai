import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { archiveCampaign, campaignSettingsPath, updateCampaign } from "../api/campaignSettings"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { TextAreaField, TextField } from "../components/authoring/fields"
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
import type { CampaignMutationResponse, CampaignSettings, UpdateCampaignRequest } from "../types/campaignSettings"
import type { TransitionRequest } from "../types/worldAuthoring"
import {
    DESCRIPTION_MAX,
    ERROR_CODE_MESSAGE,
    NAME_MAX,
    validateDescription,
    validateName,
    validateReason,
} from "../utils/authoringValidation"
import "../components/authoring/authoring.css"

interface Values {
    name: string
    description: string
}

export function CampaignSettingsPage() {
    const { campaignId = "" } = useParams()
    const { state: session } = useSession()
    const campaign =
        session.status === "authenticated"
            ? session.bootstrap.campaigns.find((c) => c.campaign_id === campaignId)
            : undefined
    const allowed = campaign?.capabilities.includes("access.manage") === true
    const { state, refetch } = useAuthoringResource<CampaignSettings>(
        allowed ? campaignSettingsPath(campaignId) : null,
    )
    const headingRef = usePageArrival(!allowed || state.kind !== "loading")
    const [kept, setKept] = useState<Values | null>(null)

    return (
        <main className="app-main">
            <div className="authoring-page">
                <h1 ref={headingRef} tabIndex={-1}>
                    Campaign settings
                </h1>
                {!allowed ? (
                    <p role="alert">You do not have permission to manage this campaign's settings.</p>
                ) : state.kind === "loading" ? (
                    <p role="status">Loading settings…</p>
                ) : state.kind !== "ready" ? (
                    <p role="alert">The campaign settings are not available.</p>
                ) : (
                    <SettingsForm
                        key={state.data.row_version}
                        settings={state.data}
                        refreshing={state.refreshing}
                        kept={kept}
                        onKeep={setKept}
                        refetch={refetch}
                    />
                )}
            </div>
        </main>
    )
}

interface Props {
    settings: CampaignSettings
    refreshing: boolean
    kept: Values | null
    onKeep: (v: Values | null) => void
    refetch: () => Promise<void>
}

function SettingsForm({ settings, refreshing, kept, onKeep, refetch }: Props) {
    const navigate = useNavigate()
    const { refresh, reload } = useSession()
    const [name, setName] = useState(settings.name)
    const [description, setDescription] = useState(settings.description ?? "")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const [archiveOpen, setArchiveOpen] = useState(false)
    const [reason, setReason] = useState("")
    const [reasonError, setReasonError] = useState<string | null>(null)
    const guard = useUnsavedChangesGuard(
        name !== settings.name || description !== (settings.description ?? ""),
    )
    const canUpdate = settings.available_actions.includes("update")
    const canArchive = settings.available_actions.includes("archive")

    const save = useAuthoringMutation<UpdateCampaignRequest, CampaignMutationResponse>({
        scopeKey: `settings:${settings.campaign_id}:${settings.row_version}`,
        request: (body, ctx) => updateCampaign(settings.campaign_id, body, ctx),
        onSuccess: async () => {
            guard.release()
            onKeep(null)
            // The bootstrap carries the campaign's name, so refresh it, then
            // reload the authoritative settings in place.
            await refresh().catch(() => undefined)
            await refetch()
        },
    })

    const archive = useAuthoringMutation<TransitionRequest, CampaignMutationResponse>({
        scopeKey: `archive-campaign:${settings.campaign_id}`,
        request: (body, ctx) => archiveCampaign(settings.campaign_id, body, ctx),
        onSuccess: async () => {
            guard.release()
            await refresh().catch(() => undefined)
            void navigate("/campaigns", { state: { announce: "Campaign archived" } })
        },
    })

    function handleSubmit() {
        const found: FieldError[] = []
        const nameError = validateName(name)
        if (nameError) found.push({ fieldId: "settings-name", message: nameError })
        const descriptionError = validateDescription(description)
        if (descriptionError) found.push({ fieldId: "settings-description", message: descriptionError })
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        save.submit({
            expected_row_version: settings.row_version,
            name: name.trim(),
            description: description.trim() === "" ? null : description.trim(),
        })
    }

    const errorFor = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null
    const saveError = save.status.kind === "error" ? save.status.error : null
    const archiveError = archive.status.kind === "error" ? archive.status.error : null
    const blocked = settings.blocked_actions.filter((b) => b.reason !== "lifecycle_transition_not_allowed")

    return (
        <>
            <dl className="authoring-fact-list">
                <dt>World</dt>
                <dd>{settings.world.name}</dd>
                <dt>Timeline</dt>
                <dd>{settings.timeline.name}</dd>
                <dt>Ruleset</dt>
                <dd>
                    {settings.ruleset_version.ruleset_display_name} — {settings.ruleset_version.version_label}
                </dd>
            </dl>

            {kept !== null ? (
                <section aria-label="Your unsaved changes" className="authoring-message authoring-message--warning">
                    <div>
                        <h2>Your unsaved changes</h2>
                        <dl className="authoring-fact-list">
                            <dt>Name</dt>
                            <dd>{kept.name}</dd>
                            <dt>Description</dt>
                            <dd>{kept.description || "(empty)"}</dd>
                        </dl>
                        <button
                            type="button"
                            className="authoring-button"
                            onClick={() => {
                                setName(kept.name)
                                setDescription(kept.description)
                                onKeep(null)
                            }}
                        >
                            Re-apply my changes
                        </button>
                    </div>
                </section>
            ) : null}

            {canUpdate ? (
                <AuthoringForm label="Campaign settings" onSubmit={handleSubmit}>
                    <ErrorSummary errors={errors} attempt={attempt} />
                    {saveError !== null && saveError.kind === "stale" ? (
                        <StaleWriteNotice
                            loading={refreshing}
                            yourChanges={
                                <dl className="authoring-fact-list">
                                    <dt>Name</dt>
                                    <dd>{name}</dd>
                                    <dt>Description</dt>
                                    <dd>{description || "(empty)"}</dd>
                                </dl>
                            }
                            onLoadLatest={() => {
                                onKeep({ name, description })
                                save.reset()
                                void refetch()
                            }}
                        />
                    ) : saveError !== null ? (
                        <MutationStatusMessage error={saveError} onRetry={save.retry} onCheckSession={reload} />
                    ) : null}
                    <TextField
                        id="settings-name"
                        label="Campaign name"
                        value={name}
                        onChange={setName}
                        required
                        maxLength={NAME_MAX}
                        error={errorFor("settings-name")}
                    />
                    <TextAreaField
                        id="settings-description"
                        label="Description"
                        value={description}
                        onChange={setDescription}
                        maxLength={DESCRIPTION_MAX}
                        error={errorFor("settings-description")}
                    />
                    <FormActions
                        pending={save.status.kind === "pending"}
                        onCancel={() => void navigate(`/app/${settings.campaign_id}/home`)}
                    />
                </AuthoringForm>
            ) : (
                <p role="alert">These settings cannot be changed right now.</p>
            )}

            {blocked.length > 0 ? (
                <ul className="authoring-note" aria-label="Unavailable actions">
                    {blocked.map((b) => (
                        <li key={b.action}>
                            {b.action} unavailable: {ERROR_CODE_MESSAGE[b.reason] ?? "not allowed right now."}
                        </li>
                    ))}
                </ul>
            ) : null}

            {canArchive ? (
                <section className="authoring-section" aria-labelledby="archive-heading">
                    <h2 id="archive-heading">Archive campaign</h2>
                    <p className="authoring-note">
                        Archiving takes the campaign out of service for everyone. Members, roles, and
                        invitations are kept, and you can reactivate it later from the Campaigns page.
                    </p>
                    <button
                        type="button"
                        className="authoring-button"
                        onClick={() => {
                            archive.reset()
                            setReason("")
                            setReasonError(null)
                            setArchiveOpen(true)
                        }}
                    >
                        Archive campaign
                    </button>
                </section>
            ) : null}

            <ConfirmDialog
                open={archiveOpen}
                title="Archive this campaign?"
                description="Members will no longer be able to open it until it is reactivated."
                confirmLabel="Archive campaign"
                onConfirm={() => {
                    const problem = validateReason(reason, false)
                    setReasonError(problem)
                    if (problem) return
                    archive.submit({
                        expected_row_version: settings.row_version,
                        reason: reason.trim() === "" ? null : reason.trim(),
                    })
                }}
                onCancel={() => setArchiveOpen(false)}
                pending={archive.status.kind === "pending"}
                reason={{
                    label: "Reason (optional)",
                    required: false,
                    value: reason,
                    onChange: setReason,
                    error: reasonError,
                }}
                error={
                    archiveError === null ? null : archiveError.kind === "stale" ? (
                        <div role="alert" className="authoring-message authoring-message--warning">
                            <p>Someone else changed this campaign. Reload to see the latest version.</p>
                        </div>
                    ) : (
                        <MutationStatusMessage error={archiveError} onRetry={archive.retry} onCheckSession={reload} />
                    )
                }
            />

            <ConfirmDialog
                open={guard.blocked}
                title="Discard unsaved changes?"
                description="You have edits to these settings that have not been saved."
                confirmLabel="Discard changes"
                onConfirm={guard.discard}
                onCancel={guard.stay}
                cancelLabel="Keep editing"
            />
            <p>
                <Link to={`/app/${settings.campaign_id}/home`}>Back to Campaign Home</Link>
            </p>
        </>
    )
}
