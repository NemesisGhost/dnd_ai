import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    MemoryRouter,
    Route,
    Routes,
} from "react-router"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { SessionContext } from "../context/SessionContext"
import type { SessionBootstrapState } from "../hooks/useSessionBootstrap"
import type { AcceptCampaignInvitationStatus } from "../hooks/useAcceptCampaignInvitation"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { AcceptCampaignInvitationPage } from "./AcceptCampaignInvitationPage"

const { acceptHookRef, acceptSuccessRef, reloadMock } = vi.hoisted(() => ({
    acceptHookRef: {
        current: {
            status: { kind: "idle" as AcceptCampaignInvitationStatus["kind"] },
            submit: vi.fn(),
            reset: vi.fn(),
        },
    },
    acceptSuccessRef: {
        current: null as null | ((result: { campaign_id: string; campaign_membership_id: string }) => void),
    },
    reloadMock: vi.fn(),
}))

vi.mock("../hooks/useAcceptCampaignInvitation", () => ({
    useAcceptCampaignInvitation: (
        onSuccess: (result: { campaign_id: string; campaign_membership_id: string }) => void,
    ) => {
        acceptSuccessRef.current = onSuccess
        return acceptHookRef.current
    },
}))

beforeEach(() => {
    acceptHookRef.current = {
        status: { kind: "idle" },
        submit: vi.fn(),
        reset: vi.fn(),
    }
    acceptSuccessRef.current = null
    reloadMock.mockReset()
})

function renderPage(sessionState: SessionBootstrapState) {
    return render(
        <SessionContext.Provider
            value={{
                state: sessionState,
                reload: reloadMock,
            }}
        >
            <MemoryRouter initialEntries={["/campaign-invitations/accept"]}>
                <Routes>
                    <Route
                        path="/campaign-invitations/accept"
                        element={<AcceptCampaignInvitationPage />}
                    />
                    <Route path="/login" element={<p>Login page</p>} />
                </Routes>
            </MemoryRouter>
        </SessionContext.Provider>,
    )
}

describe("AcceptCampaignInvitationPage", () => {
    it("redirects unauthenticated sessions to login", async () => {
        renderPage({ status: "unauthenticated" })

        expect(await screen.findByText("Login page")).toBeInTheDocument()
    })

    it("renders a secret-appropriate token input and submits the request body token", () => {
        renderPage({
            status: "authenticated",
            bootstrap: sessionBootstrapFixture,
        })

        const input = screen.getByLabelText("Invitation token")
        expect(input).toHaveAttribute("type", "password")
        expect(input).toHaveAttribute("autocomplete", "off")
        expect(input).toHaveAttribute("spellcheck", "false")

        fireEvent.change(input, { target: { value: "raw-token" } })
        fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }))

        expect(acceptHookRef.current.submit).toHaveBeenCalledWith("raw-token")
    })

    it("shows a generic unacceptable-token failure", async () => {
        acceptHookRef.current = {
            status: { kind: "unacceptable" },
            submit: vi.fn(),
            reset: vi.fn(),
        }

        renderPage({
            status: "authenticated",
            bootstrap: sessionBootstrapFixture,
        })

        expect(
            await screen.findByText(/could not be accepted/i),
        ).toBeInTheDocument()
    })

    it("shows the post-acceptance success guidance without auto-navigation", async () => {
        renderPage({
            status: "authenticated",
            bootstrap: sessionBootstrapFixture,
        })

        acceptSuccessRef.current?.({
            campaign_id: "campaign-1",
            campaign_membership_id: "membership-1",
        })

        expect(
            await screen.findByRole("heading", { name: "Invitation accepted" }),
        ).toBeInTheDocument()
        expect(
            screen.getByText(/gm may still need to assign a role or additional access/i),
        ).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Go to campaigns" })).toHaveAttribute(
            "href",
            "/campaigns",
        )
    })

    it("shows a session-error placeholder when session loading failed", () => {
        renderPage({ status: "error", error: new Error("boom") })

        expect(
            screen.getByRole("heading", { name: "Invitation acceptance unavailable" }),
        ).toBeInTheDocument()
    })
})
