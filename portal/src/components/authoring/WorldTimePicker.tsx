import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { campaignCalendarsPath, worldTimesPath } from "../../api/worldTime"
import type { RefreshOutcome } from "../../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import { useConfirmedRefresh, useUnreadWrite } from "../../hooks/useConfirmedRefresh"
import { useKept } from "../../hooks/useKeptResource"
import type { CalendarListResponse, WorldTimePage, WorldTimeReceipt } from "../../types/worldTime"
import { SelectField } from "./fields"
import { PickerRecordTime } from "./PickerRecordTime"
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

// Chooses an existing world-time point (latest first) or records a new one in a dialog and selects it.
// Every option comes from the server's own list for this campaign's world; the picker never invents a
// time or an ordering. Used by the party, session, clock, and event forms. Recording never submits,
// resets or marks saved the form around the picker, and never moves the campaign clock.
//
// Choosing the recorded time: only once the list that was read afterwards shows it, and only if the
// form's selection is still what it was when the write was confirmed (a choice made since, by a person,
// is not overwritten by a late read). A recorded time the list does not show is said to be unchosen.
export function WorldTimePicker(props: WorldTimePickerProps) {
    // A different campaign never inherits another's dialog, draft, unresolved request or late answer.
    return <WorldTimePickerFor key={props.campaignId} {...props} />
}

// A time the server confirmed, waiting to be chosen once the list shows it.
interface Created {
    id: string
    // The form's selection when the write was confirmed: the created time is chosen only over this.
    base: string
    // Whether the list has been read since.
    read: "waiting" | "ok"
}

function WorldTimePickerFor({ campaignId, id, label, value, onChange, required, error, hint }: WorldTimePickerProps) {
    const timesPath = worldTimesPath(campaignId, { limit: PICKER_PAGE_SIZE })
    const calendarsPath = campaignCalendarsPath(campaignId)
    const times = useAuthoringResource<WorldTimePage>(timesPath)
    const calendars = useAuthoringResource<CalendarListResponse>(calendarsPath)
    // The last lists that loaded stay through a failed re-read (after recording a time), so the form
    // that is choosing a time is not replaced by an error; a denied or missing answer drops them.
    const heldTimes = useKept(times.state, timesPath)
    const heldCalendars = useKept(calendars.state, calendarsPath)
    const [created, setCreated] = useState<Created | null>(null)
    // The selection as it is now, updated by the picker's own choices at once (a render may not have happened).
    const latestValue = useRef(value)
    useLayoutEffect(() => {
        latestValue.current = value
    }, [value])
    // A time that was recorded but is not in the list yet: it is chosen once the list shows it.
    const recorded = useUnreadWrite<string>()
    const refreshed = useConfirmedRefresh({
        status: recorded.status,
        reset: recorded.end,
        what: "world times",
        message: "World time recorded",
        read: async () => {
            const outcome = await times.refetch()
            if (outcome === "ok") {
                const recordedId = recorded.value
                setCreated((current) => (current !== null && current.id === recordedId ? { ...current, read: "ok" } : current))
            }
            return outcome
        },
    })

    const items = heldTimes === null ? [] : heldTimes.items
    const listed = created !== null && items.some((t) => t.world_time_id === created.id)
    const applied = useRef<string | null>(null)
    useEffect(() => {
        if (created === null || created.read !== "ok" || !listed || applied.current === created.id) return
        applied.current = created.id
        if (latestValue.current === created.base) {
            latestValue.current = created.id
            onChange(created.id)
        }
    }, [created, listed, onChange])

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
    const hasMore = heldTimes.next_cursor !== null

    // The write is confirmed. The list is read again (a read only); a read that fails leaves a notice
    // and a read-only way to try again, and never records the time a second time.
    async function confirmed(receipt: WorldTimeReceipt): Promise<RefreshOutcome> {
        setCreated({ id: receipt.world_time_id, base: latestValue.current, read: "waiting" })
        const outcome = await times.refetch()
        if (outcome === "ok") {
            setCreated((current) => (current !== null && current.id === receipt.world_time_id ? { ...current, read: "ok" } : current))
        } else {
            recorded.mark(receipt.world_time_id)
        }
        return outcome
    }

    function choose(next: string) {
        latestValue.current = next
        // A choice made by a person ends the wait to choose the recorded time for them.
        setCreated(null)
        onChange(next)
    }

    const unchosen = created !== null && created.read === "ok" && !listed && value !== created.id

    return (
        <div className="world-time-picker">
            <SelectField
                id={id}
                label={label}
                value={value}
                placeholder="Choose a time"
                required={required}
                hint={hint ?? (hasMore ? `Showing the latest ${PICKER_PAGE_SIZE} times.` : undefined)}
                options={items.map((t) => ({ value: t.world_time_id, label: t.display }))}
                onChange={choose}
                error={error}
            />
            {refreshed.notice}
            {unchosen ? (
                <p role="status" className="authoring-note">
                    The time was recorded, but it is not among the times listed here, so it has not been chosen.
                </p>
            ) : null}
            <PickerRecordTime
                campaignId={campaignId}
                calendars={heldCalendars.calendars}
                items={items}
                held={refreshed.held}
                onConfirmed={confirmed}
                onReload={() => times.refetch()}
            />
        </div>
    )
}
