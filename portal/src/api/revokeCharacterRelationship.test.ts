import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { revokeCharacterRelationship } from "./revokeCharacterRelationship"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("revokeCharacterRelationship", () => {
    it("posts to the campaign-scoped revoke route with the CSRF header, Idempotency-Key header, and same-origin credentials, no body", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    membership_character_relationship_id: "relationship-1",
                }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            revokeCharacterRelationship(
                "campaign/a b",
                "relationship/1",
                "fixture-csrf-token",
                "fixture-idempotency-key",
                controller.signal,
            ),
        ).resolves.toEqual({
            membership_character_relationship_id: "relationship-1",
        })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/character-relationships/relationship%2F1/revoke",
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

    it("throws a typed error for a non-disclosing forbidden/not-found response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        const request = revokeCharacterRelationship(
            "campaign-a",
            "relationship-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "RevokeCharacterRelationshipRequestError",
            status: 404,
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

        const request = revokeCharacterRelationship(
            "campaign-a",
            "relationship-a",
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
