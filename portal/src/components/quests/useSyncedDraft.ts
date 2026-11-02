import { useState } from "react"

type Fields = Record<string, string>

const same = <T extends Fields>(a: T, b: T): boolean => Object.keys(a).every((key) => a[key]!.trim() === b[key]!.trim())

export interface SyncedDraft<T extends Fields> {
    values: T
    setValues: (next: T) => void
    // The person has changed something against what the form last agreed with.
    dirty: boolean
    // The saved fields changed elsewhere while the person's draft was unsent: the next save must not
    // silently acquire the newer version, so the person chooses.
    conflict: boolean
    // The quest version this form's saved fields belong to. It advances only while the form's own
    // saved fields still match what it last agreed with, so an unrelated change keeps saves
    // independent and a real change to these fields is never overwritten unseen.
    version: number
    // Replace the draft with the latest saved fields.
    loadLatest: () => void
    // Keep the draft and save over the newer fields, now that the person has seen them.
    keepMine: () => void
    // Call when submitting: the saved fields that arrive equal to these are this form's own save.
    submitting: (values: T) => void
}

// One retained form (an outcome's edit form, the planning notes). `server` is the form's own saved
// fields as the page last read them, `version` the quest's current version. A clean form follows
// the saved fields; a dirty one keeps its draft and, if those fields changed elsewhere, reports a
// conflict instead of adopting the newer version with older values.
export function useSyncedDraft<T extends Fields>(server: T, version: number): SyncedDraft<T> {
    const [base, setBase] = useState({ values: server, version })
    const [values, setValues] = useState(server)
    const [sent, setSent] = useState<T | null>(null)
    const serverChanged = !same(server, base.values)
    const dirty = !same(values, base.values)

    if (sent !== null && serverChanged && same(server, sent)) {
        // Its own save came back: that is the new agreement.
        setSent(null)
        setBase({ values: server, version })
    } else if (!serverChanged && base.version !== version) {
        setBase({ values: base.values, version })
    } else if (serverChanged && !dirty) {
        setBase({ values: server, version })
        setValues(server)
    }
    return {
        values,
        setValues,
        dirty,
        conflict: serverChanged && dirty && !(sent !== null && same(server, sent)),
        version: base.version,
        loadLatest: () => {
            setBase({ values: server, version })
            setValues(server)
        },
        keepMine: () => setBase({ values: server, version }),
        submitting: setSent,
    }
}
