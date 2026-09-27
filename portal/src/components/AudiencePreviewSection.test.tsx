import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { AudiencePreviewSection } from "./AudiencePreviewSection"

const { accessOverviewStateRef } = vi.hoisted(() => ({
    accessOverviewStateRef: { current: { status: "loading" } as Record<string, unknown> },
}))

vi.mock("../hooks/useAccessOverview", () => ({
    useAccessOverview: () => ({ state: accessOverviewStateRef.current, retry: vi.fn() }),
}))

const gmCampaignId = sessionBootstrapFixture.campaigns[0].campaign_id

function renderWithSession(campaignId: string, hasManageCapability: boolean) {
    return render(
        <SessionContext.Provider
            value={{
                state: {
                    status: "authenticated",
                    bootstrap: {
                        ...sessionBootstrapFixture,
                        campaigns: sessionBootstrapFixture.campaigns.map((campaign) => ({
                            ...campaign,
                            capabilities: hasManageCapability ? ["access.manage"] : ["campaign.view"],
                        })),
                    },
                },
                reload: vi.fn(),
            }}
        >
            <AudiencePreviewSection campaignId={campaignId} resourceType="quest" />
        </SessionContext.Provider>,
    )
}

describe("AudiencePreviewSection", () => {
    it("renders nothing when there is no session provider at all", () => {
        render(<AudiencePreviewSection campaignId={gmCampaignId} resourceType="quest" />)

        expect(screen.queryByRole("button", { name: "Preview as member" })).not.toBeInTheDocument()
    })

    it("renders nothing for a member without access.manage on this campaign", () => {
        renderWithSession(gmCampaignId, false)

        expect(screen.queryByRole("button", { name: "Preview as member" })).not.toBeInTheDocument()
    })

    it("renders nothing while the access overview is loading", () => {
        accessOverviewStateRef.current = { status: "loading" }
        renderWithSession(gmCampaignId, true)

        expect(screen.queryByRole("button", { name: "Preview as member" })).not.toBeInTheDocument()
    })

    it("renders nothing when the access overview errors, never a stale panel", () => {
        accessOverviewStateRef.current = { status: "error", error: new Error("boom") }
        renderWithSession(gmCampaignId, true)

        expect(screen.queryByRole("button", { name: "Preview as member" })).not.toBeInTheDocument()
    })

    it("shows the control, sourced from the overview's member list, once authorized and loaded", () => {
        accessOverviewStateRef.current = {
            status: "success",
            overview: {
                members: [
                    { campaign_membership_id: "membership-a", display_name: "Player One", user_id: "user-1" },
                ],
                assignable_roles: [],
                assignable_characters: [],
                assignable_relationship_types: [],
                grantable_resource_capabilities: [],
                access_groups: [],
            },
        }
        renderWithSession(gmCampaignId, true)

        expect(screen.getByRole("button", { name: "Preview as member" })).toBeInTheDocument()
    })
})
