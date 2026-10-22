import { useState } from "react"

type Fields = Record<string, string>

const same = <T extends Fields>(a: T, b: T): boolean => Object.keys(a).every((key) => a[key]!.trim() === b[key]!.trim())

export interface RowDraft<T extends Fields> {
    values: T
    setValues: (next: T) => void
    // The person changed something against the saved fields the draft last agreed with.
    dirty: boolean
    // The row's saved fields changed elsewhere while the person's draft was unsent: saving pauses
    // until they choose, so a save never carries older values over a newer row unseen.
    conflict: boolean
    // The saved fields the draft is in agreement with. Anything a save must name about the row's
    // state (the event it was read at) is taken from here, never from a later read.
    agreed: T
    // Replace the draft with the latest saved fields.
    loadLatest: () => void
    // Keep the draft and save over the newer fields, now that the person has seen them.
    keepMine: () => void
    // A form that stays open after its own save calls this with the values the save sent, so it is
    // clean whether or not the read that follows succeeds. Editors that close on save never need it.
    accept: (sent: T) => void
}

// One on-demand editor of a row that stays mounted while the page reads the row again. `server` is
// the row's own editable fields as the page last read them. An untouched draft follows them; a
// dirty one keeps what was typed and, if the saved fields changed elsewhere, reports a conflict
// instead of adopting the newer row with older values. The editor closes when its save succeeds,
// so this never has to recognise its own save coming back.
export function useRowDraft<T extends Fields>(server: T): RowDraft<T> {
    const [agreed, setAgreed] = useState(server)
    const [values, setValues] = useState(server)
    // The server fields as they were when `accept` ran: until the read after a save brings newer
    // ones, the accepted values are not a difference from the row and are not replaced by it.
    const [held, setHeld] = useState<T | null>(null)
    const awaiting = held !== null && same(server, held)
    if (held !== null && !awaiting) setHeld(null)
    const serverChanged = !awaiting && !same(server, agreed)
    const dirty = !same(values, agreed)
    if (serverChanged && !dirty) {
        setAgreed(server)
        setValues(server)
    }
    return {
        values,
        setValues,
        dirty,
        conflict: serverChanged && dirty,
        agreed,
        loadLatest: () => {
            setAgreed(server)
            setValues(server)
        },
        keepMine: () => setAgreed(server),
        accept: (sent) => {
            setHeld(server)
            setAgreed(sent)
            setValues(sent)
        },
    }
}
