import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import {
    ThemeContext,
    type ThemeContextValue,
} from "./ThemeContext"
import { ThemeSelector } from "./ThemeSelector"

function renderThemeSelector(
    overrides: Partial<ThemeContextValue> = {},
) {
    const setThemePreference = vi.fn()

    const contextValue: ThemeContextValue = {
        preference: "system",
        resolvedTheme: "hearthstone",
        setThemePreference,
        ...overrides,
    }

    render(
        <ThemeContext.Provider
            value={contextValue}
        >
            <ThemeSelector />
        </ThemeContext.Provider>,
    )

    return {
        setThemePreference,
    }
}

describe("ThemeSelectorSelector", () => {
    it("renders every predefined theme", () => {
        renderThemeSelector()

        expect(
            screen
                .getAllByRole("option")
                .map((option) => option.textContent),
        ).toEqual([
            "System",
            "Hearthstone",
            "Verdant Archive",
            "Royal Plum",
            "Ash & Ember",
            "Parchment",
            "Iron & Ember",
            "Obsidian Hearth",
            "Midnight",
            "Verdant Night",
            "Royal Nocturne",
        ])
    })

    it("groups the explicit light and dark themes", () => {
        renderThemeSelector()

        const selector = screen.getByRole(
            "combobox",
            {
                name: "Appearance",
            },
        )

        const groups =
            selector.querySelectorAll("optgroup")

        expect(groups).toHaveLength(2)

        expect(groups[0]).toHaveAttribute(
            "label",
            "Light themes",
        )

        expect(groups[1]).toHaveAttribute(
            "label",
            "Dark themes",
        )
    })

    it("shows the saved preference as selected", () => {
        renderThemeSelector({
            preference: "midnight",
            resolvedTheme: "midnight",
        })

        expect(
            screen.getByRole("combobox", {
                name: "Appearance",
            }),
        ).toHaveValue("midnight")
    })

    it("shows the currently resolved appearance", () => {
        renderThemeSelector({
            preference: "system",
            resolvedTheme: "iron-ember",
        })

        expect(
            screen.getByText(
                "Active theme: Iron & Ember",
            ),
        ).toBeInTheDocument()
    })

    it("passes a valid selection to the provider", () => {
        const { setThemePreference } =
            renderThemeSelector()

        fireEvent.change(
            screen.getByRole("combobox", {
                name: "Appearance",
            }),
            {
                target: {
                    value: "royal-nocturne",
                },
            },
        )

        expect(
            setThemePreference,
        ).toHaveBeenCalledTimes(1)

        expect(
            setThemePreference,
        ).toHaveBeenCalledWith(
            "royal-nocturne",
        )
    })
})