import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { addCharacterRelationship } from "./addCharacterRelationship"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("addCharacterRelationship", () => {
    it("posts to the campaign-scoped character-relationships route with the CSRF header, Idempotency-Key header, JSON body, and same-origin credentials", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    membership_character_relationship_id: "new-relationship",
                }),
                {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            addCharacterRelationship(
                "campaign/a b",
                "membership/1",
                "character-2",
                "viewer",
                "fixture-csrf-token",
                "fixture-idempotency-key",
                controller.signal,
            ),
        ).resolves.toEqual({
            membership_character_relationship_id: "new-relationship",
        })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/memberships/membership%2F1/character-relationships",
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
                body: JSON.stringify({
                    character_id: "character-2",
                    relationship_type_code: "viewer",
                }),
            },
        )
    })

    it("throws a typed error for a non-disclosing forbidden/not-found response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        const request = addCharacterRelationship(
            "campaign-a",
            "membership-a",
            "character-a",
            "viewer",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "AddCharacterRelationshipRequestError",
            status: 404,
        })
    })

    it("throws a typed error for a conflicting duplicate/ineligible target", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 409 })),
        )

        const request = addCharacterRelationship(
            "campaign-a",
            "membership-a",
            "character-a",
            "viewer",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "AddCharacterRelationshipRequestError",
            status: 409,
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

        const request = addCharacterRelationship(
            "campaign-a",
            "membership-a",
            "character-a",
            "viewer",
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
