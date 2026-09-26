import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import {
    acceptCampaignInvitation,
    CampaignInvitationsRequestError,
    createCampaignInvitation,
    fetchCampaignInvitations,
    revokeCampaignInvitation,
} from "./campaignInvitations"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("campaign invitation API", () => {
    it("fetches the pending invitation list", async () => {
        const controller = new AbortController()
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({ invitations: [] }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchCampaignInvitations("campaign/a b", controller.signal),
        ).resolves.toEqual({ invitations: [] })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/invitations",
            {
                method: "GET",
                cache: "no-store",
                signal: controller.signal,
                headers: { Accept: "application/json" },
            },
        )
    })

    it("posts invitation creation with csrf, idempotency, same-origin credentials, and JSON body", async () => {
        const controller = new AbortController()
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    campaign_invitation_id: "invitation-1",
                    token: "raw-token",
                }),
                {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            createCampaignInvitation(
                "campaign/a b",
                "player@example.com",
                "csrf-token",
                "idempotency-key",
                controller.signal,
            ),
        ).resolves.toEqual({
            campaign_invitation_id: "invitation-1",
            token: "raw-token",
        })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/invitations",
            {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                signal: controller.signal,
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-CSRF-Token": "csrf-token",
                    "Idempotency-Key": "idempotency-key",
                },
                body: JSON.stringify({ invited_email: "player@example.com" }),
            },
        )
    })

    it("posts invitation revocation with csrf and idempotency headers", async () => {
        const controller = new AbortController()
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({ campaign_invitation_id: "invitation-1" }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            revokeCampaignInvitation(
                "campaign/a b",
                "invitation/1",
                "csrf-token",
                "idempotency-key",
                controller.signal,
            ),
        ).resolves.toEqual({ campaign_invitation_id: "invitation-1" })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/invitations/invitation%2F1/revoke",
            {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                signal: controller.signal,
                headers: {
                    Accept: "application/json",
                    "X-CSRF-Token": "csrf-token",
                    "Idempotency-Key": "idempotency-key",
                },
            },
        )
    })

    it("posts invitation acceptance in the request body only", async () => {
        const controller = new AbortController()
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    campaign_id: "campaign-1",
                    campaign_membership_id: "membership-1",
                }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            acceptCampaignInvitation("raw-token", "csrf-token", controller.signal),
        ).resolves.toEqual({
            campaign_id: "campaign-1",
            campaign_membership_id: "membership-1",
        })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaign-invitations/accept",
            {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                signal: controller.signal,
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-CSRF-Token": "csrf-token",
                },
                body: JSON.stringify({ token: "raw-token" }),
            },
        )
    })

    it("throws a typed request error for a non-disclosing rejection", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        await expect(fetchCampaignInvitations("campaign-a")).rejects.toMatchObject({
            name: "CampaignInvitationsRequestError",
            status: 404,
        } satisfies Partial<CampaignInvitationsRequestError>)
    })

    it("propagates aborts from invitation acceptance", async () => {
        const controller = new AbortController()
        vi.stubGlobal(
            "fetch",
            vi.fn().mockImplementation(
                (_input: RequestInfo | URL, init?: RequestInit) =>
                    new Promise((_resolve, reject) => {
                        init?.signal?.addEventListener("abort", () => {
                            reject(new DOMException("Aborted", "AbortError"))
                        })
                    }),
            ),
        )

        const request = acceptCampaignInvitation(
            "raw-token",
            "csrf-token",
            controller.signal,
        )
        controller.abort()

        await expect(request).rejects.toMatchObject({ name: "AbortError" })
    })
})
