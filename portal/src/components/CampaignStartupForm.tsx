import { useId, useState } from "react"
import type { FormEvent } from "react"
import { Link } from "react-router"
import { useRetryFocus } from "../hooks/useRetryFocus"
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
    const { status, save, reset, outstanding, confirmed, check, checking, checkFailed } =
        useSaveCampaignStartupPreference()
    const modeGroupId = useId()
    const selectId = useId()

    // The authoritative saved value always comes from the shared session
    // bootstrap (re-fetched after every successful save), never from what
    // this form last submitted. `draft` holds only the user's unsaved edits.
    const baseline: StartupChoice = {
        mode: bootstrap.campaign_preferences.startup_mode,
        campaignId: bootstrap.campaign_preferences.preferred_campaign_id ?? "",
    }
    const [draft, setDraft] = useState<StartupChoice | null>(null)
    const choice = draft ?? baseline
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
        setDraft(next)
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

    // Once a save is confirmed (the bootstrap shows it), drop the draft so the form shows the server's own saved
    // value - but only a draft that is that value. A newer choice typed while the confirmation was outstanding stays.
    if ((status.kind === "success" || confirmed) && draft !== null && sameChoice(draft, baseline)) {
        setDraft(null)
    }

    if (status.kind === "unavailable" && selectedCampaignAvailable && preferredSelected) {
        setUnavailableIds(new Set([...unavailableIds, choice.campaignId]))
        setDraft({ mode: "preferred_campaign", campaignId: "" })
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

            <div role="status" aria-live="polite" tabIndex={-1}>
                {pending && "Saving your startup preference…"}
                {status.kind === "success" && "Startup preference saved."}
                {confirmed && "Your earlier startup preference change was confirmed."}
                {checking && "Checking your session…"}
                {checkFailed && "The latest settings still could not be confirmed."}
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
            {outstanding && <UnconfirmedNotice onCheck={check} />}
            {status.kind === "error" && (
                <p role="alert" className="campaign-startup-form__error">
                    Your preference could not be saved. Try again.
                </p>
            )}
        </form>
    )
}

// The checked choice of the saved preference, else another enabled control of the form, else (every control
// locked by a pending save) its status region: where focus goes when
// the notice's button, which the person used, is removed because the session now shows the saved value.
function resolveCheckTarget(section: HTMLElement): HTMLElement | null {
    const enabled = (selector: string) =>
        Array.from(section.querySelectorAll<HTMLElement>(selector)).find(
            (element) => !(element as HTMLInputElement).disabled,
        ) ?? null
    return (
        enabled('input[type="radio"]:checked') ??
        enabled('input[type="radio"]') ??
        enabled("select") ??
        // Every control is locked (another save is pending): the status region, which says what is happening.
        section.querySelector<HTMLElement>('[role="status"][tabindex="-1"]') ??
        enabled("a[href], button")
    )
}

// The confirmed save the session does not show yet. Its own component so that the recovery button's focus
// handoff (useRetryFocus) lives exactly as long as the button.
function UnconfirmedNotice({ onCheck }: { onCheck: () => void }) {
    const { ref, used, left } = useRetryFocus<HTMLButtonElement>(resolveCheckTarget)
    return (
        <p role="alert" className="campaign-startup-form__error">
            Your preference was saved, but the latest settings could not be confirmed.{" "}
            <button
                type="button"
                ref={ref}
                onClick={() => {
                    used()
                    onCheck()
                }}
                onBlur={left}
            >
                Check my session
            </button>
        </p>
    )
}

function sameChoice(a: StartupChoice, b: StartupChoice): boolean {
    return a.mode === "preferred_campaign"
        ? b.mode === "preferred_campaign" && a.campaignId === b.campaignId
        : b.mode === "resume_last_visited"
}
