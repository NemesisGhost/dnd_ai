import { fireEvent, screen, waitFor } from "@testing-library/react"
import { useState } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import type { RefetchOutcome } from "../../hooks/useAuthoringResource"
import type { CampaignSessionDetail } from "../../types/campaignSession"
import { ParticipantForm } from "./ParticipantForm"

afterEach(() => {
    vi.unstubAllGlobals()
})

const SESSION = {
    session_id: "s1",
    session_number: 1,
    title: "T",
    status_code: "active",
    play_status: "scheduled",
    row_version: 3,
    participants: [],
    participant_role_options: { player_character: ["player_character", "guest"], npc: ["npc", "guest"] },
    events: [],
} as unknown as CampaignSessionDetail

const ADD = "/campaigns/c1/sessions/s1/participants"

// Holds the session the page would hold: its version only moves when a read lands (the button).
function Harness({ refetch }: { refetch: () => Promise<RefetchOutcome> }) {
    const [version, setVersion] = useState(3)
    return (
        <>
            <ParticipantForm
                campaignId="c1"
                session={{ ...SESSION, row_version: version }}
                presentCharacterIds={new Set()}
                refetch={refetch}
                refreshFailed={false}
            />
            <button type="button" onClick={() => setVersion(4)}>
                A newer read landed
            </button>
        </>
    )
}

function setup(refetch: () => Promise<RefetchOutcome>) {
    const server = installMockServer()
    server.on("GET", /\/campaigns\/c1\/world\/search/, {
        body: {
            items: [{ entity_id: "c9", category: "character", entity_type_code: "npc", name: "Doran", summary: null }],
            next_cursor: null,
        },
    })
    server.on("POST", ADD, {
        status: 201,
        body: { session_id: "s1", row_version: 4, changed: true, session_participant_id: "p1" },
    })
    renderAuthoringRoutes({
        initialEntry: "/x",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1" }],
        }),
        routes: [{ path: "/x", element: <Harness refetch={refetch} /> }],
    })
    return server
}

async function add() {
    fireEvent.focus(await screen.findByRole("combobox", { name: "Character" }))
    fireEvent.click(await screen.findByRole("option", { name: /Doran/ }))
    fireEvent.click(screen.getByRole("button", { name: "Add participant" }))
}

describe("ParticipantForm: a confirmed add whose refresh did not complete", () => {
    it("holds another add while the read is only superseded, until a version the server returned arrives", async () => {
        const refetch = vi.fn(async (): Promise<RefetchOutcome> => "superseded")
        const server = setup(refetch)
        await add()
        await waitFor(() => expect(refetch).toHaveBeenCalledTimes(1))
        // Version 4 was confirmed, but this form still holds version 3: a second add would send 3.
        await waitFor(() => expect(screen.getByRole("button", { name: "Add participant" })).toBeDisabled())
        expect(screen.getByText(/Saved\. The latest participant list could not be loaded/)).toBeInTheDocument()
        fireEvent.submit(screen.getByRole("form", { name: "Add a participant" }))
        expect(server.callsTo("POST", ADD)).toHaveLength(1)

        fireEvent.click(screen.getByRole("button", { name: "A newer read landed" }))
        await waitFor(() => expect(screen.getByRole("button", { name: "Add participant" })).toBeEnabled())
        expect(screen.queryByText(/Saved\. The latest participant list/)).toBeNull()
    })

    it("treats a completed read as resolved", async () => {
        const refetch = vi.fn(async (): Promise<RefetchOutcome> => "ok")
        setup(refetch)
        await add()
        await waitFor(() => expect(screen.queryByText(/Saved\. The latest participant list/)).toBeNull())
        expect(screen.getByRole("button", { name: "Add participant" })).toBeEnabled()
    })
})
