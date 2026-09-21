import {
    act,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react"
import { useState } from "react"
import {
    afterEach,
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { InvitationsSection } from "./InvitationsSection"

const { invitationsStateRef, retryMock, createHookRef, createSuccessRef, revokeHookRef } = vi.hoisted(() => ({
    invitationsStateRef: {
        current: {
            status: "success" as const,
            invitations: [
                {
                    campaign_invitation_id: "11111111-1111-1111-1111-111111111111",
                    invited_email: null,
                    invited_by_display_name: "Aria the GM",
                    created_at: "2026-01-01T00:00:00Z",
                    expires_at: "2026-01-08T00:00:00Z",
                },
            ],
        },
    },
    retryMock: vi.fn(),
    createHookRef: {
        current: {
            status: { kind: "idle" as const },
            submit: vi.fn(),
            reset: vi.fn(),
        },
    },
    createSuccessRef: {
        current: null as null | ((result: { campaign_invitation_id: string; token: string }) => void),
    },
    revokeHookRef: {
        current: {
            status: { kind: "idle" as const },
            submit: vi.fn(),
            reset: vi.fn(),
        },
    },
}))

vi.mock("../hooks/useCampaignInvitations", () => ({
    useCampaignInvitations: () => ({
        state: invitationsStateRef.current,
        retry: retryMock,
    }),
}))

vi.mock("../hooks/useCreateCampaignInvitation", () => ({
    useCreateCampaignInvitation: (
        campaignId: string,
        onSuccess: (result: { campaign_invitation_id: string; token: string }) => void,
    ) => {
        void campaignId
        createSuccessRef.current = onSuccess
        return createHookRef.current
    },
}))

vi.mock("../hooks/useRevokeCampaignInvitation", () => ({
    useRevokeCampaignInvitation: (campaignId: string, onSuccess: () => void) => {
        void campaignId
        void onSuccess
        return revokeHookRef.current
    },
}))

afterEach(() => {
    vi.unstubAllGlobals()
})

beforeEach(() => {
    retryMock.mockReset()
    createHookRef.current = {
        status: { kind: "idle" },
        submit: vi.fn(),
        reset: vi.fn(),
    }
    createSuccessRef.current = null
    revokeHookRef.current = {
        status: { kind: "idle" },
        submit: vi.fn(),
        reset: vi.fn(),
    }
    invitationsStateRef.current = {
        status: "success",
        invitations: [
            {
                campaign_invitation_id: "11111111-1111-1111-1111-111111111111",
                invited_email: null,
                invited_by_display_name: "Aria the GM",
                created_at: "2026-01-01T00:00:00Z",
                expires_at: "2026-01-08T00:00:00Z",
            },
        ],
    }
})

function renderSection() {
    function Wrapper() {
        const [issuedToken, setIssuedToken] = useState<string | null>(null)

        return (
            <InvitationsSection
                campaignId="campaign-a"
                onChanged={vi.fn()}
                onMutationStart={vi.fn()}
                issuedToken={issuedToken}
                onIssuedTokenChange={setIssuedToken}
            />
        )
    }

    return render(
        <Wrapper />,
    )
}

describe("InvitationsSection", () => {
    it("renders the list without showing raw invitation ids as text", () => {
        const { container } = renderSection()

        expect(screen.getByRole("heading", { name: "Invitations" })).toBeInTheDocument()
        expect(screen.getByText("No email label")).toBeInTheDocument()
        expect(container.textContent).not.toContain("11111111-1111-1111-1111-111111111111")
    })

    it("submits the optional email label and explains that it is not binding", () => {
        renderSection()

        expect(
            screen.getByText(/does not bind the token to any account/i),
        ).toBeInTheDocument()

        fireEvent.change(screen.getByLabelText("Optional email label"), {
            target: { value: "player@example.com" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Issue invitation" }))

        expect(createHookRef.current.submit).toHaveBeenCalledWith("player@example.com")
    })

    it("shows the one-time token panel and clears it on dismissal", async () => {
        const clipboardWriteText = vi.fn().mockResolvedValue(undefined)
        vi.stubGlobal("navigator", { clipboard: { writeText: clipboardWriteText } })

        renderSection()

        const successResult = {
            campaign_invitation_id: "invitation-2",
            token: "raw-token-2",
        }
        await act(async () => {
            createSuccessRef.current?.(successResult)
        })

        expect(screen.getByDisplayValue("raw-token-2")).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Copy token" }))

        await waitFor(() => {
            expect(clipboardWriteText).toHaveBeenCalledWith("raw-token-2")
        })

        fireEvent.click(screen.getByRole("button", { name: "Dismiss token" }))

        expect(screen.queryByDisplayValue("raw-token-2")).not.toBeInTheDocument()
    })

    it("does not use browser storage or the URL when handling the one-time token", () => {
        const localSetItem = vi.fn()
        const sessionSetItem = vi.fn()
        Object.defineProperty(window, "localStorage", {
            value: { setItem: localSetItem },
            configurable: true,
        })
        Object.defineProperty(window, "sessionStorage", {
            value: { setItem: sessionSetItem },
            configurable: true,
        })

        renderSection()
        act(() => {
            createSuccessRef.current?.({
                campaign_invitation_id: "invitation-2",
                token: "raw-token-2",
            })
        })

        expect(localSetItem).not.toHaveBeenCalled()
        expect(sessionSetItem).not.toHaveBeenCalled()
        expect(window.location.search).toBe("")
        expect(window.location.hash).toBe("")
    })

    it("moves focus into revoke confirmation and restores it on cancel", async () => {
        renderSection()

        const trigger = screen.getByRole("button", { name: "Revoke" })
        fireEvent.click(trigger)

        const confirm = await screen.findByRole("button", { name: "Confirm" })
        await waitFor(() => {
            expect(confirm).toHaveFocus()
        })

        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))

        await waitFor(() => {
            expect(screen.getByRole("button", { name: "Revoke" })).toHaveFocus()
        })
    })
})
