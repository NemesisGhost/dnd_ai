import {
    createContext,
    useContext,
} from "react"
import type {
    ResolvedTheme,
    ThemePreference,
} from "./themes"

export interface ThemeContextValue {
    readonly preference: ThemePreference
    readonly resolvedTheme: ResolvedTheme
    readonly setThemePreference: (
        preference: ThemePreference,
    ) => void
}

export const ThemeContext =
    createContext<ThemeContextValue | null>(
        null,
    )

export function useTheme():
    ThemeContextValue {
    const context = useContext(ThemeContext)

    if (context === null) {
        throw new Error(
            "useTheme must be used within ThemeProvider",
        )
    }

    return context
}