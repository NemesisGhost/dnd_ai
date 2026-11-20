import { fireEvent, render, screen } from "@testing-library/react"
import { useState } from "react"
import { describe, expect, it, vi } from "vitest"
import { EffectiveAccessPanel } from "./EffectiveAccessPanel"

const { effectiveAccessStateRef } = vi.hoisted(() => ({
    effectiveAccessStateRef: { current: { status: "loading" } as Record<string, unknown> },
}))

vi.mock("../hooks/useEffectiveAccess", () => ({
    useEffectiveAccess: () => ({ state: effectiveAccessStateRef.current, retry: vi.fn() }),
}))

// The panel is controlled (its open state is held above the access list); this holds it the way the
// page does, so the tests drive it through its own button.
function Held({ onRefresh = vi.fn(), initiallyOpen = false }: { onRefresh?: () => void; initiallyOpen?: boolean }) {
    const [open, setOpen] = useState(initiallyOpen)
    return (
        <EffectiveAccessPanel
            campaignId="campaign-1"
            campaignMembershipId="membership-1"
            memberDisplayName="Player One"
            isOpen={open}
            onToggle={() => setOpen((current) => !current)}
            onRefresh={onRefresh}
        />
    )
}

const access = (sources: object[], extra: object = {}) => ({
    status: "success",
    access: {
        display_name: "Player One",
        capabilities: [{ code: "campaign.view", display_name: "View Campaign", sources }],
        denials: [],
        ...extra,
    },
})

describe("EffectiveAccessPanel", () => {
    it("does not fetch until the disclosure is opened", () => {
        render(<Held />)

        expect(screen.queryByText(/Why Player One can see this/)).not.toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Explain access" })).toHaveAttribute("aria-expanded", "false")
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

        render(<Held />)

        fireEvent.click(screen.getByRole("button", { name: "Explain access" }))

        expect(screen.getByText(/Why Player One can see this/)).toBeInTheDocument()
        expect(screen.getByText("View Campaign")).toBeInTheDocument()
        expect(screen.getByText(/Role: Player/)).toBeInTheDocument()
        expect(screen.getByText(/Character access: Controls \(Aria\)/)).toBeInTheDocument()
        expect(screen.getByText(/canon.edit — Character \(Bram\)/)).toBeInTheDocument()
    })

    it("clears its content when the disclosure closes", () => {
        effectiveAccessStateRef.current = access([{ kind: "role", label: "Player", target_display_name: null }])

        render(<Held />)

        fireEvent.click(screen.getByRole("button", { name: "Explain access" }))
        expect(screen.getByText("View Campaign")).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Hide access explanation" }))
        expect(screen.queryByText("View Campaign")).not.toBeInTheDocument()
    })

    it("shows a message when the member holds no capability", () => {
        effectiveAccessStateRef.current = {
            status: "success",
            access: { display_name: "Player One", capabilities: [], denials: [] },
        }

        render(<Held />)

        fireEvent.click(screen.getByRole("button", { name: "Explain access" }))

        expect(screen.getByText("This member holds no capability in this campaign.")).toBeInTheDocument()
    })

    // E1: the label is the contract's own "Revelation" entry, not the humanized fallback's output.
    it("labels revelation sources explicitly, once per source and per capability (E1)", () => {
        effectiveAccessStateRef.current = {
            status: "success",
            access: {
                display_name: "Player One",
                capabilities: ["character.discover", "character.view_public_profile"].map((code) => ({
                    code,
                    display_name: code === "character.discover" ? "Discover characters" : "View public profile",
                    sources: [
                        { kind: "revelation", label: "Access group", target_display_name: "Mira" },
                        { kind: "revelation", label: "Member", target_display_name: "Mira" },
                    ],
                })),
                denials: [],
            },
        }
        render(<Held initiallyOpen />)
        expect(screen.getAllByText("Revelation: Access group (Mira)")).toHaveLength(2)
        expect(screen.getAllByText("Revelation: Member (Mira)")).toHaveLength(2)
    })

    it("renders an unknown future source kind through the humanized fallback (E2)", () => {
        effectiveAccessStateRef.current = access([
            { kind: "future_source", label: "Something", target_display_name: "Mira" },
        ])
        render(<Held initiallyOpen />)
        expect(screen.getByText("Future Source: Something (Mira)")).toBeInTheDocument()
    })

    it("renders no field beyond kind, label and target name of a source (E3)", () => {
        effectiveAccessStateRef.current = access([
            {
                kind: "revelation",
                label: "Member",
                target_display_name: "Mira",
                character_revelation_id: "MARKER-REVELATION-ID",
                reason: "MARKER-REASON",
                created_by: "MARKER-CREATOR",
                group_name: "MARKER-GROUP",
                character_id: "MARKER-CHARACTER-ID",
            },
        ])
        render(<Held initiallyOpen />)
        expect(screen.getByText("Revelation: Member (Mira)")).toBeInTheDocument()
        expect(document.body.textContent).not.toMatch(/MARKER/)
    })

    it("offers Refresh access only beside a loaded explanation, and it asks the page to refresh", () => {
        const onRefresh = vi.fn()
        effectiveAccessStateRef.current = { status: "loading" }
        const { unmount } = render(<Held initiallyOpen onRefresh={onRefresh} />)
        expect(screen.queryByRole("button", { name: "Refresh access" })).not.toBeInTheDocument()
        unmount()

        for (const status of ["unavailable", "error"]) {
            effectiveAccessStateRef.current = { status, error: new Error("x") }
            const view = render(<Held initiallyOpen onRefresh={onRefresh} />)
            expect(screen.queryByRole("button", { name: "Refresh access" })).not.toBeInTheDocument()
            view.unmount()
        }

        effectiveAccessStateRef.current = access([{ kind: "role", label: "Player", target_display_name: null }])
        render(<Held initiallyOpen onRefresh={onRefresh} />)
        fireEvent.click(screen.getByRole("button", { name: "Refresh access" }))
        expect(onRefresh).toHaveBeenCalledTimes(1)
    })

    it("keeps each row's explanation independent (E15)", () => {
        effectiveAccessStateRef.current = access([{ kind: "role", label: "Player", target_display_name: null }])
        render(
            <>
                <Held initiallyOpen />
                <Held initiallyOpen />
            </>,
        )
        expect(screen.getAllByText("View Campaign")).toHaveLength(2)
        fireEvent.click(screen.getAllByRole("button", { name: "Hide access explanation" })[0]!)
        expect(screen.getAllByText("View Campaign")).toHaveLength(1)
        expect(screen.getAllByRole("button", { name: "Hide access explanation" })).toHaveLength(1)
    })
})
