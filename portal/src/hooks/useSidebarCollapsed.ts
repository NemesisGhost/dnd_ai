import { useCallback, useState } from "react"

// The only thing the sidebar persists: a single presentation boolean.
// Nothing authentication- or authorization-related is ever stored here.
export const SIDEBAR_COLLAPSED_STORAGE_KEY = "dnd-ai-sidebar-collapsed"

function readCollapsed(): boolean {
    try {
        return window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true"
    } catch {
        return false
    }
}

function writeCollapsed(collapsed: boolean): void {
    try {
        window.localStorage.setItem(
            SIDEBAR_COLLAPSED_STORAGE_KEY,
            collapsed ? "true" : "false",
        )
    } catch {
        // Storage can be unavailable (private mode, blocked site data); the
        // sidebar still works for the life of this mount.
    }
}

// Re-read on mount, so the choice survives the scope-keyed remount every
// campaign change causes (RouteSessionProvider).
export function useSidebarCollapsed(): readonly [boolean, () => void] {
    const [collapsed, setCollapsed] = useState(readCollapsed)

    const toggle = useCallback(() => {
        setCollapsed((current) => {
            const next = !current
            writeCollapsed(next)
            return next
        })
    }, [])

    return [collapsed, toggle] as const
}
