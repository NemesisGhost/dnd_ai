import {
    fireEvent,
    render,
    screen,
    waitFor,
    within,
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
            user_id: sessionBootstrapFixture.user.user_id,
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
                    target_id:
                        "9e4f0e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                    target_display_name: "Kestrel Vane",
                    reason: "Visibility for the shared scene",
                    granted_at: "2026-01-03T00:00:00Z",
                    expires_at: null,
                },
            ],
        },
        {
            campaign_membership_id:
                "1a6f2e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            user_id: "9a6f2e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
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
            user_id: "8b7f3e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
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
    assignable_characters: [
        {
            character_id: "9e4f0e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            display_name: "Kestrel Vane",
        },
        {
            character_id: "1f6a2e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            display_name: "Bram Ferro",
        },
    ],
    assignable_relationship_types: [
        {
            character_relationship_type_id:
                "2a7b3e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            code: "primary_controller",
            display_name: "Primary Controller",
        },
        {
            character_relationship_type_id:
                "3b8c4e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            code: "viewer",
            display_name: "Viewer",
        },
        {
            character_relationship_type_id:
                "4c9d5e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            code: "portrayer",
            display_name: "Portrayer / Assistant GM",
        },
    ],
    grantable_resource_capabilities: [
        {
            capability_id: "5d0e6e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            code: "character.view_full",
            display_name: "View Character Full Detail",
            target_type: "character",
        },
    ],
    access_groups: [],
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
            "(Allow) on Kestrel Vane",
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
            screen.getAllByText("No direct resource access.").length,
        ).toBeGreaterThan(0)
    })

    it("shows a deliberate empty state when the campaign has no manageable access records", () => {
        renderPage({
            members: [],
            assignable_roles: [],
            assignable_characters: [],
            assignable_relationship_types: [],
            grantable_resource_capabilities: [],
            access_groups: [],
        })

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
            "Add campaign member",
            "Remove member",
            "Change type",
            "Revoke relationship",
            "Add character relationship",
            "Add direct resource access",
            "Revoke access",
            "Create access group",
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

describe("AccessPage — add character relationship (character-relationship-management checkpoint)", () => {
    it("exposes Add character relationship for every member when characters and types are assignable", () => {
        renderPage(fullOverview)

        expect(
            screen.getAllByRole("button", {
                name: "Add character relationship",
            }),
        ).toHaveLength(3)
    })

    it("does not expose the add control when no character or no relationship type is assignable", () => {
        renderPage({
            ...fullOverview,
            assignable_characters: [],
        })

        expect(
            screen.queryByRole("button", {
                name: "Add character relationship",
            }),
        ).not.toBeInTheDocument()
    })

    it("offers only server-authoritative character choices, and narrows type choices to exclude combinations already active for the selected character", () => {
        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", {
                name: "Add character relationship",
            })[0],
        )

        const characterSelect = screen.getByLabelText(
            `Add a character relationship for Aria the GM in ${campaignName}`,
        )
        const characterOptions = Array.from(
            characterSelect.querySelectorAll("option"),
        ).map((option) => option.textContent)
        expect(characterOptions).toEqual([
            "Kestrel Vane",
            "Bram Ferro",
        ])

        // Aria already holds Primary Controller for Kestrel Vane (the
        // default-selected character) — only the remaining two assignable
        // types are offered, never the already-active one.
        const typeSelect = screen.getByLabelText("Relationship type")
        const typeOptions = Array.from(
            typeSelect.querySelectorAll("option"),
        ).map((option) => option.textContent)
        expect(typeOptions).toEqual([
            "Viewer",
            "Portrayer / Assistant GM",
        ])
    })

    it("requires an explicit Add action and never submits on selection alone", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", {
                name: "Add character relationship",
            })[0],
        )

        expect(fetchMock).not.toHaveBeenCalled()
    })

    it("cancel closes the Add-relationship control and makes no request", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", {
                name: "Add character relationship",
            })[0],
        )
        fireEvent.click(
            screen.getByRole("button", { name: "Cancel" }),
        )

        expect(fetchMock).not.toHaveBeenCalled()
        expect(
            screen.queryByLabelText("Relationship type"),
        ).not.toBeInTheDocument()
    })

    it("announces pending, then success, refreshes via onChanged, and never optimistically shows the new relationship", async () => {
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
            screen.getAllByRole("button", {
                name: "Add character relationship",
            })[0],
        )
        fireEvent.click(screen.getByRole("button", { name: "Add" }))

        await waitFor(() => {
            expect(
                screen.getByText("Adding character relationship…"),
            ).toBeInTheDocument()
        })
        expect(onChanged).not.toHaveBeenCalled()

        resolveResponse(
            new Response(
                JSON.stringify({
                    membership_character_relationship_id:
                        "new-relationship-id",
                }),
                {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )

        await waitFor(() => {
            expect(
                screen.getByText("Character relationship added."),
            ).toBeInTheDocument()
        })
        expect(onChanged).toHaveBeenCalledWith(
            "Character relationship added.",
        )
    })

    it("announces a denied failure without exposing sensitive details", async () => {
        const fetchMock = vi
            .fn()
            .mockResolvedValue(new Response(null, { status: 403 }))
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", {
                name: "Add character relationship",
            })[0],
        )
        fireEvent.click(screen.getByRole("button", { name: "Add" }))

        expect(
            await screen.findByText(
                "You do not have permission to make this change.",
            ),
        ).toBeInTheDocument()
    })
})

describe("AccessPage — change relationship type (character-relationship-management checkpoint)", () => {
    it("exposes an accessible change-type action for each eligible character relationship", () => {
        renderPage(fullOverview)

        // Only Aria the GM holds one active character relationship.
        expect(
            screen.getAllByRole("button", { name: "Change type" }),
        ).toHaveLength(1)
    })

    it("labels the change control with the member and character context, and offers only authorized type choices", () => {
        renderPage(fullOverview)

        fireEvent.click(
            screen.getByRole("button", { name: "Change type" }),
        )

        const select = screen.getByLabelText(
            `Change Aria the GM's Kestrel Vane relationship type in ${campaignName}`,
        )
        const options = Array.from(
            select.querySelectorAll("option"),
        ).map((option) => option.textContent)
        expect(options).toEqual([
            "Primary Controller",
            "Viewer",
            "Portrayer / Assistant GM",
        ])
    })

    it("disables Save until the selection changes away from the current type", () => {
        renderPage(fullOverview)

        fireEvent.click(
            screen.getByRole("button", { name: "Change type" }),
        )

        const saveButton = screen.getByRole("button", { name: "Save" })
        expect(saveButton).toBeDisabled()

        fireEvent.change(screen.getByRole("combobox"), {
            target: {
                value: "3b8c4e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            },
        })
        expect(saveButton).toBeEnabled()
    })

    it("cancel closes the editor and makes no request", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getByRole("button", { name: "Change type" }),
        )
        fireEvent.click(
            screen.getByRole("button", { name: "Cancel" }),
        )

        expect(fetchMock).not.toHaveBeenCalled()
        expect(
            screen.queryByRole("combobox"),
        ).not.toBeInTheDocument()
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
            screen.getByRole("button", { name: "Change type" }),
        )
        fireEvent.change(screen.getByRole("combobox"), {
            target: {
                value: "3b8c4e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            },
        })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))

        await waitFor(() => {
            expect(
                screen.getByText("Saving relationship type change…"),
            ).toBeInTheDocument()
        })
        expect(onChanged).not.toHaveBeenCalled()

        resolveResponse(
            new Response(
                JSON.stringify({
                    membership_character_relationship_id:
                        "new-relationship-id",
                }),
                {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )

        await waitFor(() => {
            expect(
                screen.getByText("Relationship type updated."),
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
            screen.getByRole("button", { name: "Change type" }),
        )
        fireEvent.change(screen.getByRole("combobox"), {
            target: {
                value: "3b8c4e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
            },
        })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))

        expect(
            await screen.findByText(
                "You do not have permission to make this change.",
            ),
        ).toBeInTheDocument()
    })
})

describe("AccessPage — revoke character relationship (character-relationship-management checkpoint)", () => {
    it("exposes an accessible revoke action for each eligible character relationship", () => {
        renderPage(fullOverview)

        expect(
            screen.getAllByRole("button", {
                name: "Revoke relationship",
            }),
        ).toHaveLength(1)
    })

    it("requires an explicit confirmation naming the member and character, explains perspective loss, and makes no request until confirmed", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getByRole("button", {
                name: "Revoke relationship",
            }),
        )

        expect(
            screen.getByText(
                /Revoke Aria the GM's Primary Controller relationship to Kestrel Vane\?/,
            ),
        ).toBeInTheDocument()
        expect(
            screen.getByText(/will no longer be available/),
        ).toBeInTheDocument()
        expect(fetchMock).not.toHaveBeenCalled()

        expect(
            screen.getByRole("button", { name: "Confirm" }),
        ).toBeInTheDocument()
        expect(
            screen.getByRole("button", { name: "Cancel" }),
        ).toBeInTheDocument()
    })

    it("cancel closes the confirmation, makes no request, and returns focus to the trigger", async () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        const trigger = screen.getByRole("button", {
            name: "Revoke relationship",
        })
        fireEvent.click(trigger)
        fireEvent.click(
            screen.getByRole("button", { name: "Cancel" }),
        )

        expect(fetchMock).not.toHaveBeenCalled()
        expect(
            screen.queryByRole("button", { name: "Confirm" }),
        ).not.toBeInTheDocument()

        await waitFor(() => {
            expect(
                screen.getByRole("button", {
                    name: "Revoke relationship",
                }),
            ).toHaveFocus()
        })
    })

    it("announces pending, then success, refreshes via onChanged, and never optimistically removes the relationship", async () => {
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
            screen.getByRole("button", {
                name: "Revoke relationship",
            }),
        )
        fireEvent.click(
            screen.getByRole("button", { name: "Confirm" }),
        )

        await waitFor(() => {
            expect(
                screen.getByText("Revoking character relationship…"),
            ).toBeInTheDocument()
        })
        expect(
            screen.getByText("Kestrel Vane — Primary Controller"),
        ).toBeInTheDocument()
        expect(onChanged).not.toHaveBeenCalled()

        resolveResponse(
            new Response(
                JSON.stringify({
                    membership_character_relationship_id:
                        fullOverview.members[0]
                            .character_relationships[0]
                            .membership_character_relationship_id,
                }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )

        await waitFor(() => {
            expect(
                screen.getByText("Character relationship revoked."),
            ).toBeInTheDocument()
        })
        expect(onChanged).toHaveBeenCalledWith(
            "Character relationship revoked.",
        )
    })

    it("announces a denied failure without exposing sensitive details", async () => {
        const fetchMock = vi
            .fn()
            .mockResolvedValue(new Response(null, { status: 403 }))
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getByRole("button", {
                name: "Revoke relationship",
            }),
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
            screen.getByRole("button", {
                name: "Revoke relationship",
            }),
        )

        const uuidPattern =
            /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i
        expect(
            uuidPattern.test(
                screen.getByText(
                    /Revoke Aria the GM's Primary Controller relationship/,
                ).textContent ?? "",
            ),
        ).toBe(false)
    })
})

describe("AccessPage — add resource grant (checkpoint 5)", () => {
    it("exposes Add direct resource access for every member when a character and a grantable capability are assignable", () => {
        renderPage(fullOverview)

        expect(
            screen.getAllByRole("button", {
                name: "Add direct resource access",
            }),
        ).toHaveLength(3)
    })

    it("does not expose the add control when no character is assignable", () => {
        renderPage({
            ...fullOverview,
            assignable_characters: [],
        })

        expect(
            screen.queryByRole("button", {
                name: "Add direct resource access",
            }),
        ).not.toBeInTheDocument()
    })

    it("does not expose the add control when no capability is grantable", () => {
        renderPage({
            ...fullOverview,
            grantable_resource_capabilities: [],
        })

        expect(
            screen.queryByRole("button", {
                name: "Add direct resource access",
            }),
        ).not.toBeInTheDocument()
    })

    it("offers only server-authoritative resource-type/resource/capability choices, narrowing capability choices to exclude combinations already active for the selected resource", () => {
        const overview = {
            ...fullOverview,
            members: [
                {
                    ...fullOverview.members[0],
                    grants: [
                        {
                            resource_grant_id: "existing-grant",
                            capability_code: "character.view_full",
                            capability_display_name:
                                "View Character Full Detail",
                            effect: "allow",
                            target_type: "character",
                            target_id:
                                "9e4f0e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                            target_display_name: "Kestrel Vane",
                            reason: null,
                            granted_at: "2026-01-03T00:00:00Z",
                            expires_at: null,
                        },
                    ],
                },
                fullOverview.members[1],
                fullOverview.members[2],
            ],
            grantable_resource_capabilities: [
                {
                    capability_id: "cap-full",
                    code: "character.view_full",
                    display_name: "View Character Full Detail",
                    target_type: "character",
                },
                {
                    capability_id: "cap-summary",
                    code: "character.view_summary",
                    display_name: "View Character Summary",
                    target_type: "character",
                },
            ],
        }

        renderPage(overview)

        fireEvent.click(
            screen.getAllByRole("button", {
                name: "Add direct resource access",
            })[0],
        )

        const resourceSelect = screen.getByLabelText("Character")
        const resourceOptions = Array.from(
            resourceSelect.querySelectorAll("option"),
        ).map((option) => option.textContent)
        expect(resourceOptions).toEqual(["Kestrel Vane", "Bram Ferro"])

        // Aria already holds View Character Full Detail on Kestrel Vane
        // (the default-selected resource) — only the remaining
        // grantable capability is offered, never the already-active one.
        const capabilitySelect = screen.getByLabelText("Permission")
        const capabilityOptions = Array.from(
            capabilitySelect.querySelectorAll("option"),
        ).map((option) => option.textContent)
        expect(capabilityOptions).toEqual(["View Character Summary"])
    })

    it("requires an explicit Add action and never submits on selection alone", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", {
                name: "Add direct resource access",
            })[0],
        )

        expect(fetchMock).not.toHaveBeenCalled()
    })

    it("cancel closes the Add-grant control and makes no request", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", {
                name: "Add direct resource access",
            })[0],
        )
        fireEvent.click(
            screen.getByRole("button", { name: "Cancel" }),
        )

        expect(fetchMock).not.toHaveBeenCalled()
        expect(
            screen.queryByLabelText("Permission"),
        ).not.toBeInTheDocument()
    })

    it("announces pending, then success, refreshes via onChanged, and never optimistically shows the new grant", async () => {
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
            screen.getAllByRole("button", {
                name: "Add direct resource access",
            })[0],
        )
        fireEvent.click(screen.getByRole("button", { name: "Add" }))

        await waitFor(() => {
            expect(
                screen.getByText("Adding resource access…"),
            ).toBeInTheDocument()
        })
        expect(onChanged).not.toHaveBeenCalled()

        resolveResponse(
            new Response(
                JSON.stringify({ resource_grant_id: "new-grant-id" }),
                {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )

        await waitFor(() => {
            expect(
                screen.getByText("Resource access added."),
            ).toBeInTheDocument()
        })
        expect(onChanged).toHaveBeenCalledWith("Resource access added.")
    })

    it("announces a denied failure without exposing sensitive details", async () => {
        const fetchMock = vi
            .fn()
            .mockResolvedValue(new Response(null, { status: 403 }))
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getAllByRole("button", {
                name: "Add direct resource access",
            })[0],
        )
        fireEvent.click(screen.getByRole("button", { name: "Add" }))

        expect(
            await screen.findByText(
                "You do not have permission to make this change.",
            ),
        ).toBeInTheDocument()
    })
})

describe("AccessPage — revoke resource grant (checkpoint 5)", () => {
    it("exposes an accessible revoke action for each existing grant", () => {
        renderPage(fullOverview)

        expect(
            screen.getAllByRole("button", { name: "Revoke access" }),
        ).toHaveLength(1)
    })

    it("requires an explicit confirmation naming the member and resource/permission, explains access may disappear immediately, and makes no request until confirmed", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getByRole("button", { name: "Revoke access" }),
        )

        expect(
            screen.getByText(
                /Revoke Aria the GM's View Campaign on Kestrel Vane access\?/,
            ),
        ).toBeInTheDocument()
        expect(
            screen.getByText(/may disappear immediately/),
        ).toBeInTheDocument()
        expect(fetchMock).not.toHaveBeenCalled()

        expect(
            screen.getByRole("button", { name: "Confirm" }),
        ).toBeInTheDocument()
        expect(
            screen.getByRole("button", { name: "Cancel" }),
        ).toBeInTheDocument()
    })

    it("cancel closes the confirmation, makes no request, and returns focus to the trigger", async () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        const trigger = screen.getByRole("button", {
            name: "Revoke access",
        })
        fireEvent.click(trigger)
        fireEvent.click(
            screen.getByRole("button", { name: "Cancel" }),
        )

        expect(fetchMock).not.toHaveBeenCalled()
        expect(
            screen.queryByRole("button", { name: "Confirm" }),
        ).not.toBeInTheDocument()

        await waitFor(() => {
            expect(
                screen.getByRole("button", { name: "Revoke access" }),
            ).toHaveFocus()
        })
    })

    it("announces pending, then success, refreshes via onChanged, and never optimistically removes the grant", async () => {
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
            screen.getByRole("button", { name: "Revoke access" }),
        )
        fireEvent.click(
            screen.getByRole("button", { name: "Confirm" }),
        )

        await waitFor(() => {
            expect(
                screen.getByText("Revoking resource access…"),
            ).toBeInTheDocument()
        })
        expect(
            screen.getByText("View Campaign"),
        ).toBeInTheDocument()
        expect(onChanged).not.toHaveBeenCalled()

        resolveResponse(
            new Response(
                JSON.stringify({
                    resource_grant_id:
                        fullOverview.members[0].grants[0]
                            .resource_grant_id,
                }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )

        await waitFor(() => {
            expect(
                screen.getByText("Resource access revoked."),
            ).toBeInTheDocument()
        })
        expect(onChanged).toHaveBeenCalledWith("Resource access revoked.")
    })

    it("announces a denied failure without exposing sensitive details", async () => {
        const fetchMock = vi
            .fn()
            .mockResolvedValue(new Response(null, { status: 403 }))
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getByRole("button", { name: "Revoke access" }),
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
            screen.getByRole("button", { name: "Revoke access" }),
        )

        const uuidPattern =
            /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i
        expect(
            uuidPattern.test(
                screen.getByText(
                    /Revoke Aria the GM's View Campaign on Kestrel Vane access/,
                ).textContent ?? "",
            ),
        ).toBe(false)
    })
})

describe("AccessPage — revoke resource grant, deny effect (checkpoint-5 correction)", () => {
    // A "deny" grant is an explicit block, not a permission — removing one
    // restores access from elsewhere rather than taking it away, so every
    // trigger/confirmation/status string must say so instead of reusing the
    // allow-oriented "Revoke access"/"may disappear" copy above.
    const denyOverview: CampaignAccessOverview = {
        ...fullOverview,
        members: [
            {
                ...fullOverview.members[0],
                grants: [
                    {
                        ...fullOverview.members[0].grants[0],
                        effect: "deny",
                    },
                ],
            },
            fullOverview.members[1],
            fullOverview.members[2],
        ],
    }

    it("labels the trigger 'Remove denial', never 'Revoke access'", () => {
        renderPage(denyOverview)

        expect(
            screen.getByRole("button", { name: "Remove denial" }),
        ).toBeInTheDocument()
        expect(
            screen.queryByRole("button", { name: "Revoke access" }),
        ).not.toBeInTheDocument()
    })

    it("explains the denial is being removed and access may be restored, never that access may disappear", () => {
        renderPage(denyOverview)

        fireEvent.click(
            screen.getByRole("button", { name: "Remove denial" }),
        )

        expect(
            screen.getByText(
                /Remove Aria the GM's explicit denial of View Campaign on Kestrel Vane\?/,
            ),
        ).toBeInTheDocument()
        expect(
            screen.getByText(
                /Access may be restored from another role, relationship, group, or allow grant\./,
            ),
        ).toBeInTheDocument()
        expect(
            screen.queryByText(/may disappear immediately/),
        ).not.toBeInTheDocument()
    })

    it("moves focus from trigger to confirmation, and back to the trigger on cancel", async () => {
        renderPage(denyOverview)

        fireEvent.click(
            screen.getByRole("button", { name: "Remove denial" }),
        )

        await waitFor(() => {
            expect(
                screen.getByRole("button", { name: "Confirm" }),
            ).toHaveFocus()
        })

        fireEvent.click(
            screen.getByRole("button", { name: "Cancel" }),
        )

        // Cancel unmounts the confirmation markup and mounts a fresh
        // trigger button — re-query rather than reuse the stale pre-click
        // reference, mirroring the identical allow-effect focus-return
        // test above.
        await waitFor(() => {
            expect(
                screen.getByRole("button", { name: "Remove denial" }),
            ).toHaveFocus()
        })
    })

    it("announces a deny-specific pending/success message and calls onChanged with it", async () => {
        const onChanged = vi.fn()
        let resolveResponse!: (response: Response) => void
        const fetchMock = vi.fn().mockReturnValue(
            new Promise<Response>((resolve) => {
                resolveResponse = resolve
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        renderPage(denyOverview, onChanged)

        fireEvent.click(
            screen.getByRole("button", { name: "Remove denial" }),
        )
        fireEvent.click(
            screen.getByRole("button", { name: "Confirm" }),
        )

        await waitFor(() => {
            expect(
                screen.getByText("Removing denial…"),
            ).toBeInTheDocument()
        })
        expect(onChanged).not.toHaveBeenCalled()

        resolveResponse(
            new Response(
                JSON.stringify({
                    resource_grant_id:
                        denyOverview.members[0].grants[0]
                            .resource_grant_id,
                }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )

        const successMessage =
            "Explicit denial removed. Access may be restored from another role, relationship, group, or allow grant."
        await waitFor(() => {
            expect(screen.getByText(successMessage)).toBeInTheDocument()
        })
        expect(onChanged).toHaveBeenCalledWith(successMessage)
    })
})

describe("AccessPage — access groups (Phase 13E-B checkpoint 6)", () => {
    const groupOverview: CampaignAccessOverview = {
        ...fullOverview,
        grantable_resource_capabilities: [
            ...fullOverview.grantable_resource_capabilities,
            {
                capability_id: "7a3b9e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                code: "character.view_summary",
                display_name: "View Character Summary",
                target_type: "character",
            },
        ],
        access_groups: [
            {
                access_group_id: "3c9d5e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                name: "Lore Circle",
                description: "For the lore fans",
                status_code: "active",
                status_display_name: "Active",
                created_at: "2026-01-05T00:00:00Z",
                members: [
                    {
                        access_group_membership_id:
                            "4d0e6e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                        campaign_membership_id:
                            "1a6f2e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                        display_name: "Quiet Observer",
                        added_at: "2026-01-05T00:00:00Z",
                    },
                ],
                grants: [
                    {
                        resource_grant_id:
                            "5e1f7e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                        capability_code: "character.view_full",
                        capability_display_name: "View Character Full Detail",
                        effect: "allow",
                        target_type: "character",
                        target_id: "9e4f0e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                        target_display_name: "Kestrel Vane",
                        reason: null,
                        granted_at: "2026-01-05T00:00:00Z",
                        expires_at: null,
                    },
                ],
            },
            {
                access_group_id: "6f2a8e3a-2c4d-4a9b-9e3f-8a2b3c4d5e6f",
                name: "Retired Group",
                description: null,
                status_code: "archived",
                status_display_name: "Archived",
                created_at: "2026-01-01T00:00:00Z",
                members: [],
                grants: [],
            },
        ],
    }

    it("shows a deliberate empty state when the campaign has no access groups", () => {
        renderPage(fullOverview)

        expect(
            screen.getByText("No access groups exist yet for this campaign."),
        ).toBeInTheDocument()
    })

    it("renders a group's name, status, description, members, and grants", () => {
        const { container } = renderPage(groupOverview)

        expect(screen.getByText("Lore Circle")).toBeInTheDocument()
        expect(screen.getByText("For the lore fans")).toBeInTheDocument()
        expect(screen.getByText("Retired Group")).toBeInTheDocument()
        expect(screen.getByText("Archived")).toBeInTheDocument()
        expect(
            screen.getAllByText("Quiet Observer").length,
        ).toBeGreaterThan(0)
        expect(container.textContent).toContain(
            "View Character Full Detail",
        )
        expect(container.textContent).toContain("(Allow) on Kestrel Vane")
    })

    it("never renders a raw UUID as user-facing text for access groups", () => {
        const { container } = renderPage(groupOverview)

        const uuidPattern =
            /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i

        expect(uuidPattern.test(container.textContent ?? "")).toBe(false)
    })

    it("offers Edit/Deactivate for an active group and only Reactivate for an archived one", () => {
        renderPage(groupOverview)

        expect(
            screen.getAllByRole("button", { name: "Edit" }),
        ).toHaveLength(1)
        expect(
            screen.getAllByRole("button", { name: "Deactivate" }),
        ).toHaveLength(1)
        expect(
            screen.getAllByRole("button", { name: "Reactivate" }),
        ).toHaveLength(1)
    })

    it("creates a group: trigger, inline validation, Save/Cancel", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(fullOverview)

        fireEvent.click(
            screen.getByRole("button", { name: "Create access group" }),
        )

        const saveButton = screen.getByRole("button", { name: "Save" })
        expect(saveButton).toBeDisabled()

        fireEvent.change(screen.getByLabelText(/New access group name/), {
            target: { value: "   " },
        })
        expect(saveButton).toBeDisabled()

        fireEvent.change(screen.getByLabelText(/New access group name/), {
            target: { value: "New Group" },
        })
        expect(saveButton).toBeEnabled()

        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        expect(fetchMock).not.toHaveBeenCalled()
        expect(
            screen.queryByLabelText(/New access group name/),
        ).not.toBeInTheDocument()
    })

    it("edit access group: disables Save until the name/description actually changes", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage(groupOverview)

        fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0])

        const saveButton = screen.getByRole("button", { name: "Save" })
        expect(saveButton).toBeDisabled()

        fireEvent.change(screen.getByLabelText("Access group name"), {
            target: { value: "Renamed Circle" },
        })
        expect(saveButton).toBeEnabled()

        fireEvent.click(saveButton)
        expect(fetchMock).toHaveBeenCalledTimes(1)
    })

    it("deactivate confirmation names the group and explains the consequences", () => {
        renderPage(groupOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Deactivate" })[0],
        )

        expect(
            screen.getByText(/Deactivate "Lore Circle"\?/),
        ).toBeInTheDocument()
        expect(
            screen.getByText(/lose any access this group grants immediately/),
        ).toBeInTheDocument()
    })

    it("add member: offers only currently active members not already in the group", () => {
        renderPage(groupOverview)

        fireEvent.click(screen.getByRole("button", { name: "Add member" }))

        const select = screen.getByLabelText("Add a member to Lore Circle")
        const options = Array.from(select.querySelectorAll("option")).map(
            (option) => option.textContent,
        )

        // Quiet Observer already belongs to the group and must not be
        // offered again; Aria the GM and Multi Role Member remain eligible.
        expect(options).toEqual(["Aria the GM", "Multi Role Member"])
    })

    it("remove member confirmation names both the member and the group", () => {
        renderPage(groupOverview)

        fireEvent.click(
            screen.getByRole("button", { name: "Remove from group" }),
        )

        expect(
            screen.getByText(
                /Remove Quiet Observer from Lore Circle\?/,
            ),
        ).toBeInTheDocument()
    })

    it("add group resource access: character and capability selectors only, no resource-type selector", () => {
        renderPage(groupOverview)

        fireEvent.click(
            screen.getAllByRole("button", { name: "Add resource access" })[0],
        )

        expect(
            screen.getByLabelText("Add resource access for Lore Circle — Character"),
        ).toBeInTheDocument()
        expect(screen.getByLabelText("Permission")).toBeInTheDocument()
        // Only one combobox pair (character, capability) — never a
        // third "resource type" selector, unlike the member-grant flow.
        expect(screen.getAllByRole("combobox")).toHaveLength(2)
    })

    it("reuses the effect-aware revoke flow for a group-owned grant", () => {
        renderPage(groupOverview)

        const groupCard = screen
            .getByText("Lore Circle")
            .closest("details") as HTMLElement
        fireEvent.click(
            within(groupCard).getByRole("button", { name: "Revoke access" }),
        )

        expect(
            screen.getByText(/Revoke Lore Circle's/),
        ).toBeInTheDocument()
    })
})
