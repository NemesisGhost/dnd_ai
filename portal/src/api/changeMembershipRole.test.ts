import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import {
    ChangeMembershipRoleRequestError,
    changeMembershipRole,
} from "./changeMembershipRole"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("changeMembershipRole", () => {
    it("posts to the campaign-scoped change-role route with the CSRF header, Idempotency-Key header, JSON body, and same-origin credentials", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    membership_role_id: "new-membership-role",
                }),
                {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            changeMembershipRole(
                "campaign/a b",
                "membership-role/1",
                "role-2",
                "fixture-csrf-token",
                "fixture-idempotency-key",
                controller.signal,
            ),
        ).resolves.toEqual({
            membership_role_id: "new-membership-role",
        })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/memberships/roles/membership-role%2F1/change",
            {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                signal: controller.signal,
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-CSRF-Token": "fixture-csrf-token",
                    "Idempotency-Key": "fixture-idempotency-key",
                },
                body: JSON.stringify({ new_role_id: "role-2" }),
            },
        )
    })

    it("passes no signal when the caller supplies none", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    membership_role_id: "new-membership-role",
                }),
                {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await changeMembershipRole(
            "campaign-a",
            "membership-role-a",
            "role-b",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        expect(fetchMock).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ signal: undefined }),
        )
    })

    it("throws a typed error for an unauthenticated response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 401 })),
        )

        const request = changeMembershipRole(
            "campaign-a",
            "membership-role-a",
            "role-b",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toBeInstanceOf(
            ChangeMembershipRoleRequestError,
        )
        await expect(request).rejects.toMatchObject({
            name: "ChangeMembershipRoleRequestError",
            status: 401,
        })
    })

    it("throws the same typed error shape for a non-disclosing forbidden/not-found response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        const request = changeMembershipRole(
            "campaign-a",
            "membership-role-a",
            "role-b",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "ChangeMembershipRoleRequestError",
            status: 404,
        })
    })

    it("throws a typed error for a conflicting concurrent change", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 409 })),
        )

        const request = changeMembershipRole(
            "campaign-a",
            "membership-role-a",
            "role-b",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "ChangeMembershipRoleRequestError",
            status: 409,
        })
    })

    it("throws a typed error for a validation failure", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 422 })),
        )

        const request = changeMembershipRole(
            "campaign-a",
            "membership-role-a",
            "role-b",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "ChangeMembershipRoleRequestError",
            status: 422,
        })
    })

    it("throws a typed error for a recoverable server failure", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 500 })),
        )

        const request = changeMembershipRole(
            "campaign-a",
            "membership-role-a",
            "role-b",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "ChangeMembershipRoleRequestError",
            status: 500,
        })
    })

    it("propagates an abort so callers can distinguish it from a request failure", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockImplementation(
            (_input: RequestInfo | URL, init?: RequestInit) =>
                new Promise((_resolve, reject) => {
                    init?.signal?.addEventListener("abort", () => {
                        reject(new DOMException("Aborted", "AbortError"))
                    })
                }),
        )
        vi.stubGlobal("fetch", fetchMock)

        const request = changeMembershipRole(
            "campaign-a",
            "membership-role-a",
            "role-b",
            "fixture-csrf-token",
            "fixture-idempotency-key",
            controller.signal,
        )

        controller.abort()

        await expect(request).rejects.toMatchObject({
            name: "AbortError",
        })
    })
})
