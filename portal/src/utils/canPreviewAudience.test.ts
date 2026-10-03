import { describe, expect, it } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { canPreviewAudience } from "./canPreviewAudience"

describe("canPreviewAudience", () => {
    it("is false when the session is not authenticated", () => {
        expect(
            canPreviewAudience({ status: "unauthenticated" }, "campaign-one"),
        ).toBe(false)
    })

    it("is false when authenticated but the campaign membership has no access.manage capability", () => {
        expect(
            canPreviewAudience(
                {
                    status: "authenticated",
                    bootstrap: {
                        ...sessionBootstrapFixture,
                        campaigns: sessionBootstrapFixture.campaigns.map((campaign) => ({
                            ...campaign,
                            capabilities: ["campaign.view"],
                        })),
                    },
                },
                "campaign-one",
            ),
        ).toBe(false)
    })

    it("is true when the membership carries access.manage for that campaign", () => {
        expect(
            canPreviewAudience(
                { status: "authenticated", bootstrap: sessionBootstrapFixture },
                sessionBootstrapFixture.campaigns[0].campaign_id,
            ),
        ).toBe(true)
    })

    it("is false for a campaign the session has no membership in at all", () => {
        expect(
            canPreviewAudience(
                { status: "authenticated", bootstrap: sessionBootstrapFixture },
                "some-other-campaign",
            ),
        ).toBe(false)
    })
})
