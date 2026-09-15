import type {
    ChangeEvent,
} from "react"
import { useTheme } from "./ThemeContext"
import {
    THEME_OPTIONS,
    isThemePreference,
} from "./themes"

const LIGHT_THEME_OPTIONS =
    THEME_OPTIONS.filter(
        (option) => option.group === "light",
    )

const DARK_THEME_OPTIONS =
    THEME_OPTIONS.filter(
        (option) => option.group === "dark",
    )

export function ThemeSelector() {
    const {
        preference,
        resolvedTheme,
        setThemePreference,
    } = useTheme()

    const activeTheme = THEME_OPTIONS.find(
        (option) =>
            option.code === resolvedTheme,
    )

    function handleThemeChange(
        event: ChangeEvent<HTMLSelectElement>,
    ): void {
        const selectedTheme =
            event.target.value

        if (
            isThemePreference(selectedTheme)
        ) {
            setThemePreference(selectedTheme)
        }
    }

    return (
        <div className="theme-selector">
            <label
                className="theme-selector__label"
                htmlFor="theme-preference"
            >
                Appearance
            </label>

            <select
                id="theme-preference"
                className="theme-selector__select"
                value={preference}
                onChange={handleThemeChange}
            >
                <option value="system">
                    System
                </option>

                <optgroup label="Light themes">
                    {LIGHT_THEME_OPTIONS.map(
                        (option) => (
                            <option
                                key={option.code}
                                value={option.code}
                            >
                                {option.label}
                            </option>
                        ),
                    )}
                </optgroup>

                <optgroup label="Dark themes">
                    {DARK_THEME_OPTIONS.map(
                        (option) => (
                            <option
                                key={option.code}
                                value={option.code}
                            >
                                {option.label}
                            </option>
                        ),
                    )}
                </optgroup>
            </select>

            <p
                className="theme-selector__status"
                aria-live="polite"
            >
                Active theme:{" "}
                {activeTheme?.label ??
                    resolvedTheme}
            </p>
        </div>
    )
}