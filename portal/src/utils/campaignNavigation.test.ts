import { describe, expect, it } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { CampaignContext } from "../types/bootstrap"
import { buildCampaignSelectionPath } from "./campaignNavigation"

const fixtureCampaign =
    sessionBootstrapFixture.campaigns[0]

if (fixtureCampaign === undefined) {
    throw new Error(
        "The session bootstrap fixture must contain a campaign",
    )
}

const targetCampaign = {
    ...fixtureCampaign,
    campaign_id: "campaign-b",
    capabilities: [],
} satisfies CampaignContext

function buildPath(
    pathname: string,
    campaign: CampaignContext = targetCampaign,
    askEnabled = false,
): string {
    return buildCampaignSelectionPath({
        pathname,
        targetCampaign: campaign,
        askEnabled,
    })
}

describe("buildCampaignSelectionPath", () => {
    it.each([
        "home",
        "world",
        "characters",
        "quests",
        "sessions",
        "knowledge",
    ])(
        "preserves the %s section",
        (section) => {
            expect(
                buildPath(`/app/campaign-a/${section}`),
            ).toBe(`/app/campaign-b/${section}`)
        },
    )

    it("drops an entity detail id", () => {
        expect(
            buildPath(
                "/app/campaign-a/quests/quest-123",
            ),
        ).toBe("/app/campaign-b/quests")
    })

    it("falls back to home for an unknown section", () => {
        expect(
            buildPath(
                "/app/campaign-a/not-a-real-section",
            ),
        ).toBe("/app/campaign-b/home")
    })

    it("falls back to home when no section exists", () => {
        expect(
            buildPath("/app/campaign-a"),
        ).toBe("/app/campaign-b/home")
    })

    it("preserves Access when the target campaign grants access management", () => {
        const administrativeCampaign = {
            ...targetCampaign,
            capabilities: ["access.manage"],
        } satisfies CampaignContext

        expect(
            buildPath(
                "/app/campaign-a/access",
                administrativeCampaign,
            ),
        ).toBe("/app/campaign-b/access")
    })

    it("does not preserve Access without the target capability", () => {
        expect(
            buildPath("/app/campaign-a/access"),
        ).toBe("/app/campaign-b/home")
    })

    it("preserves Ask when the server enables it", () => {
        expect(
            buildPath(
                "/app/campaign-a/ask",
                targetCampaign,
                true,
            ),
        ).toBe("/app/campaign-b/ask")
    })

    it("does not preserve Ask while the feature is disabled", () => {
        expect(
            buildPath(
                "/app/campaign-a/ask",
                targetCampaign,
                false,
            ),
        ).toBe("/app/campaign-b/home")
    })
})