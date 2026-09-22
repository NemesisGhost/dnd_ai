import { act, renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { CampaignInvitationsRequestError } from "../api/campaignInvitations"
import { useRevokeCampaignInvitation } from "./useRevokeCampaignInvitation"

const { revokeCampaignInvitationMock, reloadMock, sessionStateRef } = vi.hoisted(() => ({
    revokeCampaignInvitationMock: vi.fn(),
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
        revokeCampaignInvitation: revokeCampaignInvitationMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    revokeCampaignInvitationMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useRevokeCampaignInvitation", () => {
    it("submits successfully and reloads the session", async () => {
        const onSuccess = vi.fn()
        revokeCampaignInvitationMock.mockResolvedValue({
            campaign_invitation_id: "invitation-1",
        })

        const { result } = renderHook(() =>
            useRevokeCampaignInvitation("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("invitation-1")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("reuses the idempotency key across a retry for the same invitation", async () => {
        revokeCampaignInvitationMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({ campaign_invitation_id: "invitation-1" })

        const { result } = renderHook(() =>
            useRevokeCampaignInvitation("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("invitation-1")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit("invitation-1")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })

        expect(revokeCampaignInvitationMock.mock.calls[1]?.[3]).toEqual(
            revokeCampaignInvitationMock.mock.calls[0]?.[3],
        )
    })

    it("maps 409 to conflict", async () => {
        revokeCampaignInvitationMock.mockRejectedValue(
            new CampaignInvitationsRequestError(409, "conflict"),
        )

        const { result } = renderHook(() =>
            useRevokeCampaignInvitation("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("invitation-1")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })
})
