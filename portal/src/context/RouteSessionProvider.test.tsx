import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    MemoryRouter,
    useLocation,
    useNavigate,
} from "react-router"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { fetchSessionBootstrap } from "../api/session"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { AuthenticatedSessionBoundary } from "../layouts/AuthenticatedSessionBoundary"
import { RouteSessionProvider } from "./RouteSessionProvider"

vi.mock("../api/session", () => ({
    fetchSessionBootstrap: vi.fn(),
}))

const fetchSessionBootstrapMock =
    vi.mocked(fetchSessionBootstrap)

const bootstrap = {
    ...sessionBootstrapFixture,
    user: {
        ...sessionBootstrapFixture.user,
        display_name: "Authorized session content",
    },
}

function NavigationControls() {
    const navigate = useNavigate()
    const location = useLocation()

    return (
        <nav aria-label="Test navigation">
            <p data-testid="current-path">
                {location.pathname}
            </p>

            <button
                type="button"
                onClick={() => navigate("/app/campaign-a/world")}
            >
                World
            </button>

            <button
                type="button"
                onClick={() => navigate("/app/campaign-b/home")}
            >
                Campaign B
            </button>

            <button
                type="button"
                onClick={() => navigate("/campaigns")}
            >
                Campaigns
            </button>

            <button
                type="button"
                onClick={() => navigate(-1)}
            >
                Back
            </button>

            <button
                type="button"
                onClick={() => navigate(1)}
            >
                Forward
            </button>
        </nav>
    )
}

function renderPortal() {
    return render(
        <MemoryRouter
            initialEntries={["/app/campaign-a/home"]}
        >
            <NavigationControls />

            <RouteSessionProvider>
                <AuthenticatedSessionBoundary>
                    {(sessionBootstrap) => (
                        <p>{sessionBootstrap.user.display_name}</p>
                    )}
                </AuthenticatedSessionBoundary>
            </RouteSessionProvider>
        </MemoryRouter>,
    )
}

beforeEach(() => {
    fetchSessionBootstrapMock.mockReset()
    fetchSessionBootstrapMock.mockResolvedValue(bootstrap)
})

describe("RouteSessionProvider", () => {
    it("keeps the provider when navigating within the same campaign", async () => {
        renderPortal()

        await screen.findByText("Authorized session content")

        expect(
            fetchSessionBootstrapMock,
        ).toHaveBeenCalledTimes(1)

        fireEvent.click(
            screen.getByRole("button", { name: "World" }),
        )

        expect(
            screen.getByTestId("current-path"),
        ).toHaveTextContent("/app/campaign-a/world")

        expect(
            screen.getByText("Authorized session content"),
        ).toBeInTheDocument()

        expect(
            fetchSessionBootstrapMock,
        ).toHaveBeenCalledTimes(1)
    })

    it.each(["Campaign B", "Campaigns"])(
        "hides previous content and refreshes when navigating to %s",
        async (destination) => {
            fetchSessionBootstrapMock
                .mockResolvedValueOnce(bootstrap)
                .mockReturnValue(
                    new Promise<never>(() => undefined),
                )

            renderPortal()

            await screen.findByText("Authorized session content")

            fireEvent.click(
                screen.getByRole("button", {
                    name: destination,
                }),
            )

            expect(
                screen.getByRole("heading", {
                    name: "Loading portal",
                }),
            ).toBeInTheDocument()

            expect(
                screen.queryByText("Authorized session content"),
            ).not.toBeInTheDocument()

            expect(
                fetchSessionBootstrapMock,
            ).toHaveBeenCalledTimes(2)
        },
    )

    it("refreshes when Back and Forward change the campaign", async () => {
        renderPortal()

        await screen.findByText("Authorized session content")

        fireEvent.click(
            screen.getByRole("button", {
                name: "Campaign B",
            }),
        )

        await screen.findByText("Authorized session content")

        expect(
            screen.getByTestId("current-path"),
        ).toHaveTextContent("/app/campaign-b/home")

        expect(
            fetchSessionBootstrapMock,
        ).toHaveBeenCalledTimes(2)

        fireEvent.click(
            screen.getByRole("button", { name: "Back" }),
        )

        await screen.findByText("Authorized session content")

        expect(
            screen.getByTestId("current-path"),
        ).toHaveTextContent("/app/campaign-a/home")

        expect(
            fetchSessionBootstrapMock,
        ).toHaveBeenCalledTimes(3)

        fireEvent.click(
            screen.getByRole("button", { name: "Forward" }),
        )

        await screen.findByText("Authorized session content")

        expect(
            screen.getByTestId("current-path"),
        ).toHaveTextContent("/app/campaign-b/home")

        expect(
            fetchSessionBootstrapMock,
        ).toHaveBeenCalledTimes(4)
    })
})