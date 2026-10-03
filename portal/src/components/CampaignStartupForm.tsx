import { useId, useState } from "react"
import type { FormEvent } from "react"
import { Link } from "react-router"
import { useSaveCampaignStartupPreference } from "../hooks/useSaveCampaignStartupPreference"
import type { CampaignStartupMode, SessionBootstrap } from "../types/bootstrap"

interface CampaignStartupFormProps {
    bootstrap: SessionBootstrap
    // Re-checks the session; offered after a refused save so an expired
    // session redirects to sign-in and a stale CSRF token is replaced.
    onCheckSession: () => void
}

interface StartupChoice {
    mode: CampaignStartupMode
    campaignId: string
}

// The "Campaign startup" settings (UI_DESIGN §4.7): resume the last visited
// campaign, or always open one chosen campaign. Only campaigns in the
// current bootstrap are ever offered; the server re-authorizes on save and
// a stored value never grants access. Nothing here shows a raw campaign ID.
export function CampaignStartupForm({
    bootstrap,
    onCheckSession,
}: CampaignStartupFormProps) {
    const { status, save, reset } = useSaveCampaignStartupPreference()
    const modeGroupId = useId()
    const selectId = useId()

    const [baseline, setBaseline] = useState<StartupChoice>(() => ({
        mode: bootstrap.campaign_preferences.startup_mode,
        campaignId: bootstrap.campaign_preferences.preferred_campaign_id ?? "",
    }))
    const [choice, setChoice] = useState<StartupChoice>(baseline)
    // Campaigns the server reported as no longer available during this
    // visit; dropped from the selector without a reload (a reload would
    // unmount this page and lose the explanation).
    const [unavailableIds, setUnavailableIds] = useState<ReadonlySet<string>>(
        () => new Set(),
    )

    const campaigns = bootstrap.campaigns.filter(
        (campaign) => !unavailableIds.has(campaign.campaign_id),
    )

    if (campaigns.length === 0) {
        return (
            <p>
                You do not have access to any campaigns yet.{" "}
                <Link to="/campaigns">Go to campaigns</Link>
            </p>
        )
    }

    const pending = status.kind === "pending"
    const preferredSelected = choice.mode === "preferred_campaign"
    const selectedCampaignAvailable = campaigns.some(
        (campaign) => campaign.campaign_id === choice.campaignId,
    )
    const isValid = !preferredSelected || selectedCampaignAvailable
    const unchanged = preferredSelected
        ? baseline.mode === "preferred_campaign" &&
          baseline.campaignId === choice.campaignId
        : baseline.mode === "resume_last_visited"

    function updateChoice(next: StartupChoice): void {
        setChoice(next)
        if (status.kind !== "idle" && status.kind !== "pending") {
            reset()
        }
    }

    function handleSubmit(event: FormEvent<HTMLFormElement>): void {
        event.preventDefault()
        if (pending || unchanged || !isValid) {
            return
        }
        save(preferredSelected ? choice.campaignId : null)
    }

    // Folded into the shown state rather than an effect: a settled save
    // updates the baseline the first time its result is observed.
    if (status.kind === "success" && !unchanged) {
        setBaseline(
            preferredSelected
                ? { mode: "preferred_campaign", campaignId: choice.campaignId }
                : { mode: "resume_last_visited", campaignId: baseline.campaignId },
        )
    }

    if (status.kind === "unavailable" && selectedCampaignAvailable && preferredSelected) {
        setUnavailableIds(new Set([...unavailableIds, choice.campaignId]))
        setChoice({ mode: "preferred_campaign", campaignId: "" })
    }

    return (
        <form className="campaign-startup-form" onSubmit={handleSubmit} noValidate>
            <fieldset aria-describedby={campaigns.length === 1 ? modeGroupId : undefined}>
                <legend>When I sign in</legend>

                {campaigns.length === 1 && (
                    <p id={modeGroupId}>
                        You have one campaign, so it always opens at sign-in.
                    </p>
                )}

                <label className="campaign-startup-form__option">
                    <input
                        type="radio"
                        name="campaign-startup-mode"
                        checked={!preferredSelected}
                        disabled={pending}
                        onChange={() =>
                            updateChoice({ ...choice, mode: "resume_last_visited" })
                        }
                    />
                    Resume my last visited campaign
                </label>

                <label className="campaign-startup-form__option">
                    <input
                        type="radio"
                        name="campaign-startup-mode"
                        checked={preferredSelected}
                        disabled={pending}
                        onChange={() =>
                            updateChoice({ ...choice, mode: "preferred_campaign" })
                        }
                    />
                    Always open this campaign
                </label>

                <label htmlFor={selectId}>Campaign</label>
                <br />
                <select
                    id={selectId}
                    className="campaign-startup-form__select"
                    value={choice.campaignId}
                    disabled={!preferredSelected || pending}
                    required={preferredSelected}
                    onChange={(event) =>
                        updateChoice({ ...choice, campaignId: event.currentTarget.value })
                    }
                >
                    <option value="" disabled>
                        Choose a campaign
                    </option>
                    {campaigns.map((campaign) => (
                        <option key={campaign.campaign_id} value={campaign.campaign_id}>
                            {campaign.campaign_name}
                        </option>
                    ))}
                </select>
            </fieldset>

            <p>
                <button type="submit" disabled={pending || unchanged || !isValid}>
                    {pending ? "Saving…" : "Save startup preference"}
                </button>
            </p>

            <div role="status" aria-live="polite">
                {pending && "Saving your startup preference…"}
                {status.kind === "success" && "Startup preference saved."}
            </div>

            {status.kind === "unavailable" && (
                <p role="alert" className="campaign-startup-form__error">
                    That campaign is no longer available. Choose another.
                </p>
            )}
            {status.kind === "denied" && (
                <p role="alert" className="campaign-startup-form__error">
                    Your session could not be verified, so nothing was saved.{" "}
                    <button type="button" onClick={onCheckSession}>
                        Check my session
                    </button>
                </p>
            )}
            {status.kind === "error" && (
                <p role="alert" className="campaign-startup-form__error">
                    Your preference could not be saved. Try again.
                </p>
            )}
        </form>
    )
}
