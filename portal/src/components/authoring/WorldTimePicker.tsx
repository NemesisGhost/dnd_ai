import { useState } from "react"
import { campaignCalendarsPath, worldTimesPath } from "../../api/worldTime"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
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
    const times = useAuthoringResource<WorldTimePage>(
        worldTimesPath(campaignId, { limit: PICKER_PAGE_SIZE }),
    )
    const calendars = useAuthoringResource<CalendarListResponse>(campaignCalendarsPath(campaignId))
    const [adding, setAdding] = useState(false)

    if (times.state.kind === "loading" || calendars.state.kind === "loading") {
        return <p role="status">Loading world times…</p>
    }
    if (times.state.kind !== "ready" || calendars.state.kind !== "ready") {
        return (
            <p role="alert">
                World times could not be loaded.{" "}
                {times.state.kind === "denied" || calendars.state.kind === "denied"
                    ? "You do not have permission to use them."
                    : "Try reloading the page."}
            </p>
        )
    }
    const items = times.state.data.items
    const hasMore = times.state.data.next_cursor !== null

    function created(receipt: WorldTimeReceipt) {
        void times.refetch().then(() => {
            onChange(receipt.world_time_id)
            setAdding(false)
        })
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
            {adding ? (
                <WorldTimeForm
                    campaignId={campaignId}
                    calendars={calendars.state.data.calendars}
                    times={items}
                    heading="Record a new world time"
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
