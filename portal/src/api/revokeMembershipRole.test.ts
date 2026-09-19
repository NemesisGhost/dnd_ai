import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { revokeMembershipRole } from "./revokeMembershipRole"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("revokeMembershipRole", () => {
    it("posts to the campaign-scoped revoke route with the CSRF header, Idempotency-Key header, and same-origin credentials, no body", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    membership_role_id: "membership-role/1",
                }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            revokeMembershipRole(
                "campaign/a b",
                "membership-role/1",
                "fixture-csrf-token",
                "fixture-idempotency-key",
                controller.signal,
            ),
        ).resolves.toEqual({
            membership_role_id: "membership-role/1",
        })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/memberships/roles/membership-role%2F1/revoke",
            {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                signal: controller.signal,
                headers: {
                    Accept: "application/json",
                    "X-CSRF-Token": "fixture-csrf-token",
                    "Idempotency-Key": "fixture-idempotency-key",
                },
            },
        )
    })

    it("passes no signal when the caller supplies none", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                new Response(
                    JSON.stringify({ membership_role_id: "r" }),
                    {
                        status: 200,
                        headers: { "Content-Type": "application/json" },
                    },
                ),
            ),
        )

        await revokeMembershipRole(
            "campaign-a",
            "membership-role-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        expect(fetch).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ signal: undefined }),
        )
    })

    it("throws a typed error for an unauthenticated response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 401 })),
        )

        const request = revokeMembershipRole(
            "campaign-a",
            "membership-role-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "RevokeMembershipRoleRequestError",
            status: 401,
        })
    })

    it("throws the same typed error shape for a non-disclosing forbidden/not-found response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        const request = revokeMembershipRole(
            "campaign-a",
            "membership-role-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "RevokeMembershipRoleRequestError",
            status: 404,
        })
    })

    it("throws a typed error for a conflicting idempotency-key reuse", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 409 })),
        )

        const request = revokeMembershipRole(
            "campaign-a",
            "membership-role-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "RevokeMembershipRoleRequestError",
            status: 409,
        })
    })

    it("throws a typed error for a recoverable server failure", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 500 })),
        )

        const request = revokeMembershipRole(
            "campaign-a",
            "membership-role-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "RevokeMembershipRoleRequestError",
            status: 500,
        })
    })

    it("propagates an abort so callers can distinguish it from a request failure", async () => {
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

        const request = revokeMembershipRole(
            "campaign-a",
            "membership-role-a",
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
