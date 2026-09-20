import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { changeCharacterRelationship } from "./changeCharacterRelationship"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("changeCharacterRelationship", () => {
    it("posts to the campaign-scoped change route with the CSRF header, Idempotency-Key header, JSON body, and same-origin credentials", async () => {
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
            changeCharacterRelationship(
                "campaign/a b",
                "relationship/1",
                "type-2",
                "fixture-csrf-token",
                "fixture-idempotency-key",
                controller.signal,
            ),
        ).resolves.toEqual({
            membership_character_relationship_id: "new-relationship",
        })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/character-relationships/relationship%2F1/change",
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
                body: JSON.stringify({ new_relationship_type_id: "type-2" }),
            },
        )
    })

    it("throws a typed error for a non-disclosing forbidden/not-found response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        const request = changeCharacterRelationship(
            "campaign-a",
            "relationship-a",
            "type-b",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "ChangeCharacterRelationshipRequestError",
            status: 404,
        })
    })

    it("throws a typed error for a no-op change (unchanged type)", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 422 })),
        )

        const request = changeCharacterRelationship(
            "campaign-a",
            "relationship-a",
            "type-b",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "ChangeCharacterRelationshipRequestError",
            status: 422,
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

        const request = changeCharacterRelationship(
            "campaign-a",
            "relationship-a",
            "type-b",
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
