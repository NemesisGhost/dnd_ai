import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { SessionBootstrap } from "../types/bootstrap"
import { useHeldWorldCapability, useWorldCapability } from "./useWorldCapability"

// The bootstrap carries one world-capability snapshot per campaign. A gate reads the snapshot of the
// campaign it is asked about, never another's: a person who is an Editor on one campaign's world and
// nothing on another's must see each campaign's own answer, whichever was loaded last.

const base = sessionBootstrapFixture.campaigns[0]!

const bootstrap: SessionBootstrap = {
    ...sessionBootstrapFixture,
    campaigns: [
        { ...base, campaign_id: "editor-here", world_capabilities: ["world.view", "world.canon.edit"] },
        { ...base, campaign_id: "nothing-here", world_capabilities: [] },
        { ...base, campaign_id: "older-bootstrap", world_capabilities: undefined },
    ],
}

function Probe({ campaignId }: { campaignId: string | undefined }) {
    return (
        <p>
            offer={String(useWorldCapability(campaignId, "world.canon.edit"))} held=
            {String(useHeldWorldCapability(campaignId, "world.canon.edit"))}
        </p>
    )
}

function inSession(children: ReactNode, status: "authenticated" | "loading" = "authenticated") {
    return render(
        <SessionContext.Provider
            value={{
                state: status === "authenticated" ? { status, bootstrap } : { status: "loading" },
                reload: vi.fn(),
                refresh: vi.fn(),
            }}
        >
            {children}
        </SessionContext.Provider>,
    )
}

describe("world capability gates", () => {
    it("answer from the snapshot of the campaign asked about, not another's", () => {
        inSession(
            <>
                <Probe campaignId="editor-here" />
                <Probe campaignId="nothing-here" />
            </>,
        )
        const lines = screen.getAllByText(/offer=/).map((el) => el.textContent?.replace(/\s+/g, " ").trim())
        expect(lines).toEqual(["offer=true held=true", "offer=false held=false"])
    })

    it("offer when there is no list to consult, but never send a request on that basis", () => {
        inSession(<Probe campaignId="older-bootstrap" />)
        expect(screen.getByText(/offer=/)).toHaveTextContent("offer=true held=false")
    })

    it("hold nothing for a campaign the bootstrap does not name, or outside a campaign", () => {
        inSession(
            <>
                <Probe campaignId="someone-elses" />
                <Probe campaignId={undefined} />
            </>,
        )
        const lines = screen.getAllByText(/offer=/).map((el) => el.textContent?.replace(/\s+/g, " ").trim())
        // The offer gate is permissive without a list; the request gate fails closed.
        expect(lines).toEqual(["offer=true held=false", "offer=true held=false"])
    })

    it("grant nothing before the session is known", () => {
        inSession(<Probe campaignId="editor-here" />, "loading")
        expect(screen.getByText(/offer=/)).toHaveTextContent("offer=false held=false")
    })
})
