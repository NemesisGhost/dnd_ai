import {
    act,
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { ThemeProvider } from "./ThemeProvider"
import { useTheme } from "./ThemeContext"

const THEME_STORAGE_KEY = "dnd-ai-theme"
const DARK_MODE_QUERY =
    "(prefers-color-scheme: dark)"

const mediaQueryListeners = new Set<
    (event: MediaQueryListEvent) => void
>()

function installMatchMedia(
    prefersDark: boolean,
): void {
    mediaQueryListeners.clear()

    const mediaQueryList = {
        matches: prefersDark,
        media: DARK_MODE_QUERY,
        onchange: null,
        addEventListener: vi.fn(
            (
                _eventName: string,
                listener: (
                    event: MediaQueryListEvent,
                ) => void,
            ) => {
                mediaQueryListeners.add(listener)
            },
        ),
        removeEventListener: vi.fn(
            (
                _eventName: string,
                listener: (
                    event: MediaQueryListEvent,
                ) => void,
            ) => {
                mediaQueryListeners.delete(listener)
            },
        ),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
    } as unknown as MediaQueryList

    Object.defineProperty(
        window,
        "matchMedia",
        {
            configurable: true,
            writable: true,
            value: vi.fn(() => mediaQueryList),
        },
    )
}

function changeSystemPreference(
    prefersDark: boolean,
): void {
    const event = {
        matches: prefersDark,
        media: DARK_MODE_QUERY,
    } as MediaQueryListEvent

    act(() => {
        for (const listener of mediaQueryListeners) {
            listener(event)
        }
    })
}

function ThemeProbe() {
    const {
        preference,
        resolvedTheme,
        setThemePreference,
    } = useTheme()

    return (
        <>
            <div>
                Preference: {preference}
            </div>

            <div>
                Resolved: {resolvedTheme}
            </div>

            <button
                type="button"
                onClick={() =>
                    setThemePreference("royal-plum")
                }
            >
                Choose Royal Plum
            </button>
        </>
    )
}

function renderThemeProvider() {
    return render(
        <ThemeProvider>
            <ThemeProbe />
        </ThemeProvider>,
    )
}

describe("ThemeProvider", () => {
    beforeEach(() => {
        localStorage.clear()
        installMatchMedia(false)

        delete document.documentElement.dataset.theme
        delete document.documentElement.dataset
            .themePreference

        document.documentElement.style.removeProperty(
            "color-scheme",
        )
    })

    it("defaults to System and resolves to Hearthstone in system light mode", () => {
        renderThemeProvider()

        expect(
            screen.getByText("Preference: system"),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "Resolved: hearthstone",
            ),
        ).toBeInTheDocument()

        expect(
            document.documentElement,
        ).toHaveAttribute(
            "data-theme",
            "hearthstone",
        )

        expect(
            document.documentElement,
        ).toHaveAttribute(
            "data-theme-preference",
            "system",
        )

        expect(
            document.documentElement.style
                .colorScheme,
        ).toBe("light")
    })

    it("resolves System to Iron & Ember in system dark mode", () => {
        installMatchMedia(true)

        renderThemeProvider()

        expect(
            screen.getByText(
                "Resolved: iron-ember",
            ),
        ).toBeInTheDocument()

        expect(
            document.documentElement,
        ).toHaveAttribute(
            "data-theme",
            "iron-ember",
        )

        expect(
            document.documentElement.style
                .colorScheme,
        ).toBe("dark")
    })

    it("reacts when the system appearance changes", () => {
        renderThemeProvider()

        changeSystemPreference(true)

        expect(
            screen.getByText(
                "Resolved: iron-ember",
            ),
        ).toBeInTheDocument()

        expect(
            document.documentElement,
        ).toHaveAttribute(
            "data-theme",
            "iron-ember",
        )

        changeSystemPreference(false)

        expect(
            screen.getByText(
                "Resolved: hearthstone",
            ),
        ).toBeInTheDocument()
    })

    it("restores an explicit stored preference", () => {
        localStorage.setItem(
            THEME_STORAGE_KEY,
            "royal-nocturne",
        )

        renderThemeProvider()

        expect(
            screen.getByText(
                "Preference: royal-nocturne",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "Resolved: royal-nocturne",
            ),
        ).toBeInTheDocument()

        expect(
            document.documentElement.style
                .colorScheme,
        ).toBe("dark")
    })

    it("falls back to System for an invalid stored preference", () => {
        localStorage.setItem(
            THEME_STORAGE_KEY,
            "unsupported-theme",
        )

        renderThemeProvider()

        expect(
            screen.getByText("Preference: system"),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "Resolved: hearthstone",
            ),
        ).toBeInTheDocument()
    })

    it("applies and stores a newly selected theme", () => {
        renderThemeProvider()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Choose Royal Plum",
            }),
        )

        expect(
            screen.getByText(
                "Preference: royal-plum",
            ),
        ).toBeInTheDocument()

        expect(
            document.documentElement,
        ).toHaveAttribute(
            "data-theme",
            "royal-plum",
        )

        expect(
            localStorage.getItem(
                THEME_STORAGE_KEY,
            ),
        ).toBe("royal-plum")
    })

    it("does not replace an explicit theme when the system appearance changes", () => {
        localStorage.setItem(
            THEME_STORAGE_KEY,
            "midnight",
        )

        renderThemeProvider()

        changeSystemPreference(true)
        changeSystemPreference(false)

        expect(
            screen.getByText(
                "Preference: midnight",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "Resolved: midnight",
            ),
        ).toBeInTheDocument()

        expect(
            document.documentElement,
        ).toHaveAttribute(
            "data-theme",
            "midnight",
        )
    })
})