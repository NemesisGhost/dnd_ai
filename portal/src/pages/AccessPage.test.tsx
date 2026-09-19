import {
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react"
import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { CampaignAccessOverview } from "../types/accessOverview"
import { AccessPage } from "./AccessPage"

const campaignId = sessionBootstrapFixture.campaigns[0].campaign_id
const campaignName = sessionBootstrapFixture.campaigns[0].campaign_name

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
                    membership_role_id:
                        "6b1f7e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
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
        {
            campaign_membership_id:
                "2b7f3e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            display_name: "Multi Role Member",
            status_code: "active",
            status_display_name: "Active",
            joined_at: "2026-01-05T00:00:00Z",
            roles: [
                {
                    membership_role_id:
                        "3c8f4e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                    role_id:
                        "7c2f8e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                    code: "campaign_owner",
                    display_name: "Campaign Owner",
                },
                {
                    membership_role_id:
                        "4d9f5e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                    role_id:
                        "4a2f8e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                    code: "rules_curator",
                    display_name: "Rules Curator",
                },
            ],
            character_relationships: [],
            grants: [],
        },
    ],
    assignable_roles: [
        {
            role_id: "7c2f8e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            code: "campaign_owner",
            display_name: "Campaign Owner",
        },
        {
            role_id: "4a2f8e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            code: "rules_curator",
            display_name: "Rules Curator",
        },
    ],
}

function renderPage(
    overview: CampaignAccessOverview,
    onChanged: (message: string) => void = vi.fn(),
    onMutationStart: () => void = vi.fn(),
) {
    return render(
        <SessionContext.Provider
            value={{
                state: {
                    status: "authenticated",
                    bootstrap: sessionBootstrapFixture,
                },
                reload: vi.fn(),
            }}
        >
            <AccessPage
                campaignId={campaignId}
                overview={overview}
                onChanged={onChanged}
                onMutationStart={onMutationStart}
            />
        </SessionContext.Provider>,
    )
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("AccessPage", () => {
    it("renders exactly one page-level heading", () => {
        renderPage(fullOverview)

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
        renderPage(fullOverview)

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
        const { container } = renderPage(fullOverview)

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
        const { container } = renderPage(fullOverview)

        const uuidPattern =
            /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i

        expect(
            uuidPattern.test(container.textContent ?? ""),
        ).toBe(false)
    })

    it("shows a deliberate per-member empty state for a member with no roles, relationships, or grants", () => {
        renderPage(fullOverview)

        expect(
            screen.getByText("No roles assigned."),
        ).toBeInTheDocument()

        expect(
            screen.getAllByText("No character relationships.").length,
        ).toBeGreaterThan(0)

        expect(
            screen.getAllByText("No explicit grants.").length,
        ).toBeGreaterThan(0)
    })

    it("shows a deliberate empty state when the campaign has no manageable access records", () => {
        renderPage({ members: [], assignable_roles: [] })

        expect(
            screen.getByText(
                "No campaign members are currently recorded.",
            ),
        ).toBeInTheDocument()
    })

    it("renders each member as a collapsed-by-default disclosure element", () => {
        const { container } = renderPage(fullOverview)

        const detailsElements =
            container.querySelectorAll("details")

        expect(detailsElements.length).toBe(3)
        detailsElements.forEach((details) => {
            expect(details.open).toBe(false)
        })
    })

    it("uses a semantic list for the member collection", () => {
        renderPage(fullOverview)

        expect(
            screen.getAllByRole("list").length,
        ).toBeGreaterThan(0)
    })

    it("exposes an accessible role-edit action for each eligible role", () => {
        renderPage(fullOverview)

        // One role from the single-role member plus two from the
        // multi-role member = three independent "Change role" triggers —
        // each role assignment gets its own control, never one per member.
        expect(
            screen.getAllByRole("button", { name: "Change role" }),
        ).toHaveLength(3)
    })

    it("does not expose an actionable role control when no role is assignable", () => {
        renderPage({
            ...fullOverview,
            assignable_roles: [],
        })

        expect(
            screen.queryByRole("button", { name: "Change role" }),
        ).not.toBeInTheDocument()
    })

    it("labels the role-edit control with the member and campaign context, and offers only authorized choices", () => {
        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Change role" })[0],
        )

        const select = screen.getByLabelText(
            `Change Aria the GM's Campaign Owner role in ${campaignName}`,
        )
        expect(select).toBeInTheDocument()

        const options = Array.from(
            select.querySelectorAll("option"),
        ).map((option) => option.textContent)
        expect(options).toEqual([
            "Campaign Owner",
            "Rules Curator",
        ])
    })

    it("disables Save until the selection changes away from the current role", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Change role" })[0],
        )

        const saveButton = screen.getByRole("button", { name: "Save" })
        expect(saveButton).toBeDisabled()

        fireEvent.click(saveButton)
        expect(fetchMock).not.toHaveBeenCalled()

        fireEvent.change(screen.getByRole("combobox"), {
            target: {
                value: "4a2f8e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            },
        })
        expect(saveButton).toBeEnabled()

        fireEvent.change(screen.getByRole("combobox"), {
            target: {
                value: "7c2f8e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            },
        })
        expect(saveButton).toBeDisabled()
    })

    it("requires an explicit Save action and never submits on selection change alone", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Change role" })[0],
        )

        const select = screen.getByRole("combobox")
        fireEvent.change(select, {
            target: {
                value: "4a2f8e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            },
        })

        expect(fetchMock).not.toHaveBeenCalled()
    })

    it("cancel closes the editor and makes no request", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Change role" })[0],
        )
        fireEvent.click(
            screen.getByRole("button", { name: "Cancel" }),
        )

        expect(fetchMock).not.toHaveBeenCalled()
        expect(
            screen.queryByRole("combobox"),
        ).not.toBeInTheDocument()
        expect(
            screen.getAllByRole("button", { name: "Change role" })
                .length,
        ).toBeGreaterThan(0)
    })

    it("announces pending, then success, and refreshes the authoritative overview after a successful save", async () => {
        const onChanged = vi.fn()
        let resolveResponse!: (response: Response) => void
        const fetchMock = vi.fn().mockReturnValue(
            new Promise<Response>((resolve) => {
                resolveResponse = resolve
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview, onChanged)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Change role" })[0],
        )
        fireEvent.change(screen.getByRole("combobox"), {
            target: {
                value: "4a2f8e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            },
        })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))

        await waitFor(() => {
            expect(
                screen.getByText("Saving role change…"),
            ).toBeInTheDocument()
        })
        // Existing role text remains visible — no optimistic replacement.
        expect(
            screen.getAllByText("Campaign Owner").length,
        ).toBeGreaterThan(0)
        expect(onChanged).not.toHaveBeenCalled()

        resolveResponse(
            new Response(
                JSON.stringify({
                    membership_role_id: "new-membership-role",
                }),
                {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )

        await waitFor(() => {
            expect(
                screen.getByText("Role updated."),
            ).toBeInTheDocument()
        })
        expect(onChanged).toHaveBeenCalledTimes(1)
    })

    it("announces a denied failure without exposing sensitive details", async () => {
        const fetchMock = vi
            .fn()
            .mockResolvedValue(new Response(null, { status: 403 }))
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Change role" })[0],
        )
        fireEvent.change(screen.getByRole("combobox"), {
            target: {
                value: "4a2f8e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            },
        })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))

        expect(
            await screen.findByText(
                "You do not have permission to make this change.",
            ),
        ).toBeInTheDocument()
    })

    it("renders no unrelated mutation controls", () => {
        renderPage(fullOverview)

        const buttonNames = screen
            .getAllByRole("button")
            .map((button) => button.textContent)

        const allowedNames = new Set([
            "Change role",
            "Add role",
            "Remove role",
        ])
        buttonNames.forEach((name) => {
            expect(allowedNames.has(name ?? "")).toBe(true)
        })
    })
})

describe("AccessPage — add role (Phase 13E-B checkpoint 2)", () => {
    it("offers Add role only for a member with at least one unheld assignable role", () => {
        renderPage(fullOverview)

        // Aria (holds campaign_owner only) and Quiet Observer (holds none)
        // each have an unheld role remaining; Multi Role Member already
        // holds both assignable roles and gets no control.
        expect(
            screen.getAllByRole("button", { name: "Add role" }),
        ).toHaveLength(2)
    })

    it("excludes a member's already-held roles from the Add-role choices", () => {
        renderPage(fullOverview)

        // Aria the GM already holds Campaign Owner — only Rules Curator
        // remains offered.
        fireEvent.click(
            screen.getAllByRole("button", { name: "Add role" })[0],
        )

        const select = screen.getByLabelText(
            `Add a role for Aria the GM in ${campaignName}`,
        )
        const options = Array.from(
            select.querySelectorAll("option"),
        ).map((option) => option.textContent)
        expect(options).toEqual(["Rules Curator"])
    })

    it("requires an explicit Add action and never submits on selection alone", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Add role" })[0],
        )

        expect(fetchMock).not.toHaveBeenCalled()
    })

    it("cancel closes the Add-role control and makes no request", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Add role" })[0],
        )
        fireEvent.click(
            screen.getByRole("button", { name: "Cancel" }),
        )

        expect(fetchMock).not.toHaveBeenCalled()
        expect(
            screen.queryByRole("combobox"),
        ).not.toBeInTheDocument()
    })

    it("announces pending, then success, refreshes via onChanged, and never optimistically shows the new role", async () => {
        const onChanged = vi.fn()
        let resolveResponse!: (response: Response) => void
        const fetchMock = vi.fn().mockReturnValue(
            new Promise<Response>((resolve) => {
                resolveResponse = resolve
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview, onChanged)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Add role" })[0],
        )
        fireEvent.click(screen.getByRole("button", { name: "Add" }))

        await waitFor(() => {
            expect(
                screen.getByText("Adding role…"),
            ).toBeInTheDocument()
        })
        expect(onChanged).not.toHaveBeenCalled()

        resolveResponse(
            new Response(
                JSON.stringify({
                    membership_role_id: "new-membership-role",
                }),
                {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )

        await waitFor(() => {
            expect(
                screen.getByText("Role added."),
            ).toBeInTheDocument()
        })
        expect(onChanged).toHaveBeenCalledWith("Role added.")
    })

    it("announces a denied failure without exposing sensitive details", async () => {
        const fetchMock = vi
            .fn()
            .mockResolvedValue(new Response(null, { status: 403 }))
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Add role" })[0],
        )
        fireEvent.click(screen.getByRole("button", { name: "Add" }))

        expect(
            await screen.findByText(
                "You do not have permission to make this change.",
            ),
        ).toBeInTheDocument()
    })
})

describe("AccessPage — revoke role (Phase 13E-B checkpoint 2)", () => {
    it("exposes an accessible revoke action for each eligible role", () => {
        renderPage(fullOverview)

        expect(
            screen.getAllByRole("button", { name: "Remove role" }),
        ).toHaveLength(3)
    })

    it("requires an explicit confirmation naming the member and role, and makes no request until confirmed", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Remove role" })[0],
        )

        expect(
            screen.getByText(
                "Remove Aria the GM's Campaign Owner role?",
            ),
        ).toBeInTheDocument()
        expect(fetchMock).not.toHaveBeenCalled()

        expect(
            screen.getByRole("button", { name: "Confirm" }),
        ).toBeInTheDocument()
        expect(
            screen.getByRole("button", { name: "Cancel" }),
        ).toBeInTheDocument()
    })

    it("cancel closes the confirmation and makes no request", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Remove role" })[0],
        )
        fireEvent.click(
            screen.getByRole("button", { name: "Cancel" }),
        )

        expect(fetchMock).not.toHaveBeenCalled()
        expect(
            screen.queryByRole("button", { name: "Confirm" }),
        ).not.toBeInTheDocument()
    })

    it("announces pending, then success, refreshes via onChanged, and never optimistically removes the role", async () => {
        const onChanged = vi.fn()
        let resolveResponse!: (response: Response) => void
        const fetchMock = vi.fn().mockReturnValue(
            new Promise<Response>((resolve) => {
                resolveResponse = resolve
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview, onChanged)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Remove role" })[0],
        )
        fireEvent.click(
            screen.getByRole("button", { name: "Confirm" }),
        )

        await waitFor(() => {
            expect(
                screen.getByText("Removing role…"),
            ).toBeInTheDocument()
        })
        // Still visible — no optimistic removal before server confirmation.
        expect(
            screen.getAllByText("Campaign Owner").length,
        ).toBeGreaterThan(0)
        expect(onChanged).not.toHaveBeenCalled()

        resolveResponse(
            new Response(
                JSON.stringify({
                    membership_role_id:
                        fullOverview.members[0].roles[0]
                            .membership_role_id,
                }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )

        await waitFor(() => {
            expect(
                screen.getByText("Role removed."),
            ).toBeInTheDocument()
        })
        expect(onChanged).toHaveBeenCalledWith("Role removed.")
    })

    it("announces a denied failure without exposing sensitive details", async () => {
        const fetchMock = vi
            .fn()
            .mockResolvedValue(new Response(null, { status: 403 }))
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Remove role" })[0],
        )
        fireEvent.click(
            screen.getByRole("button", { name: "Confirm" }),
        )

        expect(
            await screen.findByText(
                "You do not have permission to make this change.",
            ),
        ).toBeInTheDocument()
    })

    it("does not display any internal identifier as visible text in the confirmation", () => {
        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Remove role" })[0],
        )

        const uuidPattern =
            /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i
        expect(
            uuidPattern.test(
                screen.getByText(
                    "Remove Aria the GM's Campaign Owner role?",
                ).textContent ?? "",
            ),
        ).toBe(false)
    })
})

describe("AccessPage — onMutationStart (persistent-announcement clearing)", () => {
    it("calls onMutationStart immediately when a role change is submitted, never merely on opening the editor", () => {
        const onMutationStart = vi.fn()
        vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})))

        renderPage(fullOverview, vi.fn(), onMutationStart)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Change role" })[0],
        )
        expect(onMutationStart).not.toHaveBeenCalled()

        fireEvent.change(screen.getByRole("combobox"), {
            target: {
                value: "4a2f8e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            },
        })
        expect(onMutationStart).not.toHaveBeenCalled()

        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        expect(onMutationStart).toHaveBeenCalledTimes(1)
    })

    it("calls onMutationStart immediately when a role is added, never merely on opening the control", () => {
        const onMutationStart = vi.fn()
        vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})))

        renderPage(fullOverview, vi.fn(), onMutationStart)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Add role" })[0],
        )
        expect(onMutationStart).not.toHaveBeenCalled()

        fireEvent.click(screen.getByRole("button", { name: "Add" }))
        expect(onMutationStart).toHaveBeenCalledTimes(1)
    })

    it("calls onMutationStart immediately when a role revocation is confirmed, never merely on opening the confirmation", () => {
        const onMutationStart = vi.fn()
        vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})))

        renderPage(fullOverview, vi.fn(), onMutationStart)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Remove role" })[0],
        )
        expect(onMutationStart).not.toHaveBeenCalled()

        fireEvent.click(screen.getByRole("button", { name: "Confirm" }))
        expect(onMutationStart).toHaveBeenCalledTimes(1)
    })

    it("does not call onMutationStart on Cancel", () => {
        const onMutationStart = vi.fn()
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview, vi.fn(), onMutationStart)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Change role" })[0],
        )
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))

        expect(onMutationStart).not.toHaveBeenCalled()
        expect(fetchMock).not.toHaveBeenCalled()
    })
})
