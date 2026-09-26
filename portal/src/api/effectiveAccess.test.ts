import { afterEach, describe, expect, it, vi } from "vitest"
import type { MemberEffectiveAccess } from "../types/effectiveAccess"
import { EffectiveAccessRequestError, fetchMemberEffectiveAccess } from "./effectiveAccess"

const accessFixture: MemberEffectiveAccess = {
    display_name: "Player One",
    capabilities: [
        {
            code: "campaign.view",
            display_name: "View Campaign",
            sources: [{ kind: "role", label: "Player", target_display_name: null }],
        },
    ],
    denials: [],
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchMemberEffectiveAccess", () => {
    it("requests the member-scoped effective access and returns the typed response", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(accessFixture), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchMemberEffectiveAccess("campaign/a b", "membership/c d", controller.signal),
        ).resolves.toEqual(accessFixture)

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/members/membership%2Fc%20d/effective-access",
            {
                method: "GET",
                headers: { Accept: "application/json" },
                cache: "no-store",
                signal: controller.signal,
            },
        )
    })

    it("passes no signal when the caller supplies none", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(accessFixture), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(fetchMemberEffectiveAccess("campaign-a", "membership-a")).resolves.toEqual(
            accessFixture,
        )

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/members/membership-a/effective-access",
            {
                method: "GET",
                headers: { Accept: "application/json" },
                cache: "no-store",
                signal: undefined,
            },
        )
    })

    it("throws a typed error carrying the response status for a failed request", async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 404 }))

        vi.stubGlobal("fetch", fetchMock)

        await expect(fetchMemberEffectiveAccess("campaign-a", "membership-a")).rejects.toSatisfy(
            (error: unknown) =>
                error instanceof EffectiveAccessRequestError && error.status === 404,
        )
    })
})
