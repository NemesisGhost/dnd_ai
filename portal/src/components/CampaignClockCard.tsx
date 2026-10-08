import { useState } from "react"
import { advanceClock, clockPath, correctClock } from "../api/campaignClock"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import type { ClockReceipt, ClockState } from "../types/campaignClock"
import { ConfirmDialog } from "./authoring/ConfirmDialog"
import { useAnnounce } from "./authoring/announcer"
import { MutationStatusMessage, StaleWriteNotice } from "./authoring/feedback"
import { WorldTimePicker } from "./authoring/WorldTimePicker"
import "./authoring/authoring.css"

type Mode = "idle" | "advance" | "correct"

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    clock_not_advanced: "The new time must be later than the campaign's current time.",
    clock_not_set: "There is no recorded time to correct yet. Advance the clock first.",
    clock_unchanged: "The clock already shows that time.",
    world_time_id_invalid: "That time is not available. Choose another.",
}

// The campaign's current world time on Campaign Home. Every member sees it;
// people the bootstrap lists `canon.edit` for can advance it or correct it. The
// server decides the outcome (a later time only for an advance; a correction
// cites the event it replaces and leaves it in history) and every write answers
// with a receipt, after which the card refetches the authoritative value.
export function CampaignClockCard({ campaignId }: { campaignId: string }) {
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const clock = useAuthoringResource<ClockState>(clockPath(campaignId))
    const announce = useAnnounce()
    const { reload } = useSession()
    const [mode, setMode] = useState<Mode>("idle")
    const [timeId, setTimeId] = useState("")
    const [confirming, setConfirming] = useState(false)
    const [pickerError, setPickerError] = useState<string | null>(null)

    const state = clock.state.kind === "ready" ? clock.state.data : null

    const mutation = useAuthoringMutation<
        { kind: "advance" | "correct"; timeId: string; version: number; eventId: string | null },
        ClockReceipt
    >({
        scopeKey: `clock:${campaignId}`,
        request: (command, ctx) =>
            command.kind === "advance"
                ? advanceClock(
                      campaignId,
                      { world_time_id: command.timeId, expected_row_version: command.version },
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
            setConfirming(false)
            await clock.refetch()
            announce(done)
        },
    })

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
        })
    }

    return (
        <section className="campaign-time" aria-labelledby="campaign-clock-heading">
            <div className="campaign-time__bar">
                <div className="campaign-time__summary">
                    <h2 id="campaign-clock-heading" className="campaign-time__label">
                        Campaign time
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
                {canEdit && mode === "idle" ? (
                    <div className="authoring-actions campaign-time__actions">
                        <button
                            type="button"
                            className="authoring-button"
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
            {canEdit && mode !== "idle" ? (
                <form
                    className="campaign-time__form"
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
