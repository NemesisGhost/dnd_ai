import { useState } from "react"
import { campaignCalendarsPath, worldTimesPath } from "../../api/worldTime"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import { useConfirmedRefresh, useUnreadWrite } from "../../hooks/useConfirmedRefresh"
import { useKept } from "../../hooks/useKeptResource"
import type { CalendarListResponse, WorldTimePage, WorldTimeReceipt } from "../../types/worldTime"
import { SelectField } from "./fields"
import { WorldTimeForm } from "./WorldTimeForm"
import "./authoring.css"

interface WorldTimePickerProps {
    campaignId: string
    id: string
    label: string
    // The chosen world-time id, or "" for none.
    value: string
    onChange: (worldTimeId: string) => void
    required?: boolean
    error?: string | null
    hint?: string
}

const PICKER_PAGE_SIZE = 100

// Chooses an existing world-time point (latest first) or records a new one
// inline and selects it. Every option comes from the server's own list for this
// campaign's world; the picker never invents a time or an ordering. Used by the
// party, session, clock, and event forms.
export function WorldTimePicker({
    campaignId,
    id,
    label,
    value,
    onChange,
    required,
    error,
    hint,
}: WorldTimePickerProps) {
    const timesPath = worldTimesPath(campaignId, { limit: PICKER_PAGE_SIZE })
    const calendarsPath = campaignCalendarsPath(campaignId)
    const times = useAuthoringResource<WorldTimePage>(timesPath)
    const calendars = useAuthoringResource<CalendarListResponse>(calendarsPath)
    // The last lists that loaded stay through a failed re-read (after recording a time), so the form
    // that is choosing a time is not replaced by an error; a denied or missing answer drops them.
    const heldTimes = useKept(times.state, timesPath)
    const heldCalendars = useKept(calendars.state, calendarsPath)
    const [adding, setAdding] = useState(false)
    // A time that was recorded but is not in the list yet: it is chosen once the list shows it.
    const recorded = useUnreadWrite<string>()
    const refreshed = useConfirmedRefresh({
        status: recorded.status,
        reset: recorded.end,
        what: "world times",
        message: "World time recorded",
        read: async () => {
            const outcome = await times.refetch()
            if (outcome === "ok" && recorded.value !== null) {
                onChange(recorded.value)
                setAdding(false)
            }
            return outcome
        },
    })

    if (times.state.kind === "loading" || calendars.state.kind === "loading") {
        return <p role="status">Loading world times…</p>
    }
    if (heldTimes === null || heldCalendars === null) {
        return (
            <p role="alert">
                World times could not be loaded.{" "}
                {times.state.kind === "denied" || calendars.state.kind === "denied"
                    ? "You do not have permission to use them."
                    : "Try reloading the page."}
            </p>
        )
    }
    const items = heldTimes.items
    const hasMore = heldTimes.next_cursor !== null

    // Chosen only once the list that offers it has been read; a read that fails leaves the form open
    // with a notice and a read-only way to try again, and never records the time a second time.
    async function created(receipt: WorldTimeReceipt) {
        const outcome = await times.refetch()
        if (outcome === "ok") {
            onChange(receipt.world_time_id)
            setAdding(false)
        } else {
            recorded.mark(receipt.world_time_id)
        }
        return outcome
    }

    return (
        <div className="world-time-picker">
            <SelectField
                id={id}
                label={label}
                value={value}
                placeholder="Choose a time"
                required={required}
                hint={
                    hint ??
                    (hasMore ? `Showing the latest ${PICKER_PAGE_SIZE} times.` : undefined)
                }
                options={items.map((t) => ({ value: t.world_time_id, label: t.display }))}
                onChange={onChange}
                error={error}
            />
            {refreshed.notice}
            {refreshed.held ? null : adding ? (
                <WorldTimeForm
                    campaignId={campaignId}
                    calendars={heldCalendars.calendars}
                    times={items}
                    heading="Record a new world time"
                    nested
                    onCreated={created}
                    onCancel={() => setAdding(false)}
                />
            ) : (
                <button type="button" className="authoring-button" onClick={() => setAdding(true)}>
                    Record a new time
                </button>
            )}
        </div>
    )
}
