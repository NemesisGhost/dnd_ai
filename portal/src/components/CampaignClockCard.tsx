import { useState } from "react"
import { advanceClock, clockCauseChoicesPath, clockPath, correctClock } from "../api/campaignClock"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useConfirmedRefresh } from "../hooks/useConfirmedRefresh"
import { useKept } from "../hooks/useKeptResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import {
    CLOCK_EXPLANATION_MAX_LENGTH,
    type ClockCauseChoices,
    type ClockReceipt,
    type ClockState,
} from "../types/campaignClock"
import { ConfirmDialog } from "./authoring/ConfirmDialog"
import { useAnnounce } from "./authoring/announcer"
import { MutationStatusMessage, StaleWriteNotice } from "./authoring/feedback"
import { SelectField, TextAreaField } from "./authoring/fields"
import { WorldTimePicker } from "./authoring/WorldTimePicker"
import { StaleReadNotice } from "./StaleReadNotice"
import "./authoring/authoring.css"

type Mode = "idle" | "advance" | "correct"

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    clock_not_advanced: "The new time must be later than the campaign's current time.",
    clock_not_set: "There is no recorded time to correct yet. Advance the clock first.",
    clock_unchanged: "The clock already shows that time.",
    world_time_id_invalid: "That time is not available. Choose another.",
    clock_cause_invalid: "That event can no longer be recorded as the cause. Choose another or none.",
    clock_cause_after_target:
        "That event takes effect after the new time, so it cannot have caused this advance.",
}

// The campaign's current world time on Campaign Home. Every member sees it;
// people the bootstrap lists `canon.edit` for can advance it or correct it. The
// server decides the outcome (a later time only for an advance; a correction
// cites the event it replaces and leaves it in history) and every write answers
// with a receipt, after which the card refetches the authoritative value.
//
// `variant="compact"` is the one-line bar on the Run Session page, labelled as in-world time.
// With `actionsVisible={false}` Advance/Correct are not offered, but an open form stays mounted
// (hidden), so a half-entered time survives until the actions come back.
export function CampaignClockCard({
    campaignId,
    variant = "card",
    actionsVisible = true,
}: {
    campaignId: string
    variant?: "card" | "compact"
    actionsVisible?: boolean
}) {
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const clockUrl = clockPath(campaignId)
    const clock = useAuthoringResource<ClockState>(clockUrl)
    // The last clock that loaded stays through a failed re-read (after an advance or a correction), so
    // the card that reports the save does not disappear; a denied or missing answer drops it.
    const kept = useKept(clock.state, clockUrl)
    const stale = clock.state.kind === "error" && kept !== null
    const announce = useAnnounce()
    const { reload } = useSession()
    const [mode, setMode] = useState<Mode>("idle")
    const [timeId, setTimeId] = useState("")
    const [confirming, setConfirming] = useState(false)
    const [pickerError, setPickerError] = useState<string | null>(null)
    const [causeId, setCauseId] = useState("")
    const [explanation, setExplanation] = useState("")

    const state = kept

    // The optional cause picker reads only while the advance form is open, for the chosen time
    // (the server offers only events that take effect by then). A failed read never blocks the
    // advance: the picker is replaced by a note and the advance stays manual.
    const causes = useAuthoringResource<ClockCauseChoices>(
        canEdit && mode === "advance" ? clockCauseChoicesPath(campaignId, timeId) : null,
    )
    const choices = causes.state.kind === "ready" ? causes.state.data.choices : null
    const chosenCause = choices?.find((c) => c.event_id === causeId) ?? null
    // A cause that is not among the offered ones (the time changed under it) is not submitted.
    const droppedCause = causeId !== "" && choices !== null && chosenCause === null

    // What the last confirmed write said, for the notice if the clock could not be read back.
    const [saved, setSaved] = useState<string | null>(null)
    const mutation = useAuthoringMutation<
        {
            kind: "advance" | "correct"
            timeId: string
            version: number
            eventId: string | null
            causeEventId: string
            explanation: string
        },
        ClockReceipt
    >({
        scopeKey: `clock:${campaignId}`,
        request: (command, ctx) =>
            command.kind === "advance"
                ? advanceClock(
                      campaignId,
                      {
                          world_time_id: command.timeId,
                          expected_row_version: command.version,
                          // Left out entirely for a plain manual advance.
                          ...(command.causeEventId !== "" ? { cause_event_id: command.causeEventId } : {}),
                          ...(command.explanation.trim() !== "" ? { explanation: command.explanation.trim() } : {}),
                      },
                      ctx,
                  )
                : correctClock(
                      campaignId,
                      {
                          world_time_id: command.timeId,
                          expected_row_version: command.version,
                          corrects_event_id: command.eventId ?? "",
                      },
                      ctx,
                  ),
        onSuccess: async () => {
            const done = mode === "correct" ? "Clock corrected" : "Clock advanced"
            setMode("idle")
            setTimeId("")
            setCauseId("")
            setExplanation("")
            setConfirming(false)
            setSaved(done)
            const outcome = await clock.refetch()
            if (outcome === "ok") announce(done)
            return outcome
        },
    })
    const refreshed = useConfirmedRefresh({
        status: mutation.status,
        reset: mutation.reset,
        what: "campaign time",
        message: saved,
        read: clock.refetch,
        pageStale: stale,
    })
    // Advance and Correct name the clock's version and its last event: the card shows the earlier
    // ones until it is read again, so neither is offered from it.
    const writesHeld = refreshed.held || stale

    if (clock.state.kind === "loading") {
        return <p role="status">Loading the campaign clock…</p>
    }
    if (state === null) {
        return null
    }

    const pending = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const code = error?.code ?? null
    const message = code !== null ? (CODE_MESSAGE[code] ?? null) : null

    function submit(kind: "advance" | "correct") {
        if (writesHeld) return
        if (timeId === "") {
            setPickerError("Choose a time.")
            return
        }
        setPickerError(null)
        mutation.submit({
            kind,
            timeId,
            version: state!.row_version,
            eventId: state!.last_event_id,
            causeEventId: kind === "advance" && !droppedCause ? causeId : "",
            explanation: kind === "advance" ? explanation : "",
        })
    }

    return (
        <section
            className={variant === "compact" ? "campaign-time campaign-time--compact" : "campaign-time"}
            aria-labelledby="campaign-clock-heading"
        >
            <div className="campaign-time__bar">
                <div className="campaign-time__summary">
                    <h2 id="campaign-clock-heading" className="campaign-time__label">
                        {variant === "compact" ? "Campaign time (in-world)" : "Campaign time"}
                    </h2>
                    <p className="campaign-time__now">
                        {state.current === null
                            ? "No time has been recorded for this campaign yet."
                            : `Now: ${state.current.display}`}
                        {state.inherited && state.current !== null
                            ? " (carried over from the original timeline)"
                            : ""}
                    </p>
                </div>
                {canEdit && actionsVisible && mode === "idle" ? (
                    <div className="authoring-actions campaign-time__actions">
                        <button
                            type="button"
                            className="authoring-button"
                            disabled={writesHeld}
                            onClick={() => {
                                mutation.reset()
                                setMode("advance")
                            }}
                        >
                            Advance time
                        </button>
                        {state.current !== null &&
                        !state.inherited &&
                        state.last_event_id !== null ? (
                            <button
                                type="button"
                                className="authoring-button"
                                disabled={writesHeld}
                                onClick={() => {
                                    mutation.reset()
                                    setMode("correct")
                                }}
                            >
                                Correct time
                            </button>
                        ) : null}
                    </div>
                ) : null}
            </div>
            {stale ? <StaleReadNotice what="campaign time" onRetry={() => void clock.refetch()} /> : null}
            {refreshed.notice}
            {canEdit && mode !== "idle" ? (
                <form
                    className="campaign-time__form"
                    hidden={!actionsVisible}
                    aria-label={mode === "advance" ? "Advance time" : "Correct time"}
                    noValidate
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (mode === "advance") {
                            submit("advance")
                        } else if (timeId === "") {
                            setPickerError("Choose a time.")
                        } else {
                            setPickerError(null)
                            setConfirming(true)
                        }
                    }}
                >
                    {mutation.status.kind === "error" && error?.kind === "stale" ? (
                        <StaleWriteNotice
                            onLoadLatest={() => {
                                mutation.reset()
                                void clock.refetch()
                            }}
                        />
                    ) : message !== null ? (
                        <p role="alert">{message}</p>
                    ) : error !== null ? (
                        <MutationStatusMessage
                            error={error}
                            onRetry={mutation.retry}
                            onCheckSession={reload}
                        />
                    ) : null}
                    <WorldTimePicker
                        campaignId={campaignId}
                        id="clock-time"
                        label={mode === "advance" ? "Advance to" : "Correct to"}
                        value={timeId}
                        onChange={(value) => {
                            setTimeId(value)
                            setPickerError(null)
                        }}
                        required
                        error={pickerError}
                    />
                    {mode === "advance" ? (
                        <fieldset className="campaign-time__optional" aria-describedby="clock-optional-hint">
                            <legend>Optional details</legend>
                            <p id="clock-optional-hint" className="authoring-note">
                                Leave both empty for a manual advance.
                            </p>
                            {causes.state.kind === "loading" ? (
                                <p role="status">Loading events that could be the cause…</p>
                            ) : choices === null ? (
                                <p role="status">
                                    Events that could be the cause could not be loaded. You can still advance the
                                    clock manually.
                                </p>
                            ) : choices.length === 0 ? (
                                <p>
                                    No recorded events could have caused an advance to this time, so it will be a
                                    manual advance.
                                </p>
                            ) : (
                                <SelectField
                                    id="clock-cause"
                                    label="Cause"
                                    value={droppedCause ? "" : causeId}
                                    placeholder="No cause (manual advance)"
                                    hint={
                                        droppedCause
                                            ? "The event you chose takes effect after this time, so it was cleared."
                                            : "An event already recorded in this campaign. Members see it only if they may open that event."
                                    }
                                    options={choices.map((c) => ({
                                        value: c.event_id,
                                        label: `${c.name} (${c.in_world_time})`,
                                    }))}
                                    onChange={setCauseId}
                                />
                            )}
                            <TextAreaField
                                id="clock-explanation"
                                label="Explanation for members"
                                value={explanation}
                                onChange={setExplanation}
                                maxLength={CLOCK_EXPLANATION_MAX_LENGTH}
                                rows={3}
                                hint="Shown to campaign members who can view this event, so write it for players. Do not include GM-only notes."
                            />
                        </fieldset>
                    ) : null}
                    <div className="authoring-actions">
                        <button
                            type="submit"
                            className="authoring-button authoring-button--primary"
                            disabled={pending}
                            aria-busy={pending}
                        >
                            {pending
                                ? "Saving…"
                                : mode === "advance"
                                  ? "Advance time"
                                  : "Correct time"}
                        </button>
                        <button
                            type="button"
                            className="authoring-button"
                            disabled={pending}
                            onClick={() => {
                                setMode("idle")
                                setTimeId("")
                                setCauseId("")
                                setExplanation("")
                                setPickerError(null)
                                mutation.reset()
                            }}
                        >
                            Cancel
                        </button>
                    </div>
                </form>
            ) : null}
            <ConfirmDialog
                open={confirming}
                title="Correct the campaign time?"
                description="The clock will show the time you chose. The earlier advance stays in the campaign's history, and this correction is recorded against it."
                confirmLabel="Correct time"
                cancelLabel="Keep the current time"
                pending={pending}
                error={confirming && message !== null ? <p role="alert">{message}</p> : null}
                onConfirm={() => submit("correct")}
                onCancel={() => {
                    setConfirming(false)
                    mutation.reset()
                }}
            />
        </section>
    )
}
