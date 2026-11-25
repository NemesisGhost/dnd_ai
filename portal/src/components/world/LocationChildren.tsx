import { useCallback, useContext, useEffect, useRef, useState } from "react"
import type { FormEvent } from "react"
import { Link, useLocation, useNavigate } from "react-router"
import { fetchLocationChildren, WorldRequestError } from "../../api/world"
import { SessionContext } from "../../context/SessionContext"
import type { LocationChild } from "../../types/world"
import { humanizeCode } from "../../utils/humanize"
import { LifecycleBadge } from "../authoring/feedback"
import { focusSoon } from "../authoring/focusSoon"
import { DetailPanel } from "../DetailPanel"
import { plural } from "./areaText"
import { worldRecordPath } from "./worldPaths"

// The address parameter that holds the applied search, so Back, Forward and a copied link restore it.
export const WITHIN_PARAM = "within"

interface Props {
    campaignId: string
    location: { location_id: string; name: string }
    // An editor's host asks for drafts and archived places too; the server decides whether to honor it.
    includeHidden: boolean
    // The task the opened place keeps, as the host's other in-record links carry it.
    linkState?: object
}

type Status = "loading" | "ready" | "unavailable" | "failed"

interface Snapshot {
    // The read tuple the rows belong to (campaign, place, search, preview).
    key: string
    rows: LocationChild[]
    next: string | null
    status: Status
    // The page a failed read was for: null for the first page.
    failedCursor: string | null
    moreLoading: boolean
}

const loading = (key: string): Snapshot => ({ key, rows: [], next: null, status: "loading", failedCursor: null, moreLoading: false })

interface Owner {
    key: string
}

const SEARCH_ID = "places-within-search"
const rowId = (id: string) => `place-within-${id}`

// One owner per read tuple: a change of campaign, place, search or preview, or unmount, ends the owner, so
// an answer for any earlier tuple is ignored, and the rows shown are never another tuple's.
function usePlacesWithin(
    campaignId: string,
    locationId: string,
    within: string,
    includeHidden: boolean,
    onAppended: (firstNewId: string | null) => void,
) {
    // A page rendered outside a session (a reader under test) has none to reload; a 401 then only clears the rows.
    const reload = useContext(SessionContext)?.reload
    const key = JSON.stringify([campaignId, locationId, within, includeHidden])
    const [snapshot, setSnapshot] = useState<Snapshot>(() => loading(key))
    const [attempt, setAttempt] = useState(0)
    const owner = useRef<Owner | null>(null)
    const controller = useRef<AbortController | null>(null)

    // Rows belong to the tuple they were read for: under any other tuple none are shown.
    const current = snapshot.key === key ? snapshot : loading(key)

    const read = useCallback(
        (own: Owner, signal: AbortSignal, cursor: string | null, known: Set<string> | null): Promise<void> =>
            fetchLocationChildren(campaignId, locationId, { q: within, cursor, includeHidden }, signal)
                .then((page) => {
                    if (owner.current !== own) return
                    const fresh = known === null ? page.items : page.items.filter((row) => !known.has(row.location_id))
                    if (known !== null) onAppended(fresh[0]?.location_id ?? null)
                    // A first page replaces whatever the snapshot held; a later page extends this tuple's rows.
                    setSnapshot((previous) =>
                        known !== null && previous.key !== own.key
                            ? previous
                            : {
                                  key: own.key,
                                  rows: known === null ? page.items : [...previous.rows, ...fresh],
                                  next: page.next_cursor,
                                  status: "ready",
                                  failedCursor: null,
                                  moreLoading: false,
                              },
                    )
                })
                .catch((error: unknown) => {
                    if (owner.current !== own) return
                    if (error instanceof WorldRequestError && error.status === 401) {
                        setSnapshot(loading(own.key))
                        void reload?.()
                        return
                    }
                    if (error instanceof WorldRequestError && (error.status === 403 || error.status === 404)) {
                        setSnapshot({ key: own.key, rows: [], next: null, status: "unavailable", failedCursor: null, moreLoading: false })
                        return
                    }
                    setSnapshot((previous) =>
                        previous.key !== own.key
                            ? { ...loading(own.key), status: "failed" }
                            : { ...previous, status: "failed", failedCursor: cursor, moreLoading: false },
                    )
                }),
        [campaignId, locationId, within, includeHidden, onAppended, reload],
    )

    useEffect(() => {
        const own: Owner = { key }
        const abort = new AbortController()
        owner.current = own
        controller.current = abort
        void read(own, abort.signal, null, null)
        return () => {
            abort.abort()
            if (owner.current === own) owner.current = null
        }
        // `read` is rebuilt whenever its tuple changes, which `key` already covers; a rebuild for any
        // other reason (the session's reload) must not start a read.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key, attempt])

    const showMore = useCallback(() => {
        const own = owner.current
        const signal = controller.current?.signal
        if (own === null || signal === undefined || current.next === null) return
        setSnapshot({ ...current, status: "ready", moreLoading: true })
        void read(own, signal, current.next, new Set(current.rows.map((row) => row.location_id)))
    }, [current, read])

    const retry = useCallback(() => {
        const own = owner.current
        const signal = controller.current?.signal
        if (own === null || signal === undefined) return
        if (current.failedCursor === null) {
            setSnapshot(loading(key))
            setAttempt((n) => n + 1)
            return
        }
        setSnapshot({ ...current, status: "ready", failedCursor: null, moreLoading: true })
        void read(own, signal, current.failedCursor, new Set(current.rows.map((row) => row.location_id)))
    }, [current, key, read])

    return { current, showMore, retry }
}

// The places directly inside a place, 25 at a time, and a search of the places further down. The
// applied search is in the address (`within`), so the page can be left and returned to. Nothing here is
// counted or hinted: what is shown is exactly what the read returned for the current access.
export function LocationChildren({ campaignId, location, includeHidden, linkState }: Props) {
    const address = useLocation()
    const navigate = useNavigate()
    const within = new URLSearchParams(address.search).get(WITHIN_PARAM)?.trim() ?? ""
    const [draft, setDraft] = useState(within)
    const [seen, setSeen] = useState(within)
    // Back and Forward change the applied search: the field follows it.
    if (seen !== within) {
        setSeen(within)
        setDraft(within)
    }
    const inputRef = useRef<HTMLInputElement>(null)
    const statusRef = useRef<HTMLParagraphElement>(null)
    const focusTarget = useRef<string | null | undefined>(undefined)
    const onAppended = useCallback((firstNewId: string | null) => {
        focusTarget.current = firstNewId
    }, [])
    const { current, showMore, retry } = usePlacesWithin(campaignId, location.location_id, within, includeHidden, onAppended)

    // After Show more, focus goes to the first place it added, or to the status line if it added none.
    useEffect(() => {
        const target = focusTarget.current
        if (target === undefined || current.moreLoading) return
        focusTarget.current = undefined
        if (target === null) statusRef.current?.focus()
        else document.getElementById(rowId(target))?.focus()
    })

    function apply(text: string) {
        const params = new URLSearchParams(address.search)
        if (text === "") params.delete(WITHIN_PARAM)
        else params.set(WITHIN_PARAM, text)
        const search = params.toString()
        void navigate({ pathname: address.pathname, search: search === "" ? "" : `?${search}` }, { replace: true, state: address.state })
        // The page's own arrival focus may follow a change of address, so the field is returned to after it.
        inputRef.current?.focus()
        focusSoon(SEARCH_ID)
    }

    function submit(event: FormEvent) {
        event.preventDefault()
        apply(draft.trim())
    }

    const name = location.name
    const count = current.rows.length
    let statusText = ""
    if (current.status === "loading") statusText = "Loading places…"
    else if (current.status === "unavailable") statusText = "Places within this place are not available."
    else if (count === 0 && current.status === "ready") {
        statusText = within === "" ? `No places within ${name}.` : `No places within ${name} match “${within}”.`
    } else if (count > 0) {
        statusText = `Showing ${plural(count, "place", "places")}.${current.next !== null ? " More are available." : ""}`
    }

    return (
        <DetailPanel title={`Places within ${name}`}>
            <form role="search" aria-label={`Search places within ${name}`} className="row-actions" onSubmit={submit}>
                <label htmlFor={SEARCH_ID} className="visually-hidden">
                    {`Search places within ${name}`}
                </label>
                <input
                    id={SEARCH_ID}
                    ref={inputRef}
                    type="search"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                />
                <button type="submit" className="authoring-button">
                    Search
                </button>
                {within !== "" ? (
                    <button
                        type="button"
                        className="authoring-button"
                        onClick={() => {
                            setDraft("")
                            apply("")
                        }}
                    >
                        Clear search
                    </button>
                ) : null}
            </form>
            <p role="status" ref={statusRef} tabIndex={-1} className="authoring-note">
                {statusText}
            </p>
            {current.status === "failed" ? (
                <div role="alert">
                    <p>{`Places within ${name} could not be loaded.`}</p>
                    <button type="button" className="authoring-button" onClick={retry}>
                        Try again
                    </button>
                </div>
            ) : null}
            {count > 0 ? (
                <ul className="op-list" aria-label={`Places within ${name}`}>
                    {current.rows.map((row) => (
                        <li key={row.location_id}>
                            <Link id={rowId(row.location_id)} to={worldRecordPath(campaignId, "location", row.location_id)} state={linkState}>
                                {row.name}
                            </Link>{" "}
                            <span>{humanizeCode(row.location_type_code)}</span>
                            {row.path.length > 0 ? <span>{` in ${row.path.map((crumb) => crumb.name).join(" › ")}`}</span> : null}
                            {includeHidden ? (
                                <>
                                    {" "}
                                    <LifecycleBadge status={row.lifecycle_status === "archived" ? "archived" : row.canon_status} />
                                </>
                            ) : null}
                        </li>
                    ))}
                </ul>
            ) : null}
            {current.next !== null && current.status !== "unavailable" ? (
                <button type="button" className="authoring-button" disabled={current.moreLoading} onClick={showMore}>
                    Show more places
                </button>
            ) : null}
        </DetailPanel>
    )
}
