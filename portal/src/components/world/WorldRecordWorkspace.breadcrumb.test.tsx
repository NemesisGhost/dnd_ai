import { screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { useParams, useRoutes } from "react-router"
import { FULL_RECORD_AUTHORING } from "../../test/recordAuthoring"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import type { MockServer } from "../../test/authoringHarness"
import { liveBody, publicBody } from "../../fixtures/publicCharacter"
import { BreadcrumbLabelProvider } from "../../navigation/BreadcrumbLabelProvider"
import { useBreadcrumbLabelReader } from "../../navigation/BreadcrumbLabelContext"
import { TaskBreadcrumb } from "../navigation/TaskBreadcrumb"
import { CampaignWorldDetailPage } from "../../pages/CampaignWorldDetailPage"

// The breadcrumb registry as its real consumers read it: the TaskBreadcrumb on a child page of the
// record (its history), and the registry keys the character record publishes under (L-1).
const C = "c1"
const RAW = "RAW-REJECTED-NAME"
const NOT_FOUND = { status: 404, body: { error: { code: "not_found", message: "m", correlation_id: "x" } } }

const RECORD = (category: string, id: string) => `/app/${C}/world/${category}/${id}`
const HISTORY = (category: string, id: string) => `${RECORD(category, id)}/history`
const taskState = (category: string, id: string) => ({
    task: {
        v: 1,
        root: "world",
        scope: { campaignId: C },
        trail: [{ route: "world.record", params: { campaignId: C, category, entityId: id } }],
    },
})

// Shows what the registry holds for the record under both of the keys the workspace publishes, next
// to the real breadcrumb.
function Probe() {
    const { category = "", entityId = "" } = useParams()
    const labelFor = useBreadcrumbLabelReader()
    const character = labelFor("characters.detail", { campaignId: C, characterId: entityId }) ?? "-"
    const record = labelFor("world.record", { campaignId: C, category, entityId }) ?? "-"
    return (
        <div data-testid="probe" data-entity={entityId}>
            <TaskBreadcrumb />
            <p data-testid="labels">{`${character}|${record}`}</p>
        </div>
    )
}

function Inner() {
    return useRoutes([
        { path: "world/:category/:entityId", element: <CampaignWorldDetailPage /> },
        { path: "world/:category/:entityId/history", element: <Probe /> },
    ])
}

function render(entry: string, server: MockServer) {
    void server
    return renderAuthoringRoutes({
        initialEntry: entry,
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: C, capabilities: ["canon.edit", "campaign.view"] }],
        }),
        // One provider above every page, as in the campaign workspace, so a label outlives the page.
        routes: [
            {
                path: "/app/:campaignId/*",
                element: (
                    <BreadcrumbLabelProvider campaignId={C} characterId={null}>
                        <Inner />
                    </BreadcrumbLabelProvider>
                ),
            },
        ],
    })
}

const characterServer = (reads: Record<string, () => object | Promise<object>>) => {
    const server = installMockServer()
    server.on("GET", /.*/, NOT_FOUND)
    for (const [id, read] of Object.entries(reads)) {
        server.on("GET", `/campaigns/${C}/characters/${id}`, async () => ({ body: await read() }))
    }
    return server
}

const valid = (id: string, name: string) => ({ ...liveBody("full", { character_id: id, name, character_kind: "npc" }) })
const unavailable = () => screen.findByText("Character information is unavailable.")
const labels = () => screen.getByTestId("labels").textContent
async function openHistory(
    router: { navigate: (to: string, o?: object) => Promise<void>; state: { location: { pathname: string } } },
    category: string,
    id: string,
) {
    await router.navigate(HISTORY(category, id), { state: taskState(category, id) })
    // The previous record's probe may still be on screen until this one has rendered.
    await waitFor(() => expect(router.state.location.pathname).toBe(HISTORY(category, id)))
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveAttribute("data-entity", id))
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("World record workspace: the breadcrumb label of a character (L-1)", () => {
    it("never publishes the raw name of a malformed response", async () => {
        const server = characterServer({ n1: () => ({ character_id: "n1", name: RAW }) })
        const { router } = render(RECORD("character", "n1"), server)
        await unavailable()
        await openHistory(router, "character", "n1")
        expect(labels()).toBe("-|-")
        expect(screen.getByRole("navigation", { name: "Breadcrumb" })).not.toHaveTextContent(RAW)
        expect(document.body.textContent).not.toContain(RAW)
    })

    it("cannot publish the raw name of a summary rejected for populated mechanics", async () => {
        const server = characterServer({
            n1: () => liveBody("summary", { character_id: "n1", name: RAW, character_kind: "npc", current_hit_points: 5 }),
        })
        const { router } = render(RECORD("character", "n1"), server)
        await unavailable()
        await openHistory(router, "character", "n1")
        expect(labels()).toBe("-|-")
        expect(document.body.textContent).not.toContain(RAW)
    })

    it("removes the earlier label when a later read of the same record is rejected", async () => {
        let next: () => object = () => valid("n1", "Mira")
        const server = characterServer({ n1: () => next() })
        const { router } = render(RECORD("character", "n1"), server)
        await screen.findByRole("heading", { level: 1, name: "Mira" })
        await openHistory(router, "character", "n1")
        await waitFor(() => expect(labels()).toBe("Mira|Mira"))
        expect(screen.getByRole("link", { name: "Mira" })).toBeInTheDocument()

        next = () => ({ character_id: "n1", name: RAW })
        await router.navigate(RECORD("character", "n1"))
        await unavailable()
        await openHistory(router, "character", "n1")
        expect(labels()).toBe("-|-")
        expect(screen.queryByRole("link", { name: "Mira" })).not.toBeInTheDocument()
        expect(document.body.textContent).not.toContain(RAW)
    })

    it("shows no old, late or rejected label under another record after a superseded read", async () => {
        let release: (value: object) => void = () => undefined
        const late = new Promise<object>((resolve) => {
            release = resolve
        })
        const server = characterServer({ n1: () => late, n2: () => valid("n2", "Nia") })
        const { router } = render(RECORD("character", "n1"), server)
        // n1 has not answered; the person moves on to n2.
        await router.navigate(RECORD("character", "n2"))
        await screen.findByRole("heading", { level: 1, name: "Nia" })
        release({ character_id: "n1", name: RAW })
        await openHistory(router, "character", "n2")
        await waitFor(() => expect(labels()).toBe("Nia|Nia"))
        await openHistory(router, "character", "n1")
        expect(labels()).toBe("-|-")
        expect(document.body.textContent).not.toContain(RAW)
        expect(screen.getByRole("navigation", { name: "Breadcrumb" })).not.toHaveTextContent("Nia")
    })

    it.each([
        ["public", () => publicBody({ character_id: "n1", name: "Mira", character_kind: "npc" })],
        ["full", () => valid("n1", "Mira")],
        ["summary", () => liveBody("summary", { character_id: "n1", name: "Mira", character_kind: "npc" })],
        [
            "pre-tier",
            () => ({
                character_id: "n1",
                name: "Mira",
                character_kind: "npc",
                species_code: "human",
                size_category: "medium",
                current_hit_points: null,
                maximum_hit_points: null,
                temporary_hit_points: null,
                exhaustion_level: null,
                death_save_successes: null,
                death_save_failures: null,
                current_location_id: null,
                active_encounter_id: null,
                conditions: null,
                resources: null,
            }),
        ],
    ])("still publishes the name of a valid %s read", async (_tier, body) => {
        const server = characterServer({ n1: body })
        const { router } = render(RECORD("character", "n1"), server)
        await screen.findByRole("heading", { level: 1, name: "Mira" })
        await openHistory(router, "character", "n1")
        await waitFor(() => expect(labels()).toBe("Mira|Mira"))
        expect(screen.getByRole("link", { name: "Mira" })).toBeInTheDocument()
    })

    it("leaves a non-character record's label as it was", async () => {
        const server = installMockServer()
        server.on("GET", /.*/, NOT_FOUND)
        server.on("GET", `/campaigns/${C}/world/locations/l1`, {
            body: {
                authoring: FULL_RECORD_AUTHORING,
                location_id: "l1",
                name: "Old Mill",
                summary: "A quiet mill.",
                location_type_code: "building",
                parent_location_id: null,
                breadcrumbs: [],
                population: null,
                building_use: null,
                danger_level: null,
                is_searched: null,
                is_destroyed: null,
                alarm_level: null,
                condition_notes: null,
            },
        })
        const { router } = render(RECORD("location", "l1"), server)
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        await openHistory(router, "location", "l1")
        await waitFor(() => expect(labels()).toBe("-|Old Mill"))
    })
})
