import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
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
// selection has not been changed since the recording began. Every change of the controlled `value` that
// the picker observes (made through the picker or by the caller) counts, even one that returns to the
// earlier value, except the move to the recorded time itself. A recorded time that was not chosen, because
// of such a change or because the list does not show it, is said so. Changes React never delivers to the
// picker (several set in one batch that end where they began) cannot be seen.
export function WorldTimePicker(props: WorldTimePickerProps) {
    // A different campaign never inherits another's dialog, draft, unresolved request or late answer.
    return <WorldTimePickerFor key={props.campaignId} {...props} />
}

// A time the server confirmed, waiting to be chosen once the list shows it.
interface Created {
    // Which recording this is: eligibility and the "already handled" mark belong to one recording.
    seq: number
    id: string
    // The selection revision when the recording began: the created time is chosen only if it is unchanged.
    revision: number
    // Whether the list has been read since, and the selection revision at the moment it was: the recorded
    // time is chosen, or reported as not chosen, from that answer alone.
    read: "waiting" | { revision: number }
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
    // Counts observed changes of the selection. The move to the recorded time itself (chosen by this picker)
    // is not a change that withdraws the recording's own choice.
    const [seen, setSeen] = useState({ value, revision: 0 })
    if (seen.value !== value) {
        setSeen({ value, revision: created !== null && value === created.id ? seen.revision : seen.revision + 1 })
    }
    // The revision as of the last commit, read by the event that begins a recording.
    const revisionNow = useRef(seen.revision)
    useLayoutEffect(() => {
        revisionNow.current = seen.revision
    }, [seen.revision])
    // The revision when the recording in progress began (kept across retries of the same request).
    const began = useRef<number | null>(null)
    const begin = useCallback((retrying: boolean) => {
        if (!retrying || began.current === null) began.current = revisionNow.current
    }, [])
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
                setCreated((current) => (current !== null && current.id === recordedId ? { ...current, read: { revision: revisionNow.current } } : current))
            }
            return outcome
        },
    })

    const items = heldTimes === null ? [] : heldTimes.items
    const listed = created !== null && items.some((t) => t.world_time_id === created.id)
    const applied = useRef<number | null>(null)
    const sequence = useRef(0)
    useEffect(() => {
        if (created === null || created.read === "waiting" || !listed || applied.current === created.seq) return
        applied.current = created.seq
        if (created.read.revision === created.revision) onChange(created.id)
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
        sequence.current += 1
        const seq = sequence.current
        setCreated({ seq, id: receipt.world_time_id, revision: began.current ?? revisionNow.current, read: "waiting" })
        began.current = null
        const outcome = await times.refetch()
        if (outcome === "ok") {
            setCreated((current) => (current !== null && current.id === receipt.world_time_id ? { ...current, read: { revision: revisionNow.current } } : current))
        } else {
            recorded.mark(receipt.world_time_id)
        }
        return outcome
    }

    const overridden = created !== null && created.read !== "waiting" && created.read.revision !== created.revision
    const unchosen = created !== null && created.read !== "waiting" && value !== created.id && (overridden || !listed)

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
                onChange={onChange}
                error={error}
            />
            {refreshed.notice}
            {unchosen ? (
                <p role="status" className="authoring-note">
                    {overridden
                        ? "The time was recorded. It was not chosen because the selection was changed while it was being recorded."
                        : "The time was recorded, but it is not among the times listed here, so it has not been chosen."}
                </p>
            ) : null}
            <PickerRecordTime
                campaignId={campaignId}
                calendars={heldCalendars.calendars}
                items={items}
                held={refreshed.held}
                onConfirmed={confirmed}
                onBegin={begin}
                onReload={() => times.refetch()}
            />
        </div>
    )
}
