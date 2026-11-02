import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import type { ReactNode } from "react"
import { createPortal } from "react-dom"
import { useBlocker } from "react-router"
import {
    NO_GUARD_VIEW,
    createGuardViewStore,
    useGuardView,
    useHostGuard,
    useNavigationHold,
} from "../../hooks/navigationHolds"
import type { GuardViewStore } from "../../hooks/navigationHolds"
import type { AuthoringMutationStatus, RefreshOutcome } from "../../hooks/useAuthoringMutation"
import type { Calendar, WorldTimeItem, WorldTimeReceipt } from "../../types/worldTime"
import { useAnnounce } from "./announcer"
import { ConfirmDialog } from "./ConfirmDialog"
import { FormDialog } from "./FormDialog"
import type { FormDialogPrompt } from "./FormDialog"
import { WorldTimeForm } from "./WorldTimeForm"
import "./authoring.css"

// The dialog is rendered outside the surrounding form's DOM (a nested <form> is invalid, and a button
// or Enter inside one would submit the caller's form), and React events from inside it are not passed
// on to the caller's handlers through the component tree.
function Isolated({ children }: { children: ReactNode }) {
    const stop = (event: { stopPropagation: () => void }) => event.stopPropagation()
    return createPortal(
        <div onClick={stop} onKeyDown={stop} onSubmit={stop} onChange={stop} onInput={stop}>
            {children}
        </div>,
        document.body,
    )
}

// The blocker for a picker with no page-level guard around it: it only exists while it is needed, so
// the router never has two. Its state is handed up through `view` rather than component state.
function OwnBlocker({ hold, view }: { hold: boolean; view: GuardViewStore }) {
    const holdRef = useRef(hold)
    useLayoutEffect(() => {
        holdRef.current = hold
    }, [hold])
    const blocker = useBlocker(
        ({ currentLocation, nextLocation }) => holdRef.current && currentLocation.pathname !== nextLocation.pathname,
    )
    useLayoutEffect(() => {
        view.set({
            blocked: blocker.state === "blocked",
            stay: () => {
                if (blocker.state === "blocked") blocker.reset()
            },
            discard: () => {
                holdRef.current = false
                if (blocker.state === "blocked") blocker.proceed()
            },
        })
    }, [blocker, view])
    useLayoutEffect(() => () => view.set(NO_GUARD_VIEW), [view])
    return null
}

interface PickerRecordTimeProps {
    campaignId: string
    calendars: Calendar[]
    items: WorldTimeItem[]
    // A confirmed time whose list has not been read yet: another is not recorded until it is.
    held: boolean
    // The write was confirmed: read the list again (a read only) and report how that went.
    onConfirmed: (receipt: WorldTimeReceipt) => Promise<RefreshOutcome>
    // Read the list again, for a person who wants to check an uncertain request.
    onReload: () => Promise<unknown>
}

// "Record a new time" for a world-time picker: a trigger and the reviewed form dialog, with the form kept
// mounted behind it so an uncertain request survives the dialog closing. It never touches the form that
// surrounds the picker; the picker chooses the confirmed point itself once the list shows it.
export function PickerRecordTime({ campaignId, calendars, items, held, onConfirmed, onReload }: PickerRecordTimeProps) {
    const announce = useAnnounce()
    const [open, setOpen] = useState(false)
    // The form is first mounted when the dialog is first opened, and then stays (see above).
    const [everOpened, setEverOpened] = useState(false)
    if (open && !everOpened) setEverOpened(true)
    const [formKey, setFormKey] = useState(0)
    const [dirty, setDirty] = useState(false)
    const [status, setStatus] = useState<AuthoringMutationStatus>({ kind: "idle" })
    const [confirming, setConfirming] = useState<"discard" | "unresolved" | null>(null)
    // The time a retained draft is entered beside: recorded, and not what the form holds now.
    const [keptAfter, setKeptAfter] = useState<string | null>(null)
    const trigger = useRef<HTMLButtonElement>(null)
    // Counts forms thrown away: a confirmation that began on an earlier one decides nothing for this one.
    const formEpoch = useRef(0)
    const alive = useRef(true)
    useEffect(() => {
        alive.current = true
        return () => {
            alive.current = false
        }
    }, [])

    const handleDirty = useCallback((next: boolean) => {
        setDirty(next)
        if (!next) setKeptAfter(null)
    }, [])
    const handleStatus = useCallback((next: AuthoringMutationStatus) => {
        setStatus(next)
        if (next.kind === "pending") setKeptAfter(null)
    }, [])

    const pending = status.kind === "pending"
    const unresolved = status.kind === "error" && (status.error.kind === "network" || status.error.kind === "server")
    const hold = dirty || pending || unresolved
    useNavigationHold(hold)
    useEffect(() => {
        if (!hold) return
        const warn = (event: BeforeUnloadEvent) => event.preventDefault()
        window.addEventListener("beforeunload", warn)
        return () => window.removeEventListener("beforeunload", warn)
    }, [hold])

    const hostGuarded = useHostGuard()
    const store = useMemo(() => createGuardViewStore(), [])
    const guard = useGuardView(store)
    const blocked = !hostGuarded && guard.blocked
    // A leave question replaces any other question, so none waits unseen behind it.
    if (blocked && confirming !== null) setConfirming(null)
    const leaveMessage = pending
        ? "A time is being recorded. If you leave now you will not see whether it was saved; check the list afterwards."
        : unresolved
          ? "A time you were recording may already have been recorded. If you leave you cannot retry it from here; check the list afterwards."
          : "You have entered a time that has not been recorded. If you leave, it is lost."

    function requestDismiss() {
        if (blocked) {
            guard.stay()
            return
        }
        if (confirming !== null) {
            setConfirming(null)
            return
        }
        if (pending) return
        if (unresolved) setConfirming("unresolved")
        else if (dirty) setConfirming("discard")
        else setOpen(false)
    }

    const prompt: FormDialogPrompt | null = blocked
        ? { message: leaveMessage, keepLabel: "Stay", confirmLabel: "Leave", onKeep: guard.stay, onConfirm: guard.discard }
        : confirming === "discard"
          ? {
                message: "Discard this time? What you entered will be lost.",
                keepLabel: "Keep editing",
                confirmLabel: "Discard",
                onKeep: () => setConfirming(null),
                onConfirm: () => {
                    setConfirming(null)
                    setKeptAfter(null)
                    formEpoch.current += 1
                    setOpen(false)
                    setFormKey((n) => n + 1)
                },
            }
          : confirming === "unresolved"
            ? {
                  message:
                      "This time may already have been recorded. Closing keeps it so you can retry the same request or check the list; nothing is discarded.",
                  keepLabel: "Keep editing",
                  confirmLabel: "Close and check later",
                  onKeep: () => setConfirming(null),
                  onConfirm: () => {
                      setConfirming(null)
                      setOpen(false)
                  },
              }
            : null

    async function created(receipt: WorldTimeReceipt, { hasUnrecordedInput }: { hasUnrecordedInput: () => boolean }) {
        const epoch = formEpoch.current
        const outcome = await onConfirmed(receipt)
        if (epoch !== formEpoch.current || !alive.current) return outcome
        setConfirming(null)
        // Asked now, after the read: whatever was entered while it ran is part of the answer.
        if (hasUnrecordedInput()) {
            setKeptAfter(receipt.world_time_id)
            if (outcome !== "ok") setOpen(false)
        } else {
            if (outcome === "ok") announce("World time recorded")
            setOpen(false)
        }
        return outcome
    }

    const keptItem = keptAfter === null ? undefined : items.find((t) => t.world_time_id === keptAfter)

    return (
        <>
            {unresolved && !open ? (
                <div className="authoring-message authoring-message--warning" role="status">
                    <div>
                        <p>
                            A time you were recording may or may not have been saved. The list can only show it if it is
                            among the times shown, so reopening to retry the same request is the safe way to find out.
                        </p>
                        <button type="button" className="authoring-button" onClick={() => setOpen(true)}>
                            Reopen to retry
                        </button>{" "}
                        <button type="button" className="authoring-button" onClick={() => void onReload()}>
                            Reload the list
                        </button>
                    </div>
                </div>
            ) : null}
            <button
                ref={trigger}
                type="button"
                className="authoring-button"
                aria-disabled={held}
                aria-describedby={held ? `${campaignId}-picker-held` : undefined}
                onClick={() => {
                    if (!held) setOpen(true)
                }}
            >
                Record a new time
            </button>
            {held ? (
                <p id={`${campaignId}-picker-held`} className="authoring-note">
                    Load the latest world times before recording another.
                    {dirty ? " What you entered after it is kept in the form." : ""}
                </p>
            ) : null}
            {hostGuarded ? null : <OwnBlocker hold={hold} view={store} />}
            {everOpened ? (
            <Isolated>
                <FormDialog
                    open={open}
                    title="Record a world time"
                    description="Recording a time adds it to this world's list. It does not change the campaign's current time or the form you were filling in."
                    onDismiss={requestDismiss}
                    pending={pending}
                    prompt={prompt}
                    returnFocusTo={() => trigger.current}
                >
                    {keptAfter !== null ? (
                        <div className="authoring-message authoring-message--success" role="status">
                            <p>
                                The time you submitted earlier was recorded
                                {keptItem === undefined ? "" : `: ${keptItem.display}`}. What is in the form now has not
                                been recorded.
                            </p>
                        </div>
                    ) : null}
                    <WorldTimeForm
                        key={formKey}
                        campaignId={campaignId}
                        calendars={calendars}
                        times={items}
                        heading="Record a new world time"
                        nested
                        holdUnresolved
                        onDirtyChange={handleDirty}
                        onStatusChange={handleStatus}
                        onCreated={created}
                        onCancel={requestDismiss}
                    />
                </FormDialog>
                <ConfirmDialog
                    open={blocked && !open}
                    title="Leave this page?"
                    description={leaveMessage}
                    confirmLabel="Leave"
                    cancelLabel="Stay"
                    onConfirm={guard.discard}
                    onCancel={guard.stay}
                />
            </Isolated>
            ) : null}
        </>
    )
}
