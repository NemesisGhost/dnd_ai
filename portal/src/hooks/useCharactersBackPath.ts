import { useLocation } from "react-router"

// Router state that restores the Characters view a person came from (the selected sheet, the
// browser with its filters, or a character's sheet), the way `worldSearch` restores the World
// browser.
export interface CharactersReturnState {
    charactersReturn?: string
}

const charactersBase = (campaignId: string): string =>
    `/app/${encodeURIComponent(campaignId)}/characters`

// The one origin the carried address is resolved against, so only its path and query can matter.
const RESOLVE_ORIGIN = "http://return.invalid"

// Character ids are UUIDs (the API contract), so a character segment is never decoded: a literal
// UUID has nothing to decode, and anything else (a creation route in any casing, an encoded
// separator, a double encoding) simply does not match. The router matches case-insensitively and
// decodes parameters, which is why only the lowercase literals `all` and `inventory` and UUIDs are accepted.
const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

// What follows `/characters` for a destination a sheet or the browser can come from: the browser, a character's sheet and its inventory. Creation, edit and build routes are
// never a return target.
const SUPPORTED_REST = new RegExp(`^(?:|/all|/${UUID}|/${UUID}/inventory)$`)

// Any C0 control character or DEL (written as code points: a control character in a regex literal
// is a lint error).
function hasControl(text: string): boolean {
    for (let index = 0; index < text.length; index++) {
        const code = text.charCodeAt(index)
        if (code <= 0x1f || code === 0x7f) return true
    }
    return false
}

// The carried address, or undefined. The address is resolved the way the browser and router
// resolve it (so encoded dot segments are already collapsed), and only the canonical path and query
// are judged: the path must be one of this campaign's Characters routes with exact boundaries.
// Whatever is returned is that canonical form, never the raw input, so a crafted state cannot send
// the person anywhere else and what is checked is what is navigated to.
export function readCharactersReturn(campaignId: string, state: unknown): string | undefined {
    const value = (state as CharactersReturnState | null | undefined)?.charactersReturn
    if (typeof value !== "string") return undefined
    // Same-origin absolute paths only; "//" and "\\" would make the parser read a host.
    if (!value.startsWith("/") || value.startsWith("//") || /[\\#\s]/.test(value) || hasControl(value)) {
        return undefined
    }
    let target: URL
    let base: string
    try {
        target = new URL(value, RESOLVE_ORIGIN)
        base = new URL(charactersBase(campaignId), RESOLVE_ORIGIN).pathname
    } catch {
        return undefined
    }
    if (target.origin !== RESOLVE_ORIGIN) return undefined
    const path = target.pathname
    if (!path.startsWith(base) || !SUPPORTED_REST.test(path.slice(base.length))) return undefined
    return `${path}${target.search}`
}

// The valid return key of a location state, for forwarding through in-page links.
export function pickCharactersReturnState(
    campaignId: string,
    state: unknown,
): CharactersReturnState | undefined {
    const charactersReturn = readCharactersReturn(campaignId, state)
    return charactersReturn === undefined ? undefined : { charactersReturn }
}

// "Back to characters" target: the view the sheet was opened from, else the characters browser.
export function useCharactersBackPath(campaignId: string): string {
    return readCharactersReturn(campaignId, useLocation().state) ?? `${charactersBase(campaignId)}/all`
}
