import { useLocation } from "react-router"

// Router state that restores the Characters view a person came from (the selected sheet, the
// browser with its filters, or a character's sheet), the way `worldSearch` restores the World
// browser.
export interface CharactersReturnState {
    charactersReturn?: string
}

const charactersBase = (campaignId: string): string =>
    `/app/${encodeURIComponent(campaignId)}/characters`

// The carried address, or undefined. Only a path inside this campaign's Characters area, with an
// optional query, is honoured, so a crafted state cannot send the person anywhere else.
export function readCharactersReturn(campaignId: string, state: unknown): string | undefined {
    const value = (state as CharactersReturnState | null | undefined)?.charactersReturn
    if (typeof value !== "string") return undefined
    const base = charactersBase(campaignId)
    if (!value.startsWith(base) || value.includes("..") || value.includes("//")) return undefined
    const rest = value.slice(base.length)
    return rest === "" || rest.startsWith("/") || rest.startsWith("?") ? value : undefined
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
