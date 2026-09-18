import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import type { CampaignAccessOverview } from "../types/accessOverview"
import { AccessPage } from "./AccessPage"

const fullOverview: CampaignAccessOverview = {
    members: [
        {
            campaign_membership_id:
                "5b1f7e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            display_name: "Aria the GM",
            status_code: "active",
            status_display_name: "Active",
            joined_at: "2026-01-01T00:00:00Z",
            roles: [
                {
                    role_id:
                        "7c2f8e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                    code: "campaign_owner",
                    display_name: "Campaign Owner",
                },
            ],
            character_relationships: [
                {
                    membership_character_relationship_id:
                        "8d3f9e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                    character_id:
                        "9e4f0e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                    character_display_name: "Kestrel Vane",
                    relationship_type_code: "primary_controller",
                    relationship_type_display_name:
                        "Primary Controller",
                    granted_at: "2026-01-02T00:00:00Z",
                    expires_at: null,
                },
            ],
            grants: [
                {
                    resource_grant_id:
                        "0f5f1e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                    capability_code: "campaign.view",
                    capability_display_name: "View Campaign",
                    effect: "allow",
                    target_type: "character",
                    reason: "Visibility for the shared scene",
                    granted_at: "2026-01-03T00:00:00Z",
                    expires_at: null,
                },
            ],
        },
        {
            campaign_membership_id:
                "1a6f2e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            display_name: "Quiet Observer",
            status_code: "active",
            status_display_name: "Active",
            joined_at: "2026-01-04T00:00:00Z",
            roles: [],
            character_relationships: [],
            grants: [],
        },
    ],
}

describe("AccessPage", () => {
    it("renders exactly one page-level heading", () => {
        render(<AccessPage overview={fullOverview} />)

        expect(
            screen.getAllByRole("heading", { level: 1 }),
        ).toHaveLength(1)

        expect(
            screen.getByRole("heading", {
                level: 1,
                name: "Access",
            }),
        ).toBeInTheDocument()
    })

    it("renders member display identity and human-readable role/status labels", () => {
        render(<AccessPage overview={fullOverview} />)

        expect(
            screen.getByText("Aria the GM"),
        ).toBeInTheDocument()

        expect(
            screen.getAllByText("Active").length,
        ).toBeGreaterThan(0)

        expect(
            screen.getAllByText("Campaign Owner").length,
        ).toBeGreaterThan(0)
    })

    it("renders character relationships and grants with human-readable labels", () => {
        const { container } = render(
            <AccessPage overview={fullOverview} />,
        )

        expect(
            screen.getByText(
                "Kestrel Vane — Primary Controller",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText("View Campaign"),
        ).toBeInTheDocument()

        expect(container.textContent).toContain(
            "(Allow) — Character",
        )
        expect(container.textContent).toContain(
            "Visibility for the shared scene",
        )
    })

    it("never renders a raw UUID as user-facing text", () => {
        const { container } = render(
            <AccessPage overview={fullOverview} />,
        )

        const uuidPattern =
            /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i

        expect(
            uuidPattern.test(container.textContent ?? ""),
        ).toBe(false)
    })

    it("shows a deliberate per-member empty state for a member with no roles, relationships, or grants", () => {
        render(<AccessPage overview={fullOverview} />)

        expect(
            screen.getByText("No roles assigned."),
        ).toBeInTheDocument()

        expect(
            screen.getByText("No character relationships."),
        ).toBeInTheDocument()

        expect(
            screen.getByText("No explicit grants."),
        ).toBeInTheDocument()
    })

    it("shows a deliberate empty state when the campaign has no manageable access records", () => {
        render(<AccessPage overview={{ members: [] }} />)

        expect(
            screen.getByText(
                "No campaign members are currently recorded.",
            ),
        ).toBeInTheDocument()
    })

    it("renders no mutation controls", () => {
        render(<AccessPage overview={fullOverview} />)

        expect(screen.queryAllByRole("button")).toHaveLength(0)
        expect(screen.queryAllByRole("textbox")).toHaveLength(0)
    })

    it("renders each member as a collapsed-by-default disclosure element", () => {
        const { container } = render(
            <AccessPage overview={fullOverview} />,
        )

        const detailsElements =
            container.querySelectorAll("details")

        expect(detailsElements.length).toBe(2)
        detailsElements.forEach((details) => {
            expect(details.open).toBe(false)
        })
    })

    it("uses a semantic list for the member collection", () => {
        render(<AccessPage overview={fullOverview} />)

        expect(
            screen.getAllByRole("list").length,
        ).toBeGreaterThan(0)
    })
})
