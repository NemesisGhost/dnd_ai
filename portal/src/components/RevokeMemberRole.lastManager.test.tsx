import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { RevokeMemberRole } from "./RevokeMemberRole"

// The retention refusal of a role removal (a campaign must keep an access manager) is explained, not
// reported as "Try again": retrying cannot help, and the message names what to do first. It names no
// one else: only the member and role the person already chose.
let status: { kind: string } = { kind: "idle" }
vi.mock("../hooks/useRevokeMembershipRole", () => ({
    useRevokeMembershipRole: () => ({ status, submit: vi.fn(), reset: vi.fn() }),
}))

const role = { membership_role_id: "r1", role_id: "x", code: "campaign_owner", display_name: "Campaign Owner" }

function show(kind: string) {
    status = { kind }
    render(
        <RevokeMemberRole
            campaignId="c1"
            memberDisplayName="Smoke GM One"
            role={role}
            onChanged={vi.fn()}
            onMutationStart={vi.fn()}
        />,
    )
    fireEvent.click(screen.getByRole("button", { name: "Remove role" }))
}

describe("RevokeMemberRole refusal messages", () => {
    it("explains the last-access-manager refusal and says what to do first", () => {
        show("last_manager")
        const message = screen.getByRole("status")
        expect(message).toHaveTextContent(/must always keep at least one access manager/)
        expect(message).toHaveTextContent(/Give the Campaign Owner role to another member first/)
        expect(message).not.toHaveTextContent(/Try again/)
    })

    it("keeps an unknown failure on the generic retryable message", () => {
        show("error")
        expect(screen.getByRole("status")).toHaveTextContent("The role could not be removed. Try again.")
    })
})
