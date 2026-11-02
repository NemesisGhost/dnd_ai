import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import type { SessionBootstrap } from "../types/bootstrap"
import { ArchivedCampaignsSection } from "./ArchivedCampaignsSection"

afterEach(() => {
    vi.unstubAllGlobals()
})

const LIST = "/campaigns/archived?limit=100"
const REACTIVATE = "/campaigns/a1/reactivate"

const ARCHIVED = {
    items: [{ campaign_id: "a1", name: "Old Road", world_name: "Mundivita", timeline_name: "Primary", row_version: 5 }],
    next_cursor: null,
}
const EMPTY = { items: [], next_cursor: null }

const bootstrap = (): SessionBootstrap => bootstrapWith({ campaigns: [sessionBootstrapFixture.campaigns[0]!] })

function setup(register: (server: MockServer) => void, onRefresh?: () => Promise<SessionBootstrap>) {
    const server = installMockServer()
    register(server)
    renderAuthoringRoutes({
        initialEntry: "/campaigns",
        bootstrap: bootstrap(),
        onRefresh,
        routes: [{ path: "/campaigns", element: <ArchivedCampaignsSection /> }],
    })
    return server
}

async function reactivate() {
    fireEvent.click(await screen.findByRole("button", { name: "Reactivate Old Road" }))
    const buttons = await screen.findAllByRole("button", { name: "Reactivate campaign" })
    fireEvent.click(buttons[buttons.length - 1]!)
}

describe("archived campaigns: reactivation and its refresh", () => {
    it("says the campaign was reactivated when the bootstrap refresh failed, and retries only that read", async () => {
        let reads = 0
        const onRefresh = vi.fn(async () => {
            reads += 1
            if (reads === 1) throw new Error("boom")
            return bootstrap()
        })
        let reactivated = false
        const server = setup((s) => {
            s.on("GET", LIST, () => ({ body: reactivated ? EMPTY : ARCHIVED }))
            s.on("POST", REACTIVATE, () => {
                reactivated = true
                return { body: { campaign_id: "a1", row_version: 6 } }
            })
        }, onRefresh)
        await reactivate()
        const notice = await screen.findByRole("status")
        expect(notice).toHaveTextContent("Campaign reactivated. The latest campaign list and menus could not be loaded")
        expect(notice).not.toHaveTextContent("boom")

        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        await waitFor(() => expect(screen.queryByRole("status")).toBeNull())
        expect(onRefresh).toHaveBeenCalledTimes(2)
        expect(server.callsTo("POST", REACTIVATE)).toHaveLength(1)
    })

    it("keeps the stale list from being reactivated twice when the list re-read failed", async () => {
        let failRead = false
        const server = setup((s) => {
            s.on("GET", LIST, () => (failRead ? { status: 500, body: {} } : { body: ARCHIVED }))
            s.on("POST", REACTIVATE, () => {
                failRead = true
                return { body: { campaign_id: "a1", row_version: 6 } }
            })
        })
        await reactivate()
        expect(await screen.findByRole("status")).toHaveTextContent(
            "Campaign reactivated. The latest list of archived campaigns could not be loaded",
        )
        // The row shown is out of date: it cannot be reactivated again from here.
        expect(screen.getByRole("button", { name: "Reactivate Old Road" })).toBeDisabled()
        failRead = false
        server.on("GET", LIST, { body: EMPTY })
        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        await waitFor(() => expect(screen.queryByRole("status")).toBeNull())
        expect(screen.queryByRole("heading", { name: "Archived campaigns you manage" })).toBeNull()
        expect(server.callsTo("POST", REACTIVATE)).toHaveLength(1)
    })

    it("explains an unconfirmed reactivation as unconfirmed and keeps the dialog for a same-key retry", async () => {
        let attempts = 0
        const server = setup((s) => {
            s.on("GET", LIST, { body: ARCHIVED })
            s.on("POST", REACTIVATE, () => {
                attempts += 1
                return attempts === 1 ? { networkError: true } : { body: { campaign_id: "a1", row_version: 6 } }
            })
        })
        await reactivate()
        expect(await screen.findByText(/cannot tell whether this was saved/)).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Retry" }))
        await waitFor(() => expect(server.callsTo("POST", REACTIVATE)).toHaveLength(2))
        const [first, second] = server.callsTo("POST", REACTIVATE)
        expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
        expect(second!.body).toEqual(first!.body)
    })

    it("renders nothing for an empty list or one that failed to load", async () => {
        const server = setup((s) => s.on("GET", LIST, { status: 500, body: {} }))
        await waitFor(() => expect(server.callsTo("GET", LIST)).toHaveLength(1))
        await new Promise((resolve) => setTimeout(resolve, 30))
        expect(screen.queryByRole("alert")).toBeNull()
        expect(screen.queryByRole("heading", { name: "Archived campaigns you manage" })).toBeNull()
    })
})
