export type ThemeGroup =
    | "system"
    | "light"
    | "dark"

export type ResolvedTheme =
    | "hearthstone"
    | "verdant-archive"
    | "royal-plum"
    | "ash-ember"
    | "parchment"
    | "iron-ember"
    | "obsidian-hearth"
    | "midnight"
    | "verdant-night"
    | "royal-nocturne"

export type ThemePreference =
    | "system"
    | ResolvedTheme

export interface ThemeOption {
    readonly code: ThemePreference
    readonly label: string
    readonly group: ThemeGroup
}

export const DEFAULT_THEME_PREFERENCE:
    ThemePreference = "system"

export const SYSTEM_LIGHT_THEME:
    ResolvedTheme = "hearthstone"

export const SYSTEM_DARK_THEME:
    ResolvedTheme = "iron-ember"

export const THEME_OPTIONS = [
    {
        code: "system",
        label: "System",
        group: "system",
    },
    {
        code: "hearthstone",
        label: "Hearthstone",
        group: "light",
    },
    {
        code: "verdant-archive",
        label: "Verdant Archive",
        group: "light",
    },
    {
        code: "royal-plum",
        label: "Royal Plum",
        group: "light",
    },
    {
        code: "ash-ember",
        label: "Ash & Ember",
        group: "light",
    },
    {
        code: "parchment",
        label: "Parchment",
        group: "light",
    },
    {
        code: "iron-ember",
        label: "Iron & Ember",
        group: "dark",
    },
    {
        code: "obsidian-hearth",
        label: "Obsidian Hearth",
        group: "dark",
    },
    {
        code: "midnight",
        label: "Midnight",
        group: "dark",
    },
    {
        code: "verdant-night",
        label: "Verdant Night",
        group: "dark",
    },
    {
        code: "royal-nocturne",
        label: "Royal Nocturne",
        group: "dark",
    },
] as const satisfies readonly ThemeOption[]

export function isThemePreference(
    value: unknown,
): value is ThemePreference {
    return (
        typeof value === "string" &&
        THEME_OPTIONS.some(
            (option) => option.code === value,
        )
    )
}

export function resolveTheme(
    preference: ThemePreference,
    prefersDark: boolean,
): ResolvedTheme {
    if (preference !== "system") {
        return preference
    }

    return prefersDark
        ? SYSTEM_DARK_THEME
        : SYSTEM_LIGHT_THEME
}