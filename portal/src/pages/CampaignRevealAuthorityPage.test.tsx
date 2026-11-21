import { act, fireEvent, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { useSession } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CampaignRevealAuthorityPage } from "./CampaignRevealAuthorityPage"

// Acceptance cases L1 to L12 of docs/delivery/p15-c02-s03-reveal-delegations-plan.md (T01: read and offer).

const PATH = "/campaigns/c1/reveal-delegations"

const withManage = () =>
    bootstrapWith({
        campaigns: [
            { ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["access.manage", "canon.edit"] },
            { ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c2", capabilities: ["access.manage"] },
        ],
    })
const withoutManage = () =>
    bootstrapWith({
        campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] }],
    })

const state = (overrides: object = {}) => ({
    can_manage: true,
    members: [
        {
            campaign_membership_id: "m-gm1",
            display_name: "Gina GM",
            delegation: { granted_at: "2026-11-01T10:00:00Z", granted_by_name: "Olga Owner" },
        },
        { campaign_membership_id: "m-gm2", display_name: "Gus GM", delegation: null },
    ],
    lapsed_delegations: [],
    ...overrides,
})

function RefreshButton() {
    const { refresh } = useSession()
    return (
        <button type="button" onClick={() => void refresh()}>
            Refresh session
        </button>
    )
}

function setup({
    body = state(),
    bootstrap = withManage(),
    onRefresh,
    entry = "/app/c1/access/reveal-authority",
}: {
    body?: object
    bootstrap?: ReturnType<typeof withManage>
    onRefresh?: () => Promise<ReturnType<typeof withManage> | null>
    entry?: string
} = {}) {
    const server = installMockServer()
    server.on("GET", PATH, { body })
    const rendered = renderAuthoringRoutes({
        initialEntry: entry,
        bootstrap,
        routes: [
            {
                path: "/app/:campaignId/access/reveal-authority",
                element: (
                    <>
                        <RefreshButton />
                        <CampaignRevealAuthorityPage />
                    </>
                ),
            },
        ],
        onRefresh,
    })
    return { server, ...rendered }
}

describe("CampaignRevealAuthorityPage: navigation and gate (L1, L2, L11)", () => {
    it("L1: the tab is listed beside the others, and the page sends exactly one reveal-delegations read and nothing else", async () => {
        const { server } = setup()
        await screen.findByRole("heading", { name: "Reveal authority" })
        const nav = screen.getByRole("navigation", { name: "Access" })
        expect(within(nav).getByRole("link", { name: "Reveal authority" })).toHaveAttribute(
            "href",
            "/app/c1/access/reveal-authority",
        )
        for (const name of ["Access management", "Invitations", "Audit history"]) {
            expect(within(nav).getByRole("link", { name })).toBeInTheDocument()
        }
        expect(server.calls.map((c) => `${c.method} ${c.path}`)).toEqual([`GET ${PATH}`])
    })

    it("L2: without access.manage the placeholder shows and nothing is sent", () => {
        const { server } = setup({ bootstrap: withoutManage() })
        expect(screen.getByText("Access unavailable")).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: "Reveal authority" })).not.toBeInTheDocument()
        expect(server.calls).toHaveLength(0)
    })

    it("L2: a read still in flight when access.manage is lost is aborted and publishes nothing", async () => {
        let release: (value: { body: object }) => void = () => undefined
        const server = installMockServer()
        server.on("GET", PATH, () => new Promise((resolve) => (release = resolve)))
        renderAuthoringRoutes({
            initialEntry: "/app/c1/access/reveal-authority",
            bootstrap: withManage(),
            onRefresh: async () => withoutManage(),
            routes: [
                {
                    path: "/app/:campaignId/access/reveal-authority",
                    element: (
                        <>
                            <RefreshButton />
                            <CampaignRevealAuthorityPage />
                        </>
                    ),
                },
            ],
        })
        await screen.findByText("Loading reveal authority…")
        fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
        await screen.findByText("Access unavailable")
        await act(async () => release({ body: state() }))
        expect(screen.queryByText("Gina GM")).not.toBeInTheDocument()
        expect(screen.getByText("Access unavailable")).toBeInTheDocument()
    })

    it("L11: nothing but this page reads reveal-delegations (member cards, character pages, bootstrap)", () => {
        const sources = import.meta.glob("/src/**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }) as Record<
            string,
            string
        >
        const readers = Object.entries(sources)
            .filter(([path]) => !/\.test\.tsx?$/.test(path) && !path.includes("/test/"))
            .filter(([, source]) => source.includes("reveal-delegations") || source.includes("revealDelegationsPath"))
            .map(([path]) => path)
            .sort()
        expect(readers).toEqual([
            "/src/api/revealDelegations.ts",
            "/src/pages/CampaignRevealAuthorityPage.tsx",
            "/src/types/revealDelegations.ts",
        ])
    })
})

describe("CampaignRevealAuthorityPage: content (L3 to L6, L12)", () => {
    it("L3: no GM shows the empty line and the static owner line", async () => {
        setup({ body: state({ members: [] }) })
        expect(await screen.findByText("No member currently holds the GM role.")).toBeInTheDocument()
        expect(screen.getByText(/Campaign owners can always reveal characters/)).toBeInTheDocument()
    })

    it("L4: rows follow the server order, with the grant date and granter, and render no id, reason or role id", async () => {
        const { container } = setup({
            body: state({
                members: [
                    {
                        campaign_membership_id: "m-gm1",
                        display_name: "Gina GM",
                        delegation: { granted_at: "2026-11-01T10:00:00Z", granted_by_name: "Olga Owner" },
                    },
                    {
                        campaign_membership_id: "m-gm2",
                        display_name: "Gus GM",
                        delegation: { granted_at: "2026-11-02T10:00:00Z", granted_by_name: null },
                    },
                    { campaign_membership_id: "m-gm3", display_name: "Gail GM", delegation: null },
                ],
            }),
        })
        await screen.findByText("Gina GM")
        const items = within(screen.getByRole("list", { name: "GMs" })).getAllByRole("listitem")
        expect(items.map((li) => within(li).getByText(/GM$/, { selector: "strong" }).textContent)).toEqual([
            "Gina GM",
            "Gus GM",
            "Gail GM",
        ])
        expect(items[0]).toHaveTextContent("Can reveal characters")
        expect(items[0]).toHaveTextContent("granted by Olga Owner")
        expect(items[1]).toHaveTextContent("granted by a former member")
        expect(items[2]).toHaveTextContent("Cannot reveal characters.")
        expect(container.textContent).not.toMatch(/m-gm|membership|role id/i)
    })

    it("L5: can_manage true shows the line that the owner can grant or revoke", async () => {
        setup()
        expect(await screen.findByText("You can grant or revoke reveal authority.")).toBeInTheDocument()
    })

    it("L6: can_manage false shows the neutral line, with no control, and infers nothing from roles", async () => {
        // The bootstrap says the caller manages access and holds a role named gm: only the server's can_manage counts.
        setup({ body: state({ can_manage: false }) })
        expect(await screen.findByText("Only a campaign owner can grant or revoke reveal authority.")).toBeInTheDocument()
        expect(screen.queryByText("You can grant or revoke reveal authority.")).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Grant|Revoke/ })).not.toBeInTheDocument()
    })

    it("L12: lapsed delegations are listed apart, in the server's words, and an empty array renders no section", async () => {
        const { unmount } = setup({
            body: state({
                lapsed_delegations: [
                    {
                        campaign_membership_id: "m-old",
                        display_name: "Olive Old",
                        granted_at: "2026-10-01T10:00:00Z",
                        granted_by_name: null,
                    },
                ],
            }),
        })
        const heading = await screen.findByRole("heading", { name: "Delegations that no longer apply" })
        const section = heading.closest("section") as HTMLElement
        expect(section).toHaveTextContent("Olive Old no longer holds the GM role, so this gives no authority.")
        expect(section).toHaveTextContent("granted by a former member")
        expect(section).not.toHaveTextContent(/revoked|removed/i)
        // The lapsed member is not among the GMs.
        expect(within(screen.getByRole("list", { name: "GMs" })).queryByText("Olive Old")).not.toBeInTheDocument()
        unmount()
        setup()
        await screen.findByText("Gina GM")
        expect(screen.queryByRole("heading", { name: "Delegations that no longer apply" })).not.toBeInTheDocument()
    })
})

describe("CampaignRevealAuthorityPage: read failures and scope (L7 to L10)", () => {
    for (const status of [403, 404]) {
    it(`L7: a ${status} read removes every name and date and requests one in-place session refresh, with no retry loop`, async () => {
        let refreshes = 0
        const server = installMockServer()
        server.on("GET", PATH, { status, body: { error: { code: "nope", message: "SERVER-SECRET-TEXT" } } })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/access/reveal-authority",
            bootstrap: withManage(),
            onRefresh: async () => {
                refreshes += 1
                return withManage()
            },
            routes: [{ path: "/app/:campaignId/access/reveal-authority", element: <CampaignRevealAuthorityPage /> }],
        })
        expect(await screen.findByText("Reveal authority unavailable")).toBeInTheDocument()
        expect(screen.queryByText("Gina GM")).not.toBeInTheDocument()
        expect(screen.queryByText(/SERVER-SECRET-TEXT/)).not.toBeInTheDocument()
        await act(async () => undefined)
        expect(refreshes).toBe(1)
        expect(server.callsTo("GET", PATH)).toHaveLength(1)
    })
    }

    it("L8: a failed first read shows Try again, and a good answer replaces it with the list and the offer", async () => {
        const server = installMockServer()
        server.on("GET", PATH, { networkError: true })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/access/reveal-authority",
            bootstrap: withManage(),
            routes: [{ path: "/app/:campaignId/access/reveal-authority", element: <CampaignRevealAuthorityPage /> }],
        })
        const alert = await screen.findByRole("alert")
        expect(alert).toHaveTextContent("The latest reveal authority could not be loaded")
        expect(screen.queryByText("You can grant or revoke reveal authority.")).not.toBeInTheDocument()
        server.on("GET", PATH, { body: state() })
        fireEvent.click(within(alert).getByRole("button", { name: "Try again" }))
        expect(await screen.findByText("Gina GM")).toBeInTheDocument()
        expect(screen.getByText("You can grant or revoke reveal authority.")).toBeInTheDocument()
        expect(server.calls.every((c) => c.method === "GET")).toBe(true)
    })

    it("L9: a late answer for campaign A never appears under campaign B", async () => {
        let releaseA: (value: { body: object }) => void = () => undefined
        const server = installMockServer()
        server.on("GET", "/campaigns/c1/reveal-delegations", () => new Promise((resolve) => (releaseA = resolve)))
        server.on("GET", "/campaigns/c2/reveal-delegations", {
            body: state({ members: [{ campaign_membership_id: "m-b", display_name: "Bea B-GM", delegation: null }] }),
        })
        const { router } = renderAuthoringRoutes({
            initialEntry: "/app/c1/access/reveal-authority",
            bootstrap: withManage(),
            routes: [{ path: "/app/:campaignId/access/reveal-authority", element: <CampaignRevealAuthorityPage /> }],
        })
        await screen.findByText("Loading reveal authority…")
        await act(async () => {
            await router.navigate("/app/c2/access/reveal-authority")
        })
        expect(await screen.findByText("Bea B-GM")).toBeInTheDocument()
        await act(async () => releaseA({ body: state() }))
        expect(screen.queryByText("Gina GM")).not.toBeInTheDocument()
        expect(screen.getByText("Bea B-GM")).toBeInTheDocument()
    })

    it("L10: the server's next answer drops a member whose GM role ended, and lists a returning one with no delegation", async () => {
        const answers = [
            state(),
            state({ members: [{ campaign_membership_id: "m-gm2", display_name: "Gus GM", delegation: null }] }),
            state({
                members: [
                    { campaign_membership_id: "m-gm1", display_name: "Gina GM", delegation: null },
                    { campaign_membership_id: "m-gm2", display_name: "Gus GM", delegation: null },
                ],
            }),
        ]
        let index = 0
        const server = installMockServer()
        server.on("GET", PATH, () => ({ body: answers[Math.min(index++, answers.length - 1)] }))
        const { router } = renderAuthoringRoutes({
            initialEntry: "/app/c1/access/reveal-authority",
            bootstrap: withManage(),
            routes: [
                { path: "/app/:campaignId/access/reveal-authority", element: <CampaignRevealAuthorityPage /> },
                { path: "/app/:campaignId/elsewhere", element: <p>Elsewhere</p> },
            ],
        })
        const row = (name: string) => screen.getByText(name, { selector: "strong" }).closest("li") as HTMLElement
        await screen.findByText("Gina GM")
        expect(row("Gina GM")).toHaveTextContent("Can reveal characters")
        for (const target of ["/app/c1/elsewhere", "/app/c1/access/reveal-authority"]) {
            await act(async () => {
                await router.navigate(target)
            })
            if (target.endsWith("reveal-authority")) await screen.findByText("Gus GM")
            else await screen.findByText("Elsewhere")
        }
        expect(screen.queryByText("Gina GM")).not.toBeInTheDocument()
        for (const target of ["/app/c1/elsewhere", "/app/c1/access/reveal-authority"]) {
            await act(async () => {
                await router.navigate(target)
            })
            if (target.endsWith("reveal-authority")) await screen.findByText("Gina GM")
            else await screen.findByText("Elsewhere")
        }
        expect(row("Gina GM")).toHaveTextContent("Cannot reveal characters.")
    })
})
