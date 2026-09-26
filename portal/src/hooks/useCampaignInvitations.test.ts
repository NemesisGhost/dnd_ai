import { renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { CampaignInvitationsRequestError } from "../api/campaignInvitations"
import { useCampaignInvitations } from "./useCampaignInvitations"

const { fetchCampaignInvitationsMock, reloadMock } = vi.hoisted(() => ({
    fetchCampaignInvitationsMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock("../api/campaignInvitations", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/campaignInvitations")>()
    return {
        ...actual,
        fetchCampaignInvitations: fetchCampaignInvitationsMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: reloadMock }),
}))

beforeEach(() => {
    fetchCampaignInvitationsMock.mockReset()
    reloadMock.mockReset()
})

describe("useCampaignInvitations", () => {
    it("loads invitations successfully", async () => {
        fetchCampaignInvitationsMock.mockResolvedValue({
            invitations: [{
                campaign_invitation_id: "invitation-1",
                invited_email: null,
                invited_by_display_name: "GM",
                created_at: "2026-01-01T00:00:00Z",
                expires_at: "2026-01-08T00:00:00Z",
            }],
        })

        const { result } = renderHook(() => useCampaignInvitations("campaign-a"))

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                invitations: [{
                    campaign_invitation_id: "invitation-1",
                    invited_email: null,
                    invited_by_display_name: "GM",
                    created_at: "2026-01-01T00:00:00Z",
                    expires_at: "2026-01-08T00:00:00Z",
                }],
            })
        })
    })

    it("maps 403 and 404 to a denied state", async () => {
        fetchCampaignInvitationsMock.mockRejectedValue(
            new CampaignInvitationsRequestError(403, "denied"),
        )

        const { result } = renderHook(() => useCampaignInvitations("campaign-a"))

        await waitFor(() => {
            expect(result.current.state).toEqual({ status: "denied" })
        })
    })

    it("reloads the session on 401", async () => {
        fetchCampaignInvitationsMock.mockRejectedValue(
            new CampaignInvitationsRequestError(401, "unauthorized"),
        )

        renderHook(() => useCampaignInvitations("campaign-a"))

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
    })

    it("retries after a recoverable error", async () => {
        fetchCampaignInvitationsMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({ invitations: [] })

        const { result } = renderHook(() => useCampaignInvitations("campaign-a"))

        await waitFor(() => {
            expect(result.current.state.status).toBe("error")
        })

        result.current.retry()

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                invitations: [],
            })
        })
    })
})
