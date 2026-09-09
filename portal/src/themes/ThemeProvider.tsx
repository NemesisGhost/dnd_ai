import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"

import {
  ThemeContext,
  type ThemeContextValue,
} from "./ThemeContext"

import {
    DEFAULT_THEME_PREFERENCE,
    THEME_OPTIONS,
    isThemePreference,
    resolveTheme,
    type ResolvedTheme,
    type ThemePreference,
} from "./themes"

const THEME_STORAGE_KEY = "dnd-ai-theme"

const DARK_MODE_QUERY =
    "(prefers-color-scheme: dark)"

interface ThemeProviderProps {
    readonly children: ReactNode
}

function readStoredPreference():
    ThemePreference {
    if (typeof window === "undefined") {
        return DEFAULT_THEME_PREFERENCE
    }

    try {
        const storedPreference =
            window.localStorage.getItem(
                THEME_STORAGE_KEY,
            )

        return isThemePreference(
            storedPreference,
        )
            ? storedPreference
            : DEFAULT_THEME_PREFERENCE
    } catch {
        return DEFAULT_THEME_PREFERENCE
    }
}

function readSystemPrefersDark(): boolean {
    if (
        typeof window === "undefined" ||
        typeof window.matchMedia !== "function"
    ) {
        return false
    }

    return window.matchMedia(
        DARK_MODE_QUERY,
    ).matches
}

function getColorScheme(
    theme: ResolvedTheme,
): "light" | "dark" {
    const option = THEME_OPTIONS.find(
        (candidate) => candidate.code === theme,
    )

    return option?.group === "dark"
        ? "dark"
        : "light"
}

export function ThemeProvider({
    children,
}: ThemeProviderProps) {
    const [preference, setThemePreference] =
        useState<ThemePreference>(
            readStoredPreference,
        )

    const [systemPrefersDark, setSystemPrefersDark] =
        useState(readSystemPrefersDark)

    const resolvedTheme = resolveTheme(
        preference,
        systemPrefersDark,
    )

    useEffect(() => {
        if (
            typeof window.matchMedia !==
            "function"
        ) {
            return
        }

        const mediaQuery = window.matchMedia(
            DARK_MODE_QUERY,
        )

        function handlePreferenceChange(
            event: MediaQueryListEvent,
        ): void {
            setSystemPrefersDark(event.matches)
        }

        mediaQuery.addEventListener(
            "change",
            handlePreferenceChange,
        )

        return () => {
            mediaQuery.removeEventListener(
                "change",
                handlePreferenceChange,
            )
        }
    }, [])

    useEffect(() => {
        const documentRoot =
            document.documentElement

        documentRoot.dataset.theme =
            resolvedTheme

        documentRoot.dataset.themePreference =
            preference

        documentRoot.style.colorScheme =
            getColorScheme(resolvedTheme)

        try {
            window.localStorage.setItem(
                THEME_STORAGE_KEY,
                preference,
            )
        } catch {
            // Theme application must continue when
            // browser storage is unavailable.
        }
    }, [preference, resolvedTheme])

    const contextValue =
        useMemo<ThemeContextValue>(
            () => ({
                preference,
                resolvedTheme,
                setThemePreference,
            }),
            [
                preference,
                resolvedTheme,
            ],
        )

    return (
        <ThemeContext.Provider
            value={contextValue}
        >
            {children}
        </ThemeContext.Provider>
    )
}

