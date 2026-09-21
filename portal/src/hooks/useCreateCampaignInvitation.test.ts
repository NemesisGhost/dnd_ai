import { act, renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { CampaignInvitationsRequestError } from "../api/campaignInvitations"
import { useCreateCampaignInvitation } from "./useCreateCampaignInvitation"

const { createCampaignInvitationMock, reloadMock, sessionStateRef } = vi.hoisted(() => ({
    createCampaignInvitationMock: vi.fn(),
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
        createCampaignInvitation: createCampaignInvitationMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    createCampaignInvitationMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useCreateCampaignInvitation", () => {
    it("submits successfully and reports the one-time token payload", async () => {
        const onSuccess = vi.fn()
        createCampaignInvitationMock.mockResolvedValue({
            campaign_invitation_id: "invitation-1",
            token: "raw-token",
        })

        const { result } = renderHook(() =>
            useCreateCampaignInvitation("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("player@example.com")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(createCampaignInvitationMock).toHaveBeenCalledWith(
            "campaign-a",
            "player@example.com",
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )
        expect(onSuccess).toHaveBeenCalledWith({
            campaign_invitation_id: "invitation-1",
            token: "raw-token",
        })
    })

    it("reuses the idempotency key across a retry for the same email label", async () => {
        createCampaignInvitationMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({
                campaign_invitation_id: "invitation-1",
                token: "raw-token",
            })

        const { result } = renderHook(() =>
            useCreateCampaignInvitation("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("player@example.com")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit("player@example.com")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })

        expect(createCampaignInvitationMock.mock.calls[1]?.[3]).toEqual(
            createCampaignInvitationMock.mock.calls[0]?.[3],
        )
    })

    it("maps a non-disclosing rejection to denied", async () => {
        createCampaignInvitationMock.mockRejectedValue(
            new CampaignInvitationsRequestError(403, "denied"),
        )

        const { result } = renderHook(() =>
            useCreateCampaignInvitation("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit(null)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })

    it("maps a 409 to conflict", async () => {
        createCampaignInvitationMock.mockRejectedValue(
            new CampaignInvitationsRequestError(409, "conflict"),
        )

        const { result } = renderHook(() =>
            useCreateCampaignInvitation("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit(null)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })
})
