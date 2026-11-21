import { act, fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import { CharacterRevelationsSection } from "./CharacterRevelationsSection"

// Acceptance cases of docs/delivery/p15-c02-s02-revelations-plan.md: V1 to V10 (T01, the list). V1 and
// V9 are also exercised through the page in pages/CharacterPublicProfilePage.revelations.test.tsx.

const LIST = "/campaigns/c1/characters/ch1/revelations"

function entry(overrides: object = {}) {
    return {
        character_revelation_id: "r-1",
        audience_kind: "member",
        target_campaign_membership_id: "m-1",
        target_member_name: "Pia Player",
        target_access_group_id: null,
        target_access_group_name: null,
        created_by_membership_id: "m-gm",
        created_by_name: "Gina GM",
        authority_source: "owner",
        created_at: "2026-11-19T10:00:00Z",
        live: true,
        ended_at: null,
        end_reason: null,
        ...overrides,
    }
}

const read = (revelations: object[] = []) => ({ body: { character_id: "ch1", revelations } })

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(list: object = read(), characterId = "ch1", onGone = vi.fn()) {
    const server = installMockServer()
    server.on("GET", LIST, list as never)
    const rendered = renderAuthoringRoutes({
        initialEntry: `/app/c1/characters/${characterId}/public-profile`,
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] }],
        }),
        routes: [
            {
                path: "/app/:campaignId/characters/:characterId/public-profile",
                element: <CharacterRevelationsSection campaignId="c1" characterId={characterId} onGone={onGone} />,
            },
        ],
    })
    return { server, onGone, ...rendered }
}

describe("CharacterRevelationsSection: list (T01)", () => {
    it("V2: an empty list says nobody has been revealed to", async () => {
        const { server } = setup()
        expect(await screen.findByText("This character hasn't been revealed to anyone.")).toBeInTheDocument()
        expect(server.callsTo("GET", LIST)).toHaveLength(1)
        expect(screen.queryByRole("heading", { name: "Visible to" })).not.toBeInTheDocument()
    })

    it("V3: live and ended groups, each newest first, with creator, date, source and end reason", async () => {
        setup(
            read([
                entry({ character_revelation_id: "r-old", target_member_name: "Older Live", created_at: "2026-11-01T10:00:00Z" }),
                entry({ character_revelation_id: "r-new", target_member_name: "Newer Live", created_at: "2026-11-10T10:00:00Z", authority_source: "delegation" }),
                entry({
                    character_revelation_id: "r-end-1",
                    target_member_name: "Revoked One",
                    created_at: "2026-10-01T10:00:00Z",
                    live: false,
                    ended_at: "2026-10-05T10:00:00Z",
                    end_reason: "revoked",
                }),
                entry({
                    character_revelation_id: "r-end-2",
                    audience_kind: "access_group",
                    target_member_name: null,
                    target_access_group_name: "Night Watch",
                    created_at: "2026-10-02T10:00:00Z",
                    live: false,
                    ended_at: "2026-10-06T10:00:00Z",
                    end_reason: "access_group_deactivated",
                }),
                entry({
                    character_revelation_id: "r-end-3",
                    target_member_name: "Left One",
                    created_at: "2026-09-01T10:00:00Z",
                    live: false,
                    ended_at: "2026-09-05T10:00:00Z",
                    end_reason: "target_membership_ended",
                }),
            ]),
        )
        const visible = within(await screen.findByRole("region", { name: "Visible to" }))
        const live = visible.getAllByRole("listitem").map((li) => li.textContent ?? "")
        expect(live[0]).toContain("Newer Live")
        expect(live[0]).toContain("Delegated GM")
        expect(live[1]).toContain("Older Live")
        expect(live[0]).toContain("Revealed by Gina GM")
        expect(live[1]).toContain("Owner")
        const ended = within(screen.getByRole("region", { name: "Ended" }))
        const rows = ended.getAllByRole("listitem").map((li) => li.textContent ?? "")
        expect(rows[0]).toContain("Group: Night Watch")
        expect(rows[0]).toContain("Group deactivated")
        expect(rows[1]).toContain("Revoked One")
        expect(rows[1]).toContain("Revoked")
        expect(rows[2]).toContain("Membership ended")
        expect(visible.queryByText(/Ended/)).not.toBeInTheDocument()
    })

    it("V4: the four audience labels, with the snapshot members of a campaign_current revelation", async () => {
        setup(
            read([
                entry({ character_revelation_id: "a", audience_kind: "campaign_current_and_future", target_member_name: null, created_at: "2026-11-04T10:00:00Z" }),
                entry({
                    character_revelation_id: "b",
                    audience_kind: "campaign_current",
                    target_member_name: null,
                    created_at: "2026-11-03T10:00:00Z",
                    audience_size: 2,
                    snapshot_members: [
                        { campaign_membership_id: "x1", display_name: "Stays Here", added_at: "2026-11-03T10:00:00Z", removed_at: null, removal_reason: null },
                        { campaign_membership_id: "x2", display_name: "Went Away", added_at: "2026-11-03T10:00:00Z", removed_at: "2026-11-06T10:00:00Z", removal_reason: "membership_ended" },
                    ],
                }),
                entry({ character_revelation_id: "c", audience_kind: "access_group", target_member_name: null, target_access_group_name: "The Band", created_at: "2026-11-02T10:00:00Z" }),
                entry({ character_revelation_id: "d", target_member_name: "Pia Player", created_at: "2026-11-01T10:00:00Z" }),
            ]),
        )
        expect(await screen.findByText("All campaign members, including future ones")).toBeInTheDocument()
        expect(screen.getByText("Campaign members at the time (2)")).toBeInTheDocument()
        expect(screen.getByText("Group: The Band")).toBeInTheDocument()
        expect(screen.getByText("Pia Player")).toBeInTheDocument()
        const summary = screen.getByText("Members at the time")
        expect(summary.closest("details")).not.toBeNull()
        expect(within(summary.closest("details")!).getByText("Stays Here")).toBeInTheDocument()
        expect(screen.getByText("Went Away (Left the campaign)")).toBeInTheDocument()
    })

    it("V5: no id and no reason is rendered", async () => {
        setup(read([entry({ character_revelation_id: "REV-ID-0000", target_campaign_membership_id: "MEMBER-ID-1111", created_by_membership_id: "CREATOR-ID-2222" })]))
        await screen.findByText("Pia Player")
        for (const hidden of ["REV-ID-0000", "MEMBER-ID-1111", "CREATOR-ID-2222", "ch1"]) {
            expect(document.body).not.toHaveTextContent(hidden)
        }
    })

    it("V6: the list answering 404 removes every name and calls onGone once", async () => {
        const { onGone } = setup({ status: 404, body: { error: { code: "not_found", message: "SERVER-SECRET" } } })
        expect(await screen.findByText("The revelations of this character are not available to you.")).toBeInTheDocument()
        await vi.waitFor(() => expect(onGone).toHaveBeenCalledTimes(1))
        expect(screen.queryByText(/Pia Player|SERVER-SECRET/)).not.toBeInTheDocument()
    })

    it("V7: a failed read shows Try again; a kept list stays, marked out of date, and a retry only reads", async () => {
        const { server } = setup({ status: 500, body: { error: { code: "server_error", message: "x" } } })
        const notice = await screen.findByRole("alert")
        expect(notice).toHaveTextContent(/The latest revelations could not be loaded/)
        server.on("GET", LIST, () => read([entry()]))
        fireEvent.click(within(notice).getByRole("button", { name: "Try again" }))
        expect(await screen.findByText("Pia Player")).toBeInTheDocument()
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    })

    it("V8: a late list for another character is never shown under this one", async () => {
        const server = installMockServer()
        let answerFirst: (value: { body: object }) => void = () => undefined
        server.on("GET", LIST, () => new Promise((resolve) => (answerFirst = resolve)))
        server.on("GET", "/campaigns/c1/characters/ch2/revelations", () => read([entry({ target_member_name: "Second Character Member" })]))
        const { router } = renderAuthoringRoutes({
            initialEntry: "/app/c1/characters/ch1/public-profile",
            routes: [
                {
                    path: "/app/:campaignId/characters/:characterId/public-profile",
                    element: <Scoped />,
                },
            ],
        })
        await vi.waitFor(() => expect(server.callsTo("GET", LIST)).toHaveLength(1))
        await act(async () => {
            void router.navigate("/app/c1/characters/ch2/public-profile")
        })
        expect(await screen.findByText("Second Character Member")).toBeInTheDocument()
        await act(async () => answerFirst(read([entry({ target_member_name: "First Character Member" })])))
        expect(screen.queryByText("First Character Member")).not.toBeInTheDocument()
        expect(screen.getByText("Second Character Member")).toBeInTheDocument()
    })
})

import { useParams } from "react-router"

function Scoped() {
    const { characterId = "" } = useParams()
    return <CharacterRevelationsSection key={characterId} campaignId="c1" characterId={characterId} onGone={() => undefined} />
}

describe("V10: no other surface asks for revelations", () => {
    it("only the section and its API module name the revelations path", () => {
        const sources = import.meta.glob(["../../**/*.ts", "../../**/*.tsx", "!../../**/*.test.ts", "!../../**/*.test.tsx"], {
            query: "?raw",
            import: "default",
            eager: true,
        }) as Record<string, string>
        const naming = Object.entries(sources)
            .filter(([, text]) => /revelationsPath|\/revelations/.test(text))
            .map(([file]) => file.split("/").pop() ?? file)
            .sort()
        expect(naming).toEqual(
            [
                "characterRevelations.ts", // api/ and types/ (two files of this name)
                "characterRevelations.ts",
                "CharacterRevelationsSection.tsx",
            ].sort(),
        )
    })
})
