import { parseCharacterType } from "../hooks/useCharactersBrowseState"
import { REVIEW_STATUS_ORDER } from "../utils/reviewStatus"
import { parseWorldCategory } from "../utils/worldCategories"

// The list state a task may persist (`TaskOriginV1.list`): per list route, the query keys the real
// page produces and the values each accepts. A syntax-valid query string is not enough: a persisted
// descriptor is rejected unless every key is declared for that route and every value passes its rule.
//
// Rejected, not normalized. An invalid descriptor makes `validateTask` return null (the entry falls
// back to the legacy adapter, then the route default), and a legacy key whose list state fails is
// ignored by the adapter. Nothing is rewritten, so what is stored is what was validated.
//
// Deliberately absent from every contract: perspective and scope keys (`character_id`, `party_id`,
// campaign/world/timeline ids), return URLs (`returnTo`), and any key a page does not produce. The
// Quests and Knowledge lists carry their perspective in the query, so their list state is empty
// (a change of perspective is a context transition, never list state). `q` is a user-typed browse
// search that the page already carries in router state; it is permitted because the plan whitelists
// browse queries, it is bounded, it never leaves `history.state`, and it is the only free text.

type Rule =
    | { kind: "enum"; accepts: (value: string) => boolean }
    | { kind: "flag" }
    | { kind: "text"; max: number }
    | { kind: "token"; max: number }
    | { kind: "name"; max: number }

interface KeyContract {
    rule: Rule
    // How many times the key may repeat (the forward-only cursor trail); 1 for a single value.
    repeat: number
}

/**
 * The most characters a persisted list query may have in total. It is a resource bound for tampered
 * history: 524,288 UTF-16 code units (JavaScript `string.length`, not bytes). A trail of maximum-length
 * (2048-character) cursors fits about 250 pages once percent-encoding of the key is counted. It is finite on
 * purpose: a query over it is rejected (the return falls back to the route default), never truncated, so
 * browse position is preserved up to this bound and not beyond. No browser limit is assumed or inferred.
 */
export const MAX_LIST_SEARCH = 512 * 1024

const one = (rule: Rule): KeyContract => ({ rule, repeat: 1 })

// The backend accepts a cursor of up to 2048 characters (api/pagination.py `_MAX_CURSOR_BYTES`, and the
// `Query(max_length=2048)` of every browse route). A cursor is opaque: it is checked for alphabet and length
// only, never decoded, and the stored string is the producer's own. The browsers keep every cursor of the
// page trail in the address (the API pages forward only), one per next-page action, with no cap, so the
// validator has none per key either: truncating or rejecting a long trail would silently reset the person's
// browse position on return. The resource bound is the total size of the query (MAX_LIST_SEARCH).
const BACKEND_CURSOR_MAX = 2048
const CURSOR = { rule: { kind: "token", max: BACKEND_CURSOR_MAX } as Rule, repeat: Number.POSITIVE_INFINITY }
const SEARCH = one({ kind: "text", max: 200 })
const HIDDEN = one({ kind: "flag" })

const NONE: Record<string, KeyContract> = {}

// Keys the Characters and World browsers build (`useCharactersBrowseState`, `useWorldBrowseState`).
const CHARACTER_BROWSE = {
    type: one({ kind: "enum", accepts: (value) => parseCharacterType(value) !== null }),
    q: SEARCH,
    hidden: HIDDEN,
    cursor: CURSOR,
}
const WORLD_BROWSE = {
    category: one({ kind: "enum", accepts: (value) => parseWorldCategory(value) !== null }),
    q: SEARCH,
    hidden: HIDDEN,
    cursor: CURSOR,
}

const LIST_CONTRACTS: Readonly<Record<string, Record<string, KeyContract>>> = {
    "characters.index": NONE,
    "characters.browse": CHARACTER_BROWSE,
    "campaign.world": WORLD_BROWSE,
    "review.queue": {
        status: one({ kind: "enum", accepts: (value) => REVIEW_STATUS_ORDER.includes(value) }),
        // The endpoint's own bound: `type: Query(max_length=60)` in api/review_queue.py.
        type: one({ kind: "name", max: 60 }),
    },
    "itemDefinitions.list": {
        // `category: Query(max_length=100)` in api/item_definition_authoring.py.
        category: one({ kind: "name", max: 100 }),
        homebrew: HIDDEN,
    },
    "items.list": NONE,
    "parties.list": NONE,
    "quests.list": NONE,
    "sessions.list": NONE,
    "knowledge.list": NONE,
    "worlds.timelines": NONE,
}

/** Whether a list route may be persisted as list state at all. */
export function hasListContract(route: string): boolean {
    return Object.prototype.hasOwnProperty.call(LIST_CONTRACTS, route)
}

function hasControl(text: string): boolean {
    for (let index = 0; index < text.length; index++) {
        const code = text.charCodeAt(index)
        if (code <= 0x1f || code === 0x7f) return true
    }
    return false
}

function valueAccepted(rule: Rule, value: string): boolean {
    switch (rule.kind) {
        case "enum":
            return rule.accepts(value)
        case "flag":
            return value === "1"
        case "text":
            return value.length <= rule.max && !hasControl(value)
        case "token":
            // The backend emits unpadded Base64url (`base64.urlsafe_b64encode(...).rstrip("=")` in
            // api/pagination.py): only [A-Za-z0-9_-]. Padding and the standard-alphabet characters
            // (. = ~ + /) are never emitted. This is a structural check; the backend's decode_cursor
            // stays authoritative for signature-free payload, keyset and freshness.
            return /^[A-Za-z0-9_-]+$/.test(value) && value.length <= rule.max
        case "name":
            return /^[A-Za-z0-9][A-Za-z0-9 _-]*$/.test(value) && value.length <= rule.max
    }
}

/**
 * Whether `search` (empty, or a `?` query string) is list state `route` produces: only the keys the
 * route declares, each no more often than allowed and with a value its rule accepts. The caller keeps
 * the string as given; nothing is rewritten.
 */
export function isValidListSearch(route: string, search: string): boolean {
    if (!hasListContract(route)) return false
    if (search === "") return true
    if (!search.startsWith("?") || search.length > MAX_LIST_SEARCH) return false
    const keys = LIST_CONTRACTS[route]!
    const seen = new Map<string, number>()
    for (const [key, value] of new URLSearchParams(search)) {
        if (!Object.prototype.hasOwnProperty.call(keys, key)) return false
        const count = (seen.get(key) ?? 0) + 1
        seen.set(key, count)
        const contract = keys[key]!
        if (count > contract.repeat || !valueAccepted(contract.rule, value)) return false
    }
    return true
}
