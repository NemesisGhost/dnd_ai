import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { EffectiveAccessPanel } from "./EffectiveAccessPanel"

const { effectiveAccessStateRef } = vi.hoisted(() => ({
    effectiveAccessStateRef: { current: { status: "loading" } as Record<string, unknown> },
}))

vi.mock("../hooks/useEffectiveAccess", () => ({
    useEffectiveAccess: () => ({ state: effectiveAccessStateRef.current, retry: vi.fn() }),
}))

describe("EffectiveAccessPanel", () => {
    it("does not fetch until the disclosure is opened", () => {
        render(
            <EffectiveAccessPanel
                campaignId="campaign-1"
                campaignMembershipId="membership-1"
                memberDisplayName="Player One"
            />,
        )

        expect(screen.queryByText(/Why Player One can see this/)).not.toBeInTheDocument()
    })

    it("shows the capability sources once opened", () => {
        effectiveAccessStateRef.current = {
            status: "success",
            access: {
                display_name: "Player One",
                capabilities: [
                    {
                        code: "campaign.view",
                        display_name: "View Campaign",
                        sources: [
                            { kind: "role", label: "Player", target_display_name: null },
                            {
                                kind: "character_relationship",
                                label: "Controls",
                                target_display_name: "Aria",
                            },
                        ],
                    },
                ],
                denials: [
                    { capability_code: "canon.edit", target_type: "character", target_display_name: "Bram" },
                ],
            },
        }

        render(
            <EffectiveAccessPanel
                campaignId="campaign-1"
                campaignMembershipId="membership-1"
                memberDisplayName="Player One"
            />,
        )

        fireEvent.click(screen.getByRole("button", { name: "Explain access" }))

        expect(screen.getByText(/Why Player One can see this/)).toBeInTheDocument()
        expect(screen.getByText("View Campaign")).toBeInTheDocument()
        expect(screen.getByText(/Role: Player/)).toBeInTheDocument()
        expect(screen.getByText(/Character relationship: Controls \(Aria\)/)).toBeInTheDocument()
        expect(screen.getByText(/canon.edit — Character \(Bram\)/)).toBeInTheDocument()
    })

    it("clears its content when the disclosure closes", () => {
        effectiveAccessStateRef.current = {
            status: "success",
            access: {
                display_name: "Player One",
                capabilities: [
                    {
                        code: "campaign.view",
                        display_name: "View Campaign",
                        sources: [{ kind: "role", label: "Player", target_display_name: null }],
                    },
                ],
                denials: [],
            },
        }

        render(
            <EffectiveAccessPanel
                campaignId="campaign-1"
                campaignMembershipId="membership-1"
                memberDisplayName="Player One"
            />,
        )

        const toggle = screen.getByRole("button", { name: "Explain access" })
        fireEvent.click(toggle)
        expect(screen.getByText("View Campaign")).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Hide access explanation" }))
        expect(screen.queryByText("View Campaign")).not.toBeInTheDocument()
    })

    it("shows a message when the member holds no capability", () => {
        effectiveAccessStateRef.current = {
            status: "success",
            access: { display_name: "Player One", capabilities: [], denials: [] },
        }

        render(
            <EffectiveAccessPanel
                campaignId="campaign-1"
                campaignMembershipId="membership-1"
                memberDisplayName="Player One"
            />,
        )

        fireEvent.click(screen.getByRole("button", { name: "Explain access" }))

        expect(screen.getByText("This member holds no capability in this campaign.")).toBeInTheDocument()
    })
})
