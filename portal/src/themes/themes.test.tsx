import {
    //afterEach,
    describe,
    expect,
    it,
    //vi,
} from "vitest"

import {
    DEFAULT_THEME_PREFERENCE,
    SYSTEM_DARK_THEME,
    SYSTEM_LIGHT_THEME,
    THEME_OPTIONS,
    isThemePreference,
    resolveTheme,
} from "./themes"

describe("themes", () => {
    it("defaults to the system preference", () => {
        expect(DEFAULT_THEME_PREFERENCE).toBe("system")
    })

    it("uses Hearthstone as the system light theme", () => {
        expect(SYSTEM_LIGHT_THEME).toBe("hearthstone")
    })

    it("uses Iron & Ember as the system dark theme", () => {
        expect(SYSTEM_DARK_THEME).toBe("iron-ember")
    })

    it("defines every predefined theme exactly once", () => {
        const expectedCodes = [
            "system",
            "hearthstone",
            "verdant-archive",
            "royal-plum",
            "ash-ember",
            "parchment",
            "iron-ember",
            "obsidian-hearth",
            "midnight",
            "verdant-night",
            "royal-nocturne",
        ]

        expect(
            THEME_OPTIONS.map((option) => option.code),
        ).toEqual(expectedCodes)

        expect(
            new Set(
                THEME_OPTIONS.map((option) => option.code),
            ).size,
        ).toBe(THEME_OPTIONS.length)
    })

    it("classifies themes for the appearance selector", () => {
        expect(
            THEME_OPTIONS.map((option) => ({
                code: option.code,
                group: option.group,
            })),
        ).toEqual([
            {
                code: "system",
                group: "system",
            },
            {
                code: "hearthstone",
                group: "light",
            },
            {
                code: "verdant-archive",
                group: "light",
            },
            {
                code: "royal-plum",
                group: "light",
            },
            {
                code: "ash-ember",
                group: "light",
            },
            {
                code: "parchment",
                group: "light",
            },
            {
                code: "iron-ember",
                group: "dark",
            },
            {
                code: "obsidian-hearth",
                group: "dark",
            },
            {
                code: "midnight",
                group: "dark",
            },
            {
                code: "verdant-night",
                group: "dark",
            },
            {
                code: "royal-nocturne",
                group: "dark",
            },
        ])
    })

    it("accepts only predefined theme preferences", () => {
        for (const option of THEME_OPTIONS) {
            expect(
                isThemePreference(option.code),
            ).toBe(true)
        }

        expect(isThemePreference("")).toBe(false)
        expect(isThemePreference("light")).toBe(false)
        expect(isThemePreference("dark")).toBe(false)
        expect(isThemePreference("unknown")).toBe(false)
        expect(isThemePreference(null)).toBe(false)
        expect(isThemePreference(undefined)).toBe(false)
    })

    it("resolves System according to the browser preference", () => {
        expect(resolveTheme("system", false)).toBe(
            "hearthstone",
        )

        expect(resolveTheme("system", true)).toBe(
            "iron-ember",
        )
    })

    it("does not replace an explicitly selected theme", () => {
        expect(
            resolveTheme("verdant-archive", true),
        ).toBe("verdant-archive")

        expect(
            resolveTheme("midnight", false),
        ).toBe("midnight")
    })
})