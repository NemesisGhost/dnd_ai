import { createContext, useContext } from "react"

// A single polite live region for the authenticated shell. Authoring pages
// announce results through it (docs/UI_DESIGN.md §5.11): success messages ride
// navigation state and are announced after the destination's authoritative
// fetch resolves, so the message survives the refetch that proves the write.
export interface Announcer {
    announce: (message: string) => void
}

export const AnnouncerContext = createContext<Announcer>({
    announce: () => {},
})

export function useAnnounce(): Announcer["announce"] {
    return useContext(AnnouncerContext).announce
}

// Navigation state carrying a success message to announce at the destination.
export interface AnnounceNavigationState {
    announce?: string
}

export function readAnnounceMessage(state: unknown): string | null {
    if (typeof state === "object" && state !== null && "announce" in state) {
        const message = (state as AnnounceNavigationState).announce
        return typeof message === "string" && message.length > 0 ? message : null
    }
    return null
}
