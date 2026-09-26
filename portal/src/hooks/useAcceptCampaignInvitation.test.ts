import { act, renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { CampaignInvitationsRequestError } from "../api/campaignInvitations"
import { useAcceptCampaignInvitation } from "./useAcceptCampaignInvitation"

const { acceptCampaignInvitationMock, reloadMock, sessionStateRef } = vi.hoisted(() => ({
    acceptCampaignInvitationMock: vi.fn(),
    reloadMock: vi.fn(),
    sessionStateRef: {
        current: {
            status: "authenticated" as const,
            bootstrap: { csrf_token: "fixture-csrf-token" },
        },
    },
}))

vi.mock("../api/campaignInvitations", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/campaignInvitations")>()
    return {
        ...actual,
        acceptCampaignInvitation: acceptCampaignInvitationMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    acceptCampaignInvitationMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useAcceptCampaignInvitation", () => {
    it("accepts successfully and reloads bootstrap", async () => {
        const onSuccess = vi.fn()
        acceptCampaignInvitationMock.mockResolvedValue({
            campaign_id: "campaign-1",
            campaign_membership_id: "membership-1",
        })

        const { result } = renderHook(() => useAcceptCampaignInvitation(onSuccess))

        act(() => {
            result.current.submit("raw-token")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledWith({
            campaign_id: "campaign-1",
            campaign_membership_id: "membership-1",
        })
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("maps a generic rejection to unacceptable", async () => {
        acceptCampaignInvitationMock.mockRejectedValue(
            new CampaignInvitationsRequestError(404, "not acceptable"),
        )

        const { result } = renderHook(() => useAcceptCampaignInvitation(vi.fn()))

        act(() => {
            result.current.submit("raw-token")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "unacceptable" })
        })
    })

    it("maps a 403 to denied", async () => {
        acceptCampaignInvitationMock.mockRejectedValue(
            new CampaignInvitationsRequestError(403, "denied"),
        )

        const { result } = renderHook(() => useAcceptCampaignInvitation(vi.fn()))

        act(() => {
            result.current.submit("raw-token")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })
})
