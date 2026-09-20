import {
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
import type {
    CampaignAccessOverview,
} from "../types/accessOverview"
import {
    AccessOverviewBoundary,
} from "./AccessOverviewBoundary"

const {
    retryMock,
    useAccessOverviewMock,
} = vi.hoisted(() => ({
    retryMock: vi.fn(),
    useAccessOverviewMock: vi.fn(),
}))

vi.mock("../hooks/useAccessOverview", () => ({
    useAccessOverview: useAccessOverviewMock,
}))

const overviewFixture: CampaignAccessOverview = {
    members: [
        {
            campaign_membership_id: "membership-a",
            user_id: "user-a",
            display_name: "Player One",
            status_code: "active",
            status_display_name: "Active",
            joined_at: "2026-01-01T00:00:00Z",
            account_is_active: true,
            roles: [],
            character_relationships: [],
            grants: [],
        },
    ],
    assignable_roles: [],
    assignable_characters: [],
    assignable_relationship_types: [],
    grantable_resource_capabilities: [],
    access_groups: [],
}

function renderBoundary() {
    render(
        <AccessOverviewBoundary campaignId="campaign-a">
            {(overview, retry) => (
                <ul>
                    {overview.members.map((member) => (
                        <li key={member.campaign_membership_id}>
                            {member.display_name}
                        </li>
                    ))}
                    <li>
                        <button
                            type="button"
                            onClick={retry}
                        >
                            Refresh
                        </button>
                    </li>
                </ul>
            )}
        </AccessOverviewBoundary>,
    )
}

beforeEach(() => {
    retryMock.mockReset()
    useAccessOverviewMock.mockReset()
})

describe("AccessOverviewBoundary", () => {
    it("shows loading without rendering member content", () => {
        useAccessOverviewMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Loading access",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("Player One"),
        ).not.toBeInTheDocument()

        expect(
            useAccessOverviewMock,
        ).toHaveBeenCalledWith("campaign-a")
    })

    it("shows a non-disclosing unavailable state", () => {
        useAccessOverviewMock.mockReturnValue({
            state: {
                status: "unavailable",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Access unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "The requested access information is not available.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("Player One"),
        ).not.toBeInTheDocument()
    })

    it("shows a safe recoverable error and retries", () => {
        const diagnosticError = new Error(
            "Database connection failed for internal host",
        )

        useAccessOverviewMock.mockReturnValue({
            state: {
                status: "error",
                error: diagnosticError,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Access information unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(diagnosticError.message),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText("Player One"),
        ).not.toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Try again",
            }),
        )

        expect(retryMock).toHaveBeenCalledTimes(1)
    })

    it("renders the authorized overview after a successful request", () => {
        useAccessOverviewMock.mockReturnValue({
            state: {
                status: "success",
                overview: overviewFixture,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByText("Player One"),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("button", {
                name: "Try again",
            }),
        ).not.toBeInTheDocument()
    })

    it("passes the hook's retry function through to the success-state children", () => {
        useAccessOverviewMock.mockReturnValue({
            state: {
                status: "success",
                overview: overviewFixture,
            },
            retry: retryMock,
        })

        renderBoundary()

        fireEvent.click(
            screen.getByRole("button", { name: "Refresh" }),
        )

        expect(retryMock).toHaveBeenCalledTimes(1)
    })
})
