import { useEffect, useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router"
import { createCampaign } from "../api/campaignSettings"
import { worldPath, worldsListPath } from "../api/worlds"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { RadioGroupField, SelectField, TextAreaField, TextField } from "../components/authoring/fields"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
} from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import type { CreateCampaignRequest, CreateCampaignResponse } from "../types/campaignSettings"
import type { WorldDetail, WorldListResponse } from "../types/worldAuthoring"
import { DESCRIPTION_MAX, NAME_MAX, validateDescription, validateName } from "../utils/authoringValidation"
import { canCreateWorlds } from "../utils/worldAccess"
import "../components/authoring/authoring.css"

// The campaign setup wizard. Step state lives in the URL (`?worldId=&timelineId=`),
// so Back/Forward and a refresh resume it, and every committed step (a world
// created mid-wizard) is a real, visible, owned record — cancelling leaves no
// hidden half-object. The final step creates the campaign and navigates into it
// only once the refreshed bootstrap actually contains it.
export function CampaignSetupPage() {
    const [params] = useSearchParams()
    const worldId = params.get("worldId")
    const timelineId = params.get("timelineId")
    const step = worldId === null ? 1 : timelineId === null ? 2 : 3
    const headingRef = usePageArrival(true)

    return (
        <main className="app-main">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to="/campaigns">Campaigns</Link>
                </p>
                <h1 ref={headingRef} tabIndex={-1}>
                    Create a campaign
                </h1>
                <ol className="authoring-step-nav" aria-label="Setup steps">
                    {["World", "Timeline", "Details"].map((label, index) => (
                        <li key={label} aria-current={step === index + 1 ? "step" : undefined}>
                            {index + 1}. {label}
                        </li>
                    ))}
                </ol>
                {step === 1 ? (
                    <ChooseWorld />
                ) : step === 2 ? (
                    <ChooseTimeline worldId={worldId!} />
                ) : (
                    <CampaignDetails worldId={worldId!} timelineId={timelineId!} />
                )}
            </div>
        </main>
    )
}

function ChooseWorld() {
    const [, setParams] = useSearchParams()
    const { state: session } = useSession()
    // Offered only with the server-computed `world.create`; never a link that
    // would fail after navigation.
    const canCreate = session.status === "authenticated" && canCreateWorlds(session.bootstrap)
    const { state } = useAuthoringResource<WorldListResponse>(`${worldsListPath("active")}&limit=100`)
    const [choice, setChoice] = useState("")

    if (state.kind === "loading") return <p role="status">Loading your worlds…</p>
    if (state.kind !== "ready") {
        return <p role="alert">Your worlds could not be loaded. Try reloading the page.</p>
    }
    const eligible = state.data.items.filter((w) => w.capabilities.includes("campaign.create"))

    return (
        <>
            <p className="authoring-page__lead">Choose the world this campaign is played in.</p>
            {eligible.length === 0 ? (
                <p>You do not own a world you can start a campaign in yet.</p>
            ) : (
                <RadioGroupField
                    legend="World"
                    value={choice}
                    onChange={setChoice}
                    options={eligible.map((w) => ({ value: w.world_id, label: w.name }))}
                />
            )}
            <div className="authoring-actions">
                <button
                    type="button"
                    className="authoring-button authoring-button--primary"
                    disabled={choice === ""}
                    onClick={() => setParams({ worldId: choice })}
                >
                    Continue
                </button>
                {canCreate ? (
                    <Link className="authoring-button" to="/worlds/new?returnTo=/campaigns/new">
                        Create a new world
                    </Link>
                ) : null}
                <Link className="authoring-button" to="/campaigns">
                    Cancel
                </Link>
            </div>
        </>
    )
}

function ChooseTimeline({ worldId }: { worldId: string }) {
    const [, setParams] = useSearchParams()
    const { state } = useAuthoringResource<WorldDetail>(worldPath(worldId))
    const [choice, setChoice] = useState<string | null>(null)

    if (state.kind === "loading") return <p role="status">Loading world…</p>
    if (state.kind !== "ready" || !state.data.available_actions.includes("create_campaign")) {
        return (
            <p role="alert">
                This world is not available for new campaigns. <Link to="/campaigns/new">Choose another world</Link>
            </p>
        )
    }
    const active = state.data.timelines.filter((t) => t.lifecycle_status === "active")
    const selected = choice ?? active.find((t) => t.is_primary)?.timeline_id ?? active[0]?.timeline_id ?? ""

    return (
        <>
            <p className="authoring-page__lead">
                Choose the timeline in {state.data.name} this campaign is played on.
            </p>
            {active.length === 0 ? (
                <p role="alert">This world has no active timeline.</p>
            ) : (
                <RadioGroupField
                    legend="Timeline"
                    value={selected}
                    onChange={setChoice}
                    options={active.map((t) => ({
                        value: t.timeline_id,
                        label: t.is_primary ? `${t.name} (primary)` : t.name,
                    }))}
                />
            )}
            <div className="authoring-actions">
                <button
                    type="button"
                    className="authoring-button authoring-button--primary"
                    disabled={selected === ""}
                    onClick={() => setParams({ worldId, timelineId: selected })}
                >
                    Continue
                </button>
                <Link className="authoring-button" to="/campaigns/new">
                    Back
                </Link>
            </div>
        </>
    )
}

function CampaignDetails({ worldId, timelineId }: { worldId: string; timelineId: string }) {
    const { state } = useAuthoringResource<WorldDetail>(worldPath(worldId))
    if (state.kind === "loading") return <p role="status">Loading world…</p>
    if (
        state.kind !== "ready" ||
        !state.data.available_actions.includes("create_campaign") ||
        !state.data.timelines.some((t) => t.timeline_id === timelineId && t.lifecycle_status === "active")
    ) {
        return (
            <p role="alert">
                That world or timeline is not available for new campaigns.{" "}
                <Link to="/campaigns/new">Start over</Link>
            </p>
        )
    }
    return <DetailsForm world={state.data} worldId={worldId} timelineId={timelineId} />
}

function DetailsForm({
    world,
    worldId,
    timelineId,
}: {
    world: WorldDetail
    worldId: string
    timelineId: string
}) {
    const navigate = useNavigate()
    const { state: session, refresh, reload } = useSession()
    const versions = world.allowed_rulesets.flatMap((r) =>
        r.current_version
            ? [
                  {
                      value: r.current_version.ruleset_version_id,
                      label: `${r.display_name} — ${r.current_version.version_label}`,
                  },
              ]
            : [],
    )
    const [name, setName] = useState("")
    const [description, setDescription] = useState("")
    const [versionState, setVersionState] = useState<string | null>(null)
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const [createdId, setCreatedId] = useState<string | null>(null)
    const [refreshFailed, setRefreshFailed] = useState(false)
    const version = versionState ?? (versions.length === 1 ? versions[0]!.value : "")
    const guard = useUnsavedChangesGuard(createdId === null && (name !== "" || description !== ""))

    const mutation = useAuthoringMutation<CreateCampaignRequest, CreateCampaignResponse>({
        scopeKey: `create-campaign:${timelineId}`,
        request: (body, ctx) => createCampaign(body, ctx),
        onSuccess: async (result) => {
            guard.release()
            setCreatedId(result.campaign_id)
            try {
                await refresh()
            } catch {
                setRefreshFailed(true)
            }
        },
    })

    // Navigate only once the authoritative bootstrap lists the new campaign;
    // never to a guessed route, which the campaign boundary would reject.
    const listed =
        createdId !== null &&
        session.status === "authenticated" &&
        session.bootstrap.campaigns.some((c) => c.campaign_id === createdId)
    useEffect(() => {
        if (listed && createdId !== null) {
            void navigate(`/app/${createdId}/home`, { state: { announce: "Campaign created" } })
        }
    }, [listed, createdId, navigate])

    const error = mutation.status.kind === "error" ? mutation.status.error : null

    function handleSubmit() {
        const found: FieldError[] = []
        const nameError = validateName(name)
        if (nameError) found.push({ fieldId: "campaign-name", message: nameError })
        const descriptionError = validateDescription(description)
        if (descriptionError) found.push({ fieldId: "campaign-description", message: descriptionError })
        if (version === "") found.push({ fieldId: "campaign-ruleset", message: "Choose a ruleset version." })
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        mutation.submit({
            timeline_id: timelineId,
            ruleset_version_id: version,
            name: name.trim(),
            description: description.trim() === "" ? null : description.trim(),
        })
    }

    if (createdId !== null) {
        return refreshFailed || (mutation.status.kind === "success" && !listed) ? (
            <div role="alert" className="authoring-message authoring-message--warning">
                <div>
                    <p>Campaign created. We could not confirm it with the server yet.</p>
                    <button
                        type="button"
                        className="authoring-button authoring-button--primary"
                        onClick={() => {
                            setRefreshFailed(false)
                            refresh().catch(() => setRefreshFailed(true))
                        }}
                    >
                        Open the campaign
                    </button>
                </div>
            </div>
        ) : (
            <p role="status">Campaign created. Opening it…</p>
        )
    }

    const errorFor = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null

    return (
        <>
            <p className="authoring-page__lead">
                Set up {world.name}'s new campaign. You become its owner and can invite players
                afterwards.
            </p>
            <AuthoringForm label="Create campaign" onSubmit={handleSubmit}>
                <ErrorSummary errors={errors} attempt={attempt} />
                {error !== null ? (
                    <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                ) : null}
                <TextField
                    id="campaign-name"
                    label="Campaign name"
                    value={name}
                    onChange={setName}
                    required
                    maxLength={NAME_MAX}
                    error={errorFor("campaign-name")}
                />
                <TextAreaField
                    id="campaign-description"
                    label="Description"
                    value={description}
                    onChange={setDescription}
                    maxLength={DESCRIPTION_MAX}
                    error={errorFor("campaign-description")}
                />
                <SelectField
                    id="campaign-ruleset"
                    label="Ruleset version"
                    hint="Fixed for the life of the campaign."
                    value={version}
                    placeholder="Choose a ruleset version"
                    required
                    options={versions}
                    onChange={setVersionState}
                    error={errorFor("campaign-ruleset")}
                />
                <FormActions
                    pending={mutation.status.kind === "pending"}
                    saveLabel="Create campaign"
                    pendingLabel="Creating…"
                    onCancel={() => void navigate("/campaigns")}
                />
            </AuthoringForm>
            <p>
                <Link to={`/campaigns/new?worldId=${encodeURIComponent(worldId)}`}>Back to timeline choice</Link>
            </p>
            <ConfirmDialog
                open={guard.blocked}
                title="Discard unsaved changes?"
                description="You have entered campaign details that have not been saved."
                confirmLabel="Discard changes"
                onConfirm={guard.discard}
                onCancel={guard.stay}
                cancelLabel="Keep editing"
            />
        </>
    )
}
