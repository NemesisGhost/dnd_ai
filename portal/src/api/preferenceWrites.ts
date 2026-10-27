// Orders the fire-and-forget saved-preference writes against later reads.
//
// The last-visited campaign is written after a campaign page mounts, with no
// reload, while every campaign-scope change immediately refetches the session
// bootstrap. Left unordered, the refetch can be answered before the write
// commits and report the previous campaign as "last visited" -- a saved default
// that is older than the selection the user just made. Writes therefore run one
// at a time in the order they were issued (last selection wins), and a
// bootstrap read waits for the ones already issued.
let tail: Promise<unknown> = Promise.resolve()

export function enqueuePreferenceWrite<T>(run: () => Promise<T>): Promise<T> {
    const result = tail.then(run)
    tail = result.catch(() => undefined)
    return result
}

// Resolves once every write issued so far has finished, successfully or not.
export function preferenceWritesSettled(): Promise<void> {
    return tail.then(() => undefined)
}
