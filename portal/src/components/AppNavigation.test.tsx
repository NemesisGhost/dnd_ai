import {
    fireEvent,
    render,
    screen,
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
            ["Home", "/app/campaign-a/home"],
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

        expect(
            within(navigation).getByText("Ask"),
        ).toHaveAttribute(
            "aria-disabled",
            "true",
        )
    })

    it("shows capability-dependent destinations only when authorized", () => {
        const { rerender } = renderNavigation({
            showAccess: false,
        })

        expect(
            screen.queryByRole("link", {
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
            screen.getByRole("link", {
                name: "Access",
            }),
        ).toHaveAttribute(
            "href",
            "/app/campaign-a/access",
        )
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
                    name: "Home",
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
})