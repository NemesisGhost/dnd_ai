import {
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from "@testing-library/react"
import type { ComponentProps } from "react"
import { MemoryRouter } from "react-router"
import {
    describe,
    expect,
    it,
} from "vitest"
import { AppNavigation } from "./AppNavigation"

const defaultProps = {
    campaignId: "campaign-a",
    askEnabled: false,
    showAccess: false,
} satisfies ComponentProps<typeof AppNavigation>

function renderNavigation(
    overrides: Partial<
        ComponentProps<typeof AppNavigation>
    > = {},
) {
    return render(
        <MemoryRouter
            initialEntries={[
                "/app/campaign-a/home",
            ]}
        >
            <AppNavigation
                {...defaultProps}
                {...overrides}
            />
        </MemoryRouter>,
    )
}

describe("AppNavigation", () => {
    it("renders the ordinary campaign destinations", () => {
        renderNavigation()

        const navigation = screen.getByRole(
            "navigation",
            {
                name: "Campaign",
            },
        )

        const expectedDestinations = [
            ["Campaign Home", "/app/campaign-a/home"],
            ["World", "/app/campaign-a/world"],
            [
                "Characters",
                "/app/campaign-a/characters",
            ],
            ["Quests", "/app/campaign-a/quests"],
            [
                "Sessions",
                "/app/campaign-a/sessions",
            ],
            [
                "Knowledge",
                "/app/campaign-a/knowledge",
            ],
        ]

        for (const [name, destination] of
            expectedDestinations) {
            expect(
                within(navigation).getByRole(
                    "link",
                    { name },
                ),
            ).toHaveAttribute(
                "href",
                destination,
            )
        }

        expect(
            within(navigation).queryByRole(
                "link",
                {
                    name: "Change campaign",
                },
            ),
        ).not.toBeInTheDocument()
    })

    it("keeps Ask visibly disabled without making it a link", () => {
        renderNavigation({
            askEnabled: false,
        })

        const navigation = screen.getByRole(
            "navigation",
            {
                name: "Campaign",
            },
        )

        expect(
            within(navigation).queryByRole(
                "link",
                {
                    name: "Ask",
                },
            ),
        ).not.toBeInTheDocument()

        const askLabel =
            within(navigation).getByText("Ask")

        expect(askLabel).toHaveClass(
            "app-navigation__label",
        )

        expect(
            askLabel.closest(
                "[aria-disabled='true']",
            ),
        ).toHaveAttribute(
            "title",
            "Unavailable until Phase 12 is verified",
        )
    })

    it("shows the Access disclosure only when authorized", () => {
        const { rerender } = renderNavigation({
            showAccess: false,
        })

        expect(
            screen.queryByRole("button", {
                name: "Access",
            }),
        ).not.toBeInTheDocument()

        rerender(
            <MemoryRouter
                initialEntries={[
                    "/app/campaign-a/home",
                ]}
            >
                <AppNavigation
                    {...defaultProps}
                    showAccess
                />
            </MemoryRouter>,
        )

        expect(
            screen.getByRole("button", {
                name: "Access",
            }),
        ).toHaveAttribute("aria-expanded", "false")

        expect(
            screen.queryByRole("link", {
                name: "Access Management",
            }),
        ).not.toBeInTheDocument()
    })

    describe("Access submenu", () => {
        function renderWithAccess(
            initialEntry = "/app/campaign-a/home",
        ) {
            return render(
                <MemoryRouter initialEntries={[initialEntry]}>
                    <AppNavigation
                        {...defaultProps}
                        showAccess
                    />
                </MemoryRouter>,
            )
        }

        it("is collapsed by default and reveals both children when opened", () => {
            renderWithAccess()

            const button = screen.getByRole("button", {
                name: "Access",
            })

            expect(button).toHaveAttribute("aria-expanded", "false")
            expect(
                screen.queryByRole("link", { name: "Access Management" }),
            ).not.toBeInTheDocument()

            fireEvent.click(button)

            expect(button).toHaveAttribute("aria-expanded", "true")
            expect(
                screen.getByRole("link", { name: "Access Management" }),
            ).toHaveAttribute("href", "/app/campaign-a/access")
            expect(
                screen.getByRole("link", { name: "Invitations" }),
            ).toHaveAttribute(
                "href",
                "/app/campaign-a/access/invitations",
            )
        })

        it("marks the parent active while either child route is current", () => {
            renderWithAccess("/app/campaign-a/access/invitations")

            expect(
                screen.getByRole("button", { name: "Access" }),
            ).toHaveClass("app-navigation__link--active")

            expect(
                screen.getByRole("link", { name: "Invitations" }),
            ).toHaveAttribute("aria-current", "page")
            expect(
                screen.getByRole("link", { name: "Access Management" }),
            ).not.toHaveAttribute("aria-current")
        })

        it("starts open when a child route is already active", () => {
            renderWithAccess("/app/campaign-a/access")

            expect(
                screen.getByRole("button", { name: "Access" }),
            ).toHaveAttribute("aria-expanded", "true")
            expect(
                screen.getByRole("link", { name: "Access Management" }),
            ).toHaveAttribute("aria-current", "page")
        })

        it("closes and refocuses the button on Escape", async () => {
            renderWithAccess()

            const button = screen.getByRole("button", { name: "Access" })
            fireEvent.click(button)

            await waitFor(() => {
                expect(
                    screen.getByRole("link", { name: "Access Management" }),
                ).toHaveFocus()
            })

            fireEvent.keyDown(
                screen.getByRole("link", { name: "Access Management" }),
                { key: "Escape" },
            )

            expect(button).toHaveAttribute("aria-expanded", "false")
            expect(button).toHaveFocus()
        })

        it("closes on an outside click without moving focus", () => {
            renderWithAccess()

            fireEvent.click(screen.getByRole("button", { name: "Access" }))

            const outside = screen.getByRole("link", {
                name: "World",
            })
            fireEvent.pointerDown(outside)

            expect(
                screen.getByRole("button", { name: "Access" }),
            ).toHaveAttribute("aria-expanded", "false")
        })

        it("closes after choosing a child destination", () => {
            renderWithAccess()

            fireEvent.click(screen.getByRole("button", { name: "Access" }))
            fireEvent.click(
                screen.getByRole("link", { name: "Access Management" }),
            )

            expect(
                screen.getByRole("button", { name: "Access" }),
            ).toHaveAttribute("aria-expanded", "false")
        })

        it("closes the mobile navigation after choosing a child destination", () => {
            renderWithAccess()

            fireEvent.click(
                screen.getByRole("button", {
                    name: "Open campaign navigation",
                }),
            )

            const navigation = screen.getByRole("navigation", {
                name: "Campaign",
            })

            expect(navigation).toHaveClass("app-navigation--mobile-open")

            fireEvent.click(screen.getByRole("button", { name: "Access" }))
            fireEvent.click(
                screen.getByRole("link", { name: "Invitations" }),
            )

            expect(navigation).not.toHaveClass(
                "app-navigation--mobile-open",
            )
        })
    })

    it("collapses into an icon rail while preserving accessible link names", () => {
        renderNavigation()

        const navigation = screen.getByRole(
            "navigation",
            {
                name: "Campaign",
            },
        )

        const collapseButton =
            screen.getByRole("button", {
                name: "Collapse navigation",
            })

        expect(collapseButton).toHaveAttribute(
            "aria-expanded",
            "true",
        )

        expect(collapseButton).toHaveAttribute(
            "aria-controls",
            "campaign-navigation-list",
        )

        expect(navigation).not.toHaveClass(
            "app-navigation--collapsed",
        )

        fireEvent.click(collapseButton)

        expect(navigation).toHaveClass(
            "app-navigation--collapsed",
        )

        expect(
            screen.getByRole("button", {
                name: "Expand navigation",
            }),
        ).toHaveAttribute(
            "aria-expanded",
            "false",
        )

        // Collapsing changes only presentation. Navigation
        // destinations must remain available to assistive
        // technology and keyboard users.
        expect(
            within(navigation).getByRole(
                "link",
                {
                    name: "Campaign Home",
                },
            ),
        ).toBeInTheDocument()

        expect(
            within(navigation).getByRole(
                "link",
                {
                    name: "Knowledge",
                },
            ),
        ).toBeInTheDocument()
    })

    it("can expand again after being collapsed", () => {
        renderNavigation()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Collapse navigation",
            }),
        )

        fireEvent.click(
            screen.getByRole("button", {
                name: "Expand navigation",
            }),
        )

        expect(
            screen.getByRole("navigation", {
                name: "Campaign",
            }),
        ).not.toHaveClass(
            "app-navigation--collapsed",
        )

        expect(
            screen.getByRole("button", {
                name: "Collapse navigation",
            }),
        ).toHaveAttribute(
            "aria-expanded",
            "true",
        )
    })

    it("opens and closes the mobile navigation explicitly", () => {
        renderNavigation()

        const navigation = screen.getByRole(
            "navigation",
            {
                name: "Campaign",
            },
        )

        const openButton =
            screen.getByRole("button", {
                name: "Open campaign navigation",
            })

        expect(openButton).toHaveAttribute(
            "aria-expanded",
            "false",
        )

        expect(openButton).toHaveAttribute(
            "aria-controls",
            "campaign-navigation-list",
        )

        expect(navigation).not.toHaveClass(
            "app-navigation--mobile-open",
        )

        fireEvent.click(openButton)

        expect(navigation).toHaveClass(
            "app-navigation--mobile-open",
        )

        const closeButton =
            screen.getByRole("button", {
                name: "Close campaign navigation",
            })

        expect(closeButton).toHaveAttribute(
            "aria-expanded",
            "true",
        )

        fireEvent.click(closeButton)

        expect(navigation).not.toHaveClass(
            "app-navigation--mobile-open",
        )

        expect(
            screen.getByRole("button", {
                name: "Open campaign navigation",
            }),
        ).toHaveAttribute(
            "aria-expanded",
            "false",
        )
    })

    it("closes the mobile navigation after choosing a destination", () => {
        renderNavigation()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Open campaign navigation",
            }),
        )

        const navigation = screen.getByRole(
            "navigation",
            {
                name: "Campaign",
            },
        )

        expect(navigation).toHaveClass(
            "app-navigation--mobile-open",
        )

        fireEvent.click(
            within(navigation).getByRole("link", {
                name: "World",
            }),
        )

        expect(navigation).not.toHaveClass(
            "app-navigation--mobile-open",
        )

        expect(
            screen.getByRole("button", {
                name: "Open campaign navigation",
            }),
        ).toHaveAttribute(
            "aria-expanded",
            "false",
        )
    })

    it("closes the mobile navigation when Escape is pressed", () => {
        renderNavigation()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Open campaign navigation",
            }),
        )

        const navigation = screen.getByRole(
            "navigation",
            {
                name: "Campaign",
            },
        )

        expect(navigation).toHaveClass(
            "app-navigation--mobile-open",
        )

        fireEvent.keyDown(document, {
            key: "Escape",
        })

        expect(navigation).not.toHaveClass(
            "app-navigation--mobile-open",
        )
    })
})