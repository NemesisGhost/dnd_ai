/* eslint-disable react-refresh/only-export-components -- test support module: Fast Refresh does not apply to it. */
import { fireEvent, screen, within } from "@testing-library/react"
import { useSession } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { CampaignAccessPage } from "../pages/CampaignAccessPage"
import type { AccessResourceGrantSummary, CampaignAccessOverview } from "../types/accessOverview"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "./authoringHarness"
import type { MockResponse, MockServer } from "./authoringHarness"

// Shared by the character-denial page tests (P15-C02-S04, T01 and T02): a fake campaign "c1" served through the
// authoring harness's mock server, the real Access page, and small helpers for its member and group cards. The
// calling test file must mock "../components/InvitationsSection" itself.

export const OVERVIEW = "/campaigns/c1/access-overview"
export const GRANTS = "/campaigns/c1/resource-grants"
export const ARIA = "ch-aria"
export const BRAM = "ch-bram"

export const DENIABLE = [
    { capability_id: "cap-view", code: "campaign.view", display_name: "View Campaign" },
    { capability_id: "cap-edit", code: "canon.edit", display_name: "Edit Canon" },
]
export const GRANTABLE = [
    { capability_id: "cap-full", code: "character.view_full", display_name: "View Character Full Detail", target_type: "character" },
    { capability_id: "cap-ctl", code: "character.control", display_name: "Control Character", target_type: "character" },
    { capability_id: "cap-ent", code: "campaign.view", display_name: "View Campaign", target_type: "entity" },
    { capability_id: "cap-ent2", code: "canon.edit", display_name: "Edit Canon", target_type: "entity" },
]

export function member(id: string, name: string, grants: AccessResourceGrantSummary[] = []) {
    return {
        campaign_membership_id: id,
        user_id: id === "m1" ? sessionBootstrapFixture.user.user_id : `user-${id}`,
        display_name: name,
        status_code: "active",
        status_display_name: "Active",
        joined_at: "2026-01-01T00:00:00Z",
        account_is_active: true,
        roles: [],
        character_relationships: [],
        grants,
    }
}

export function group(id: string, name: string, status: "active" | "archived" = "active", grants: AccessResourceGrantSummary[] = []) {
    return {
        access_group_id: id,
        name,
        description: null,
        status_code: status,
        status_display_name: status === "active" ? "Active" : "Archived",
        created_at: "2026-01-01T00:00:00Z",
        members: [],
        grants,
    }
}

export function denyGrant(id: string, code: string, character: string): AccessResourceGrantSummary {
    return {
        resource_grant_id: id,
        capability_code: code,
        capability_display_name: code === "canon.edit" ? "Edit Canon" : "View Campaign",
        effect: "deny",
        target_type: "entity",
        target_id: character,
        target_display_name: character === ARIA ? "Aria" : "Bram",
        reason: null,
        granted_at: "2026-02-01T00:00:00Z",
        expires_at: null,
    }
}

export function overviewWith(over: Partial<CampaignAccessOverview> = {}): CampaignAccessOverview {
    return {
        members: [member("m1", "Olga Owner"), member("m2", "Pip Player")],
        assignable_roles: [],
        assignable_characters: [
            { character_id: ARIA, display_name: "Aria" },
            { character_id: BRAM, display_name: "Bram" },
        ],
        assignable_relationship_types: [],
        grantable_resource_capabilities: GRANTABLE,
        deniable_character_capabilities: DENIABLE,
        access_groups: [group("g1", "Night Watch"), group("g2", "Old Guard", "archived")],
        ...over,
    }
}

export const bootstrap = (caps: string[] = ["access.manage"]) =>
    bootstrapWith({
        campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: caps }],
    })

export interface SetupOptions {
    overview?: () => CampaignAccessOverview
    post?: (body: unknown) => MockResponse | Promise<MockResponse>
    onRefresh?: () => Promise<ReturnType<typeof bootstrap> | null>
}

// A control that asks the shell for the authoritative session, as the app does after a write.
export function Host() {
    const { refresh } = useSession()
    return (
        <>
            <CampaignAccessPage />
            <button type="button" onClick={() => void refresh()}>
                Refresh session
            </button>
        </>
    )
}

export function setup(options: SetupOptions = {}) {
    const state = { overview: options.overview ?? (() => overviewWith()) }
    const server = installMockServer()
    server.on("GET", OVERVIEW, () => ({ body: state.overview() }))
    server.on("POST", GRANTS, (call) => options.post?.(call.body) ?? { status: 201, body: { resource_grant_id: "new-grant" } })
    const rendered = renderAuthoringRoutes({
        initialEntry: "/app/c1/access",
        bootstrap: bootstrap(),
        routes: [
            { path: "/app/:campaignId/access", element: <Host /> },
            { path: "/app/:campaignId/elsewhere", element: <p>Elsewhere</p> },
        ],
        onRefresh: options.onRefresh,
    })
    return { server, state, ...rendered }
}

export const posts = (server: MockServer) => server.callsTo("POST", GRANTS)
export const reads = (server: MockServer) => server.callsTo("GET", OVERVIEW)

export async function cardOf(name: string): Promise<HTMLElement> {
    const heading = await screen.findByText(name, { selector: "summary strong" })
    return heading.closest("details") as HTMLElement
}

export async function openForm(card: HTMLElement) {
    fireEvent.click(within(card).getByRole("button", { name: /^Add (direct )?resource access$/ }))
    return within(card).getByRole("combobox", { name: /^Add (direct )?resource access for/ })
}

export async function chooseDenyKind(card: HTMLElement) {
    const typeSelect = await openForm(card)
    fireEvent.change(typeSelect, { target: { value: "character_deny" } })
}

export const characterSelect = (card: HTMLElement) => within(card).getByRole("combobox", { name: "Character" })
export const permissionSelect = (card: HTMLElement) => within(card).getByRole("combobox", { name: "What to deny" })
export const confirmBox = (card: HTMLElement) => within(card).getByRole("checkbox", { name: /I understand this explicitly denies/ })
export const addButton = (card: HTMLElement) => within(card).getByRole("button", { name: "Add" })

export async function fillDeny(card: HTMLElement, character = ARIA, code = "canon.edit") {
    await chooseDenyKind(card)
    fireEvent.change(characterSelect(card), { target: { value: character } })
    fireEvent.change(permissionSelect(card), { target: { value: code } })
    fireEvent.click(confirmBox(card))
}

export const optionTexts = (select: HTMLElement) =>
    within(select).getAllByRole("option").map((option) => option.textContent)

export async function typeOptions(card: HTMLElement) {
    return optionTexts(await openForm(card))
}
