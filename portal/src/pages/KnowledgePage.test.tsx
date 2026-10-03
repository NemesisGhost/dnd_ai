import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { AuthorizedParty } from "../types/bootstrap"
import type { KnowledgeView } from "../types/knowledge"
import { KnowledgePage } from "./KnowledgePage"

const { accessOverviewStateRef } = vi.hoisted(() => ({
    accessOverviewStateRef: { current: { status: "loading" } as Record<string, unknown> },
}))

vi.mock("../hooks/useAccessOverview", () => ({
    useAccessOverview: () => ({ state: accessOverviewStateRef.current, retry: vi.fn() }),
}))

interface RenderOverrides {
    campaignId?: string
    view?: KnowledgeView
    query?: string
    partyId?: string | null
    parties?: AuthorizedParty[]
    onViewChange?: (view: KnowledgeView) => void
    onQueryChange?: (query: string) => void
    onPartyChange?: (partyId: string | null) => void
    children?: React.ReactNode
}

const authorizedParties: AuthorizedParty[] = [
    {
        party_id: "party-primary",
        party_name: "The Adventuring Party",
    },
    {
        party_id: "party-council",
        party_name: "The Merchant Council",
    },
]

function renderPage(overrides: RenderOverrides = {}) {
    const props = {
        campaignId: "test-campaign",
        view: "known" as KnowledgeView,
        query: "",
        partyId: null,
        parties: authorizedParties,
        onViewChange: vi.fn(),
        onQueryChange: vi.fn(),
        onPartyChange: vi.fn(),
        children: <p>Knowledge results go here.</p>,
        ...overrides,
    }

    const view = render(<KnowledgePage {...props} />)

    return { ...props, ...view }
}

describe("KnowledgePage", () => {
    it("renders the heading and labelled search controls", () => {
        renderPage()

        expect(
            screen.getByRole("heading", {
                name: "Knowledge",
                level: 1,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("search", {
                name: "Knowledge search",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("searchbox", {
                name: "Search",
            }),
        ).toHaveValue("")

        expect(
            screen.getByRole("combobox", {
                name: "View",
            }),
        ).toHaveValue("known")
    })

    it("offers all six server-defined knowledge views", () => {
        renderPage()

        const viewSelect =
            screen.getByRole("combobox", {
                name: "View",
            })

        expect(
            Array.from(viewSelect.querySelectorAll("option")).map(
                (option) => option.textContent,
            ),
        ).toEqual([
            "Known",
            "Rumors",
            "Party shared",
            "Character private",
            "Recent",
            "Public",
        ])
    })

    it("renders the supplied children", () => {
        renderPage({
            children: <p>Knowledge results go here.</p>,
        })

        expect(
            screen.getByText("Knowledge results go here."),
        ).toBeInTheDocument()
    })

    it("is a controlled search input: it reflects the query prop and reports every change immediately", () => {
        const onQueryChange = vi.fn()

        renderPage({
            query: "ossuary",
            onQueryChange,
        })

        const searchInput =
            screen.getByRole("searchbox", {
                name: "Search",
            })

        expect(searchInput).toHaveValue("ossuary")

        fireEvent.change(searchInput, {
            target: {
                value: "shard",
            },
        })

        // KnowledgePage does not debounce or hold its own copy of the
        // value: it reports the raw change and waits for a new `query`
        // prop.
        expect(onQueryChange).toHaveBeenCalledTimes(1)
        expect(onQueryChange).toHaveBeenCalledWith(
            "shard",
        )
        expect(searchInput).toHaveValue("ossuary")
    })

    it("reports view selections", () => {
        const onViewChange = vi.fn()

        renderPage({
            view: "known",
            onViewChange,
        })

        const viewSelect =
            screen.getByRole("combobox", {
                name: "View",
            })

        expect(viewSelect).toHaveValue("known")

        fireEvent.change(viewSelect, {
            target: {
                value: "rumors",
            },
        })

        expect(onViewChange).toHaveBeenLastCalledWith(
            "rumors",
        )
    })

    it("lists the authorized parties and reports selections, mapping the default option to null", () => {
        const onPartyChange = vi.fn()

        renderPage({
            partyId: "party-primary",
            parties: authorizedParties,
            onPartyChange,
        })

        const partySelect =
            screen.getByRole("combobox", {
                name: "Party",
            })

        expect(partySelect).toBeEnabled()
        expect(partySelect).toHaveValue("party-primary")

        expect(
            screen.getByRole("option", {
                name: "The Adventuring Party",
                selected: true,
            }),
        ).toBeInTheDocument()

        fireEvent.change(partySelect, {
            target: {
                value: "party-council",
            },
        })

        expect(onPartyChange).toHaveBeenLastCalledWith(
            "party-council",
        )

        fireEvent.change(partySelect, {
            target: {
                value: "",
            },
        })

        expect(onPartyChange).toHaveBeenLastCalledWith(
            null,
        )
    })

    it("disables the party selector when no parties are authorized", () => {
        const onPartyChange = vi.fn()

        renderPage({
            partyId: null,
            parties: [],
            onPartyChange,
        })

        const partySelect =
            screen.getByRole("combobox", {
                name: "Party",
            })

        expect(partySelect).toBeDisabled()
        expect(partySelect).toHaveValue("")

        expect(
            screen.getByRole("option", {
                name: "No party available",
            }),
        ).toBeDisabled()

        expect(onPartyChange).not.toHaveBeenCalled()
    })

    it("keeps the search input mounted and focused when its children change", () => {
        const { rerender } = render(
            <KnowledgePage
                campaignId="test-campaign"
                view="known"
                query=""
                partyId={null}
                parties={authorizedParties}
                onViewChange={vi.fn()}
                onQueryChange={vi.fn()}
                onPartyChange={vi.fn()}
            >
                <p>Loading knowledge results.</p>
            </KnowledgePage>,
        )

        const searchInput =
            screen.getByRole("searchbox", {
                name: "Search",
            })

        searchInput.focus()
        expect(searchInput).toHaveFocus()

        rerender(
            <KnowledgePage
                campaignId="test-campaign"
                view="known"
                query="g"
                partyId={null}
                parties={authorizedParties}
                onViewChange={vi.fn()}
                onQueryChange={vi.fn()}
                onPartyChange={vi.fn()}
            >
                <p>Knowledge results go here.</p>
            </KnowledgePage>,
        )

        expect(
            screen.getByRole("searchbox", {
                name: "Search",
            }),
        ).toHaveFocus()

        expect(
            screen.getByText("Knowledge results go here."),
        ).toBeInTheDocument()
    })
})

describe("KnowledgePage — audience preview (Phase 13E-B manual-acceptance fix)", () => {
    it("shows 'Preview as member' to a GM/admin campaign membership", () => {
        accessOverviewStateRef.current = {
            status: "success",
            overview: {
                members: [
                    {
                        campaign_membership_id: "membership-a",
                        display_name: "Player One",
                        user_id: "user-1",
                    },
                ],
                assignable_roles: [],
                assignable_characters: [],
                assignable_relationship_types: [],
                grantable_resource_capabilities: [],
                access_groups: [],
            },
        }

        render(
            <SessionContext.Provider
                value={{
                    state: {
                        status: "authenticated",
                        bootstrap: {
                            ...sessionBootstrapFixture,
                            campaigns: sessionBootstrapFixture.campaigns.map((campaign) => ({
                                ...campaign,
                                campaign_id: "test-campaign",
                                capabilities: ["access.manage"],
                            })),
                        },
                    },
                    reload: vi.fn(), refresh: vi.fn(),
                }}
            >
                <KnowledgePage
                    campaignId="test-campaign"
                    view="known"
                    query=""
                    partyId={null}
                    parties={authorizedParties}
                    onViewChange={vi.fn()}
                    onQueryChange={vi.fn()}
                    onPartyChange={vi.fn()}
                >
                    <p>Knowledge results go here.</p>
                </KnowledgePage>
            </SessionContext.Provider>,
        )

        expect(screen.getByRole("button", { name: "Preview as member" })).toBeInTheDocument()
    })

    it("does not show 'Preview as member' without access.manage", () => {
        renderPage()

        expect(
            screen.queryByRole("button", { name: "Preview as member" }),
        ).not.toBeInTheDocument()
    })
})
