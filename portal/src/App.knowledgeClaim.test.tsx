import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const CLAIM = "/app/mundivita/knowledge/k1"
const DETAIL = /^\/campaigns\/mundivita\/knowledge\/k1(\?.*)?$/
const AUDIENCE = "/campaigns/mundivita/knowledge/k1/audience"
const VIEW_PATH = "/campaigns/mundivita/authoring/knowledge/k1"
const UPDATE = `${VIEW_PATH}/update`
const KNOWLEDGE = "/campaigns/mundivita/knowledge"
const LIFECYCLE = "/campaigns/mundivita/entities/k1/lifecycle"

const OPTIONS = {
  can_create: true,
  knowledge_types: [
    { value: "secret", label: "Secret" },
    { value: "rumor", label: "Rumor" },
  ],
  truth_statuses: [
    { value: "true", label: "True" },
    { value: "false", label: "False" },
  ],
  sensitivities: [
    { value: "public", label: "Public" },
    { value: "secret", label: "Secret" },
  ],
  limits: { statement_max_length: 4000, change_note_max_length: 1000 },
}

const SUBJECT = { entity_id: "l1", name: "Keep", category: "location", entity_type_code: "fortress" }

const detail = (extra: Record<string, unknown> = {}) => ({
  knowledge_item_id: "k1",
  knowledge_type_code: "secret",
  statement: "The duke is a vampire.",
  truth_status_code: "true",
  sensitivity: "secret",
  awareness_level: null,
  confidence: null,
  willing_to_share: null,
  subject: SUBJECT,
  ...extra,
})

const view = (extra: Record<string, unknown> = {}) => ({
  knowledge_item_id: "k1",
  statement: "The duke is a vampire.",
  knowledge_type: "secret",
  truth_status: "true",
  sensitivity: "secret",
  subject: { entity_id: "l1", name: "Keep", canon_status: "canon", lifecycle_status: "active" },
  in_use: false,
  canon_status: "draft",
  lifecycle_status: "active",
  row_version: 1,
  available_actions: ["update"],
  blocked_actions: [],
  field_locks: [],
  ...extra,
})

const lifecycle = (extra: Record<string, unknown> = {}) => ({
  entity_id: "k1",
  entity_type_code: "knowledge_item",
  canonical_name: "x",
  canon_status: "draft",
  lifecycle_status: "active",
  row_version: 2,
  lifecycle_managed: true,
  superseded_by: null,
  available_actions: ["submit_for_review", "reject", "archive", "delete_draft"],
  blocked_actions: [
    { action: "approve", reason: "wrong_canon_status" },
    { action: "publish", reason: "wrong_canon_status" },
  ],
  ...extra,
})

const audience = () => ({
  knowledge_item_id: "k1",
  awareness_levels: ["aware", "rumored", "suspected"],
  transfer_methods: ["dialogue", "rumor"],
  parties: [{ party_knowledge_id: "pk1", party_id: "p1", party_name: "Red Company", awareness_level: "aware" }],
  knowers: [
    {
      entity_knowledge_id: "ek1",
      knower_entity_id: "n1",
      knower_name: "Mira",
      knower_type: "npc",
      awareness_level: "suspected",
      confidence: 60,
      interpretation: "He only seems pale.",
      willing_to_share: true,
      last_event_id: "ev1",
    },
  ],
  public: [{ public_knowledge_id: "pub1", location_id: "l1", location_name: "Stonebridge", awareness_level: "rumored" }],
})

const PARTIES = {
  can_create: true,
  items: [
    { party_id: "p1", name: "Red Company", description: null, lifecycle_status: "active", row_version: 1 },
    { party_id: "p2", name: "Blue Company", description: null, lifecycle_status: "active", row_version: 1 },
  ],
}

const PROVENANCE = {
  entity_id: "k1",
  name: "x",
  entity_type_code: "knowledge_item",
  canon_status: "draft",
  lifecycle_status: "active",
  created_at: "2026-10-04T00:00:00Z",
  created_by_name: "Platform Administrator",
  origin: { source_id: "s0", source_type: "gm_entry", source_type_label: "GM entry", title: "GM entry", reference: null, created_by_name: null, attached_count: 1 },
  links: [],
  transitions: [],
  superseded_by: null,
  supersedes: [],
}
const SOURCES = {
  items: [],
  source_types: [{ value: "note", label: "Note" }],
  limits: { title_max_length: 200, reference_max_length: 2000 },
}

const RECEIPT = { knowledge_item_id: "k1", record_id: "r1", changed: true, event_id: "e1" }
const STALE = { status: 409, body: { error: { code: "stale_write", message: "m", correlation_id: "c" } } }

let server: MockServer
let current: { detail: object; view: object }

const at = (section: string, query = "") => `${CLAIM}?${query === "" ? "" : `${query}&`}section=${section}`

function setup(path = CLAIM, capabilities: string[] = ["canon.edit"]) {
  current = { detail: detail(), view: view() }
  server.on("GET", DETAIL, () => ({ body: current.detail }))
  server.on("GET", VIEW_PATH, () => ({ body: current.view }))
  return openApp(path, capabilities)
}

// A published claim: only then can anyone be recorded as knowing it.
function setupPublished(path = CLAIM) {
  const rendered = setup(path)
  current = { detail: current.detail, view: view({ canon_status: "canon" }) }
  server.on("GET", VIEW_PATH, () => ({ body: current.view }))
  return rendered
}

const withLifecycle = (body: object) => {
  server.on("GET", LIFECYCLE, () => ({ body }))
}

beforeEach(() => {
  server = installCampaignShellMocks()
  server.on("GET", "/campaigns/mundivita/authoring/knowledge/options", { body: OPTIONS })
  server.on("GET", AUDIENCE, () => ({ body: audience() }))
  server.on("GET", /\/campaigns\/mundivita\/parties/, { body: PARTIES })
  server.on("GET", /\/authoring\/knowledge\/subject-options/, {
    body: { items: [{ entity_id: "l2", name: "Harbor", kind: "settlement", canon_status: "canon" }], next_cursor: null },
  })
  server.on("GET", /\/world\/search/, {
    body: {
      items: [{ entity_id: "n2", category: "character", entity_type_code: "npc", name: "Tom", summary: null }],
      next_cursor: null,
    },
  })
  server.on("GET", /\/entities\/k1\/lifecycle$/, { status: 404 })
  server.on("GET", /\/entities\/k1\/provenance$/, { body: PROVENANCE })
  server.on("GET", "/campaigns/mundivita/sources", { body: SOURCES })
  server.on("GET", /audience-preview|audience_preview/, { status: 404 })
  server.on("POST", /\/campaigns\/mundivita\/knowledge\//, { body: RECEIPT })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const claimBox = () => screen.findByRole("textbox", { name: /^Claim/ })
const stageLink = (n: number) => screen.getByRole("link", { name: new RegExp(`^${n}\\.`) })
const panelOf = (key: string) => document.getElementById(`claim-section-${key}-heading`)!.closest("section")!
// The workspace renders once the lifecycle read has settled, so wait for a panel before using it.
const findPanel = async (key: string) => {
  await waitFor(() => expect(document.getElementById(`claim-section-${key}-heading`)).not.toBeNull())
  return panelOf(key)
}
const breadcrumbKnowledge = () =>
  within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Knowledge" })

describe("unified knowledge claim page", () => {
  describe("header", () => {
    it("shows the claim, its subject and the actual status apart from the stage navigation", async () => {
      withLifecycle(lifecycle())
      setup(`${CLAIM}?character_id=c1`)
      expect(await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })).toBeInTheDocument()
      expect(screen.getAllByRole("main")).toHaveLength(1)
      const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" })
      expect(within(crumbs).getByRole("link", { name: "Knowledge" })).toHaveAttribute(
        "href",
        "/app/mundivita/knowledge?character_id=c1",
      )
      expect(within(crumbs).getByText("Claim")).toHaveAttribute("aria-current", "page")
      const status = await screen.findByRole("group", { name: "Record status" })
      expect(within(status).getByText("Draft")).toBeInTheDocument()
      expect(screen.getAllByText("About this World entry")).not.toHaveLength(0)
      expect(screen.getAllByRole("link", { name: "Open World entry" })[0]).toHaveAttribute(
        "href",
        "/app/mundivita/world/location/l1",
      )
      // Navigation says nothing about status.
      const stages = screen.getByRole("navigation", { name: "Claim stages" })
      expect(within(stages).getAllByRole("link").map((l) => l.textContent)).toEqual([
        "1. Prepare",
        "2. Review & publish",
        "3. Use in play",
      ])
      expect(within(stages).queryByText("Draft")).toBeNull()
      // The member preview is its own workspace (Knowledge > Member preview), not a per-claim control.
      expect(screen.queryByRole("button", { name: /Preview as member/ })).toBeNull()
    })

    it("marks an archived record as archived next to its canon status", async () => {
      withLifecycle(lifecycle({ canon_status: "canon", lifecycle_status: "archived", available_actions: ["restore"] }))
      setup()
      const status = await screen.findByRole("group", { name: "Record status" })
      expect(within(status).getByText("Canon")).toBeInTheDocument()
      expect(within(status).getByText("Archived")).toBeInTheDocument()
    })

    it("cuts a very long claim in the headline and keeps it whole in the Claim section", async () => {
      const long = "A long claim. ".repeat(40).trim()
      current = { detail: detail({ statement: long }), view: view({ statement: long }) }
      server.on("GET", DETAIL, () => ({ body: current.detail }))
      server.on("GET", VIEW_PATH, () => ({ body: current.view }))
      openApp(CLAIM, ["canon.edit"])
      const heading = await screen.findByRole("heading", { level: 1, name: /^A long claim/ })
      expect(heading.textContent!.endsWith("…")).toBe(true)
      expect(heading.textContent!.length).toBeLessThan(long.length)
      expect(await claimBox()).toHaveValue(long)
    })
  })

  describe("staged workspace", () => {
    it("opens the claim for a draft, with one visible section and every panel kept mounted", async () => {
      withLifecycle(lifecycle())
      const { router } = setup()
      expect(await claimBox()).toHaveValue("The duke is a vampire.")
      await waitFor(() => expect(router.state.location.search).toBe("?section=claim"))
      expect(screen.getByRole("heading", { level: 2, name: "Claim" })).toBeInTheDocument()
      for (const hidden of ["sources", "review", "publication", "who-knows", "character"]) {
        expect(panelOf(hidden)).not.toBeVisible()
      }
      expect(panelOf("claim")).toBeVisible()
      expect(stageLink(1)).toHaveAttribute("aria-current", "step")
      const sections = screen.getByRole("navigation", { name: "Prepare sections" })
      expect(within(sections).getAllByRole("link").map((l) => l.textContent)).toEqual(["Claim", "Sources"])
      expect(within(sections).getByRole("link", { name: "Claim" })).toHaveAttribute("aria-current", "page")
    })

    it.each([
      ["draft", {}, "claim"],
      ["rejected", { available_actions: ["return_to_draft", "archive"] }, "claim"],
      ["proposed", { available_actions: ["approve", "return_to_draft", "reject"] }, "review"],
      ["approved", { available_actions: ["publish", "return_to_draft"] }, "review"],
      ["canon", { available_actions: ["supersede", "archive"] }, "who-knows"],
    ])("opens a %s claim at its %s section", async (status, extra, section) => {
      withLifecycle(lifecycle({ canon_status: status, ...extra }))
      const { router } = setup()
      await waitFor(() => expect(router.state.location.search).toBe(`?section=${section}`))
      expect(router.state.historyAction).toBe("REPLACE")
    })

    it("opens an archived claim at Publication", async () => {
      withLifecycle(lifecycle({ canon_status: "canon", lifecycle_status: "archived", available_actions: ["restore"] }))
      const { router } = setup()
      await waitFor(() => expect(router.state.location.search).toBe("?section=publication"))
    })

    it("opens the claim when the lifecycle could not be read", async () => {
      server.on("GET", /\/entities\/k1\/lifecycle$/, { status: 500 })
      const { router } = setup()
      await claimBox()
      await waitFor(() => expect(router.state.location.search).toBe("?section=claim"))
      fireEvent.click(stageLink(2))
      fireEvent.click(screen.getByRole("link", { name: "Publication" }))
      expect(await screen.findByText(/lifecycle could not be loaded/)).toBeInTheDocument()
    })

    it("walks the stages and sections with links that send no request and change no status", async () => {
      withLifecycle(lifecycle())
      const { router } = setup(`${CLAIM}?character_id=c1&party_id=p1`)
      await claimBox()
      await waitFor(() => expect(server.callsTo("GET", AUDIENCE).length).toBeGreaterThan(0))
      await waitFor(() => expect(server.callsTo("GET", "/campaigns/mundivita/sources").length).toBeGreaterThan(0))
      await waitFor(() => expect(router.state.location.search).toContain("section=claim"))
      const before = server.calls.length

      fireEvent.click(stageLink(2))
      expect(router.state.location.search).toBe("?character_id=c1&party_id=p1&section=review")
      expect(await screen.findByRole("heading", { level: 2, name: "Review claim" })).toBeInTheDocument()
      expect(screen.queryByRole("heading", { level: 2, name: "Claim" })).toBeNull()
      fireEvent.click(screen.getByRole("link", { name: "Publication" }))
      expect(router.state.location.search).toBe("?character_id=c1&party_id=p1&section=publication")
      fireEvent.click(stageLink(3))
      expect(router.state.location.search).toBe("?character_id=c1&party_id=p1&section=who-knows")
      fireEvent.click(screen.getByRole("link", { name: "Character knowledge" }))
      expect(router.state.location.search).toBe("?character_id=c1&party_id=p1&section=character")
      // A stage reopens on the section last used in it.
      fireEvent.click(stageLink(2))
      expect(router.state.location.search).toBe("?character_id=c1&party_id=p1&section=publication")
      expect(router.state.location.pathname).toBe(CLAIM)

      expect(server.calls.length).toBe(before)
      expect(server.calls.filter((c) => c.method !== "GET")).toHaveLength(0)
    })

    it("walks back through the sections with the browser history", async () => {
      withLifecycle(lifecycle())
      const { router } = setup()
      await claimBox()
      await waitFor(() => expect(router.state.location.search).toBe("?section=claim"))
      fireEvent.click(screen.getByRole("link", { name: "Sources" }))
      fireEvent.click(stageLink(3))
      expect(router.state.location.search).toBe("?section=who-knows")
      await router.navigate(-1)
      await waitFor(() => expect(router.state.location.search).toBe("?section=sources"))
      expect(await screen.findByRole("heading", { level: 2, name: "Sources" })).toBeInTheDocument()
      await router.navigate(-1)
      await waitFor(() => expect(router.state.location.search).toBe("?section=claim"))
    })

    it("replaces an unknown section, and maps the old fragments, keeping the perspective", async () => {
      withLifecycle(lifecycle())
      const first = setup(`${CLAIM}?character_id=c1&section=nonsense`)
      await waitFor(() => expect(first.router.state.location.search).toBe("?character_id=c1&section=claim"))
      expect(first.router.state.historyAction).toBe("REPLACE")
      first.unmount()

      const second = setup(`${CLAIM}?party_id=p1#who-knows`)
      await waitFor(() => expect(second.router.state.location.search).toBe("?party_id=p1&section=who-knows"))
      expect(second.router.state.location.hash).toBe("")
      expect(await screen.findByRole("heading", { level: 2, name: "Who knows this" })).toBeInTheDocument()
    })

    it("keeps a typed claim draft, source title and open roster form while another section is shown", async () => {
      withLifecycle(lifecycle({ canon_status: "canon", available_actions: ["supersede", "archive"] }))
      setup(at("claim"))
      current = { detail: detail(), view: view({ canon_status: "canon" }) }
      server.on("GET", VIEW_PATH, () => ({ body: current.view }))
      fireEvent.change(await claimBox(), { target: { value: "Draft kept" } })

      fireEvent.click(screen.getByRole("link", { name: "Sources" }))
      fireEvent.click(await screen.findByRole("button", { name: "Add source" }))
      fireEvent.change(screen.getByRole("textbox", { name: "Title" }), { target: { value: "Ledger page" } })

      fireEvent.click(stageLink(3))
      fireEvent.click(await screen.findByRole("button", { name: "Make public" }))
      expect(screen.getByRole("form", { name: "Make this public" })).toBeInTheDocument()

      // Prepare reopens on the section last used in it (Sources).
      fireEvent.click(stageLink(1))
      expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Ledger page")
      fireEvent.click(screen.getByRole("link", { name: "Claim" }))
      expect(screen.getByRole("textbox", { name: /^Claim/ })).toHaveValue("Draft kept")
      fireEvent.click(screen.getByRole("link", { name: "Sources" }))
      expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Ledger page")
      fireEvent.click(stageLink(3))
      expect(screen.getByRole("form", { name: "Make this public" })).toBeInTheDocument()
      expect(server.calls.filter((c) => c.method !== "GET")).toHaveLength(0)
    })
  })

  describe("claim section", () => {
    it("renders editable controls straight away, with no view or edit toggle", async () => {
      setup()
      expect(await claimBox()).toHaveValue("The duke is a vampire.")
      expect(screen.getByRole("combobox", { name: /Kind/ })).toHaveValue("secret")
      expect(screen.getByRole("combobox", { name: /Truth/ })).toHaveValue("true")
      expect(screen.getByRole("combobox", { name: /Sensitivity/ })).toHaveValue("secret")
      // The subject is one readable field with separate actions, not a name repeated in an input.
      const about = within(panelOf("claim")).getByText("About this World entry").parentElement as HTMLElement
      expect(within(about).getByText("Keep")).toBeInTheDocument()
      expect(within(about).getByRole("link", { name: "Open World entry" })).toBeInTheDocument()
      expect(within(about).getByRole("button", { name: "Change subject" })).toBeInTheDocument()
      expect(within(about).getByRole("button", { name: "Clear subject" })).toBeInTheDocument()
      expect(within(about).queryByRole("combobox")).toBeNull()
      expect(screen.queryByRole("button", { name: /^Edit/ })).toBeNull()
    })

    it("lets an editor set a subject on an unlinked claim, inside the same About block", async () => {
      current = { detail: detail({ subject: null }), view: view({ subject: null }) }
      server.on("GET", DETAIL, () => ({ body: current.detail }))
      server.on("GET", VIEW_PATH, () => ({ body: current.view }))
      openApp(CLAIM, ["canon.edit"])
      await claimBox()
      const about = within(panelOf("claim")).getByText("About this World entry").parentElement as HTMLElement
      expect(within(about).getByRole("combobox", { name: "Subject" })).toBeInTheDocument()
      expect(within(about).queryByRole("link")).toBeNull()
    })

    it("shows the subject once, with Open, Change and Clear as separate actions", async () => {
      withLifecycle(lifecycle())
      setup()
      await claimBox()
      const aboutBlock = () => within(panelOf("claim")).getByText("About this World entry").parentElement as HTMLElement
      expect(within(aboutBlock()).getAllByText("Keep")).toHaveLength(1)
      expect(within(aboutBlock()).getByRole("link", { name: "Open World entry" })).toHaveAttribute(
        "href",
        "/app/mundivita/world/location/l1",
      )
      fireEvent.click(within(aboutBlock()).getByRole("button", { name: "Change subject" }))
      expect(within(aboutBlock()).getByRole("combobox", { name: "Subject" })).toBeInTheDocument()
      fireEvent.focus(within(aboutBlock()).getByRole("combobox", { name: "Subject" }))
      fireEvent.click(await within(aboutBlock()).findByRole("option", { name: /Harbor/ }))
      // The unsaved choice is shown as such, with no stale link to open.
      expect(within(aboutBlock()).getByText("Harbor")).toBeInTheDocument()
      expect(within(aboutBlock()).getByText("not saved yet")).toBeInTheDocument()
      expect(within(aboutBlock()).queryByRole("link", { name: "Open World entry" })).toBeNull()
      expect(screen.getByText("Unsaved changes to the claim")).toBeInTheDocument()
    })

    it("clears the subject as an unsaved change that Discard undoes, and saves it as null", async () => {
      server.on("POST", UPDATE, { body: RECEIPT })
      setup()
      await claimBox()
      const aboutBlock = () => within(panelOf("claim")).getByText("About this World entry").parentElement as HTMLElement
      fireEvent.click(within(aboutBlock()).getByRole("button", { name: "Clear subject" }))
      expect(within(aboutBlock()).getByText("No subject (not saved yet)")).toBeInTheDocument()
      expect(within(aboutBlock()).getByRole("combobox", { name: "Subject" })).toBeInTheDocument()
      fireEvent.click(screen.getByRole("button", { name: "Discard changes" }))
      expect(within(aboutBlock()).getByText("Keep")).toBeInTheDocument()
      fireEvent.click(within(aboutBlock()).getByRole("button", { name: "Clear subject" }))
      fireEvent.click(screen.getByRole("button", { name: "Save claim" }))
      await waitFor(() => expect(server.callsTo("POST", UPDATE)).toHaveLength(1))
      expect(server.callsTo("POST", UPDATE)[0]!.body).toMatchObject({ subject_entity_id: null })
    })

    it("freezes claim, kind and subject once someone knows it, and says why", async () => {
      setup()
      current = { detail: detail(), view: view({ in_use: true, field_locks: ["statement", "knowledge_type", "subject"] }) }
      server.on("GET", VIEW_PATH, () => ({ body: current.view }))
      const box = await claimBox()
      await waitFor(() => expect(box).toBeDisabled())
      expect(screen.getByRole("combobox", { name: /Kind/ })).toBeDisabled()
      expect(screen.queryByRole("combobox", { name: "Subject" })).toBeNull()
      expect(screen.queryByRole("button", { name: /Change subject|Clear subject/ })).toBeNull()
      expect(screen.getByText(/The subject cannot change/)).toBeInTheDocument()
      expect(within(panelOf("claim")).getByRole("link", { name: "Open World entry" })).toBeInTheDocument()
      expect(screen.getByRole("combobox", { name: /Truth/ })).toBeEnabled()
    })

    it.each([
      ["proposed", "in review", "Return it to draft to edit it."],
      ["approved", "approved", "Return it to draft to edit it."],
      ["rejected", "rejected", "Return it to draft to rework it."],
    ])("shows a %s claim as text with one line saying how to edit it", async (status, word, step) => {
      withLifecycle(lifecycle({ canon_status: status, available_actions: ["return_to_draft"] }))
      setup(at("claim"))
      current = {
        detail: detail(),
        view: view({
          canon_status: status,
          available_actions: [],
          blocked_actions: [{ action: "update", reason: "review_in_progress" }],
        }),
      }
      server.on("GET", VIEW_PATH, () => ({ body: current.view }))
      const note = await screen.findByText(new RegExp(`This claim is ${word}. ${step}`))
      expect(within(note).getByRole("link", { name: "Open Publication" })).toHaveAttribute(
        "href",
        `${CLAIM}?section=publication`,
      )
      expect(screen.queryByRole("textbox", { name: /^Claim/ })).toBeNull()
      expect(screen.queryByRole("button", { name: "Save claim" })).toBeNull()
      expect(screen.getByRole("heading", { name: "GM and canonical information" })).toBeInTheDocument()
    })

    it("keeps the claim editable when nobody may see who knows it", async () => {
      setup()
      server.on("GET", AUDIENCE, { status: 403 })
      expect(await claimBox()).toBeEnabled()
      await waitFor(() => expect(server.callsTo("GET", AUDIENCE).length).toBeGreaterThan(0))
      expect(within(panelOf("who-knows")).queryByText(/Red Company/)).toBeNull()
    })
  })

  describe("a reader", () => {
    it("shows readable values, with no stages, no editing actions and no editor requests", async () => {
      setup(CLAIM, ["campaign.view"])
      expect(await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })).toBeInTheDocument()
      expect(screen.queryByRole("textbox")).toBeNull()
      expect(screen.queryByRole("navigation", { name: "Claim stages" })).toBeNull()
      expect(screen.queryByRole("combobox", { name: /Kind|Truth|Sensitivity|Subject/ })).toBeNull()
      expect(screen.queryByRole("button", { name: /Save claim|Discard changes/ })).toBeNull()
      expect(screen.getByRole("heading", { name: "GM and canonical information" })).toBeInTheDocument()
      expect(screen.getByText("Truth")).toBeInTheDocument()
      expect(screen.getByRole("heading", { name: "Character knowledge" })).toBeInTheDocument()
      expect(screen.queryByRole("heading", { name: "Who knows this" })).toBeNull()
      expect(screen.queryByRole("group", { name: "Record status" })).toBeNull()
      expect(screen.getByRole("link", { name: "Keep" })).toHaveAttribute("href", "/app/mundivita/world/location/l1")
      expect(server.calls.some((c) => /\/authoring\/|\/audience$|lifecycle|provenance|\/sources/.test(c.path))).toBe(false)
    })

    it("ignores a section in the address and does not rewrite it", async () => {
      const { router } = setup(`${CLAIM}?section=publication`, ["campaign.view"])
      await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })
      expect(router.state.location.search).toBe("?section=publication")
      expect(screen.queryByRole("navigation", { name: "Claim stages" })).toBeNull()
    })

    it("keeps restricted canonical fields absent when the server withheld them", async () => {
      current = { detail: detail({ truth_status_code: null, sensitivity: null }), view: view() }
      server.on("GET", DETAIL, () => ({ body: current.detail }))
      openApp(CLAIM, ["campaign.view"])
      await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })
      expect(screen.queryByRole("heading", { name: "GM and canonical information" })).toBeNull()
      expect(screen.queryByText("Truth")).toBeNull()
      expect(screen.queryByText("Sensitivity")).toBeNull()
      expect(screen.queryByText("Not recorded")).toBeNull()
    })

    it("omits the About block when the server returned no subject", async () => {
      current = { detail: detail({ subject: null }), view: view({ subject: null }) }
      server.on("GET", DETAIL, () => ({ body: current.detail }))
      server.on("GET", VIEW_PATH, () => ({ body: current.view }))
      openApp(CLAIM, ["campaign.view"])
      await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })
      expect(screen.queryByText("About this World entry")).toBeNull()
    })

    it("shows only what is recorded for the perspective in the address", async () => {
      current = {
        detail: detail({ awareness_level: "understood", confidence: 85, willing_to_share: null }),
        view: view(),
      }
      server.on("GET", DETAIL, () => ({ body: current.detail }))
      openApp(`${CLAIM}?character_id=c1`, ["campaign.view"])
      expect(await screen.findByText("Understood")).toBeInTheDocument()
      expect(screen.getByText("85%")).toBeInTheDocument()
      expect(screen.queryByText("Willing to share")).toBeNull()
      expect(server.calls.some((c) => c.path.includes("character_id=c1"))).toBe(true)
    })

    it("says so when the selected character has nothing recorded", async () => {
      setup(`${CLAIM}?character_id=c1`, ["campaign.view"])
      expect(await screen.findByText(/no recorded knowledge of this claim/)).toBeInTheDocument()
    })

    it("shows an editor the same character knowledge in Use in play", async () => {
      current = {
        detail: detail({ awareness_level: "understood", confidence: 85, willing_to_share: true }),
        view: view(),
      }
      server.on("GET", DETAIL, () => ({ body: current.detail }))
      server.on("GET", VIEW_PATH, () => ({ body: current.view }))
      openApp(at("character", "character_id=c1"), ["canon.edit"])
      expect(await screen.findByText("Understood")).toBeInTheDocument()
      expect(screen.getByText("Willing to share")).toBeInTheDocument()
    })
  })

  describe("saving the claim", () => {
    it("enables Save and Discard only for a change, and discards it", async () => {
      setup()
      const box = await claimBox()
      const save = screen.getByRole("button", { name: "Save claim" })
      const discard = screen.getByRole("button", { name: "Discard changes" })
      expect(save).toBeDisabled()
      expect(discard).toBeDisabled()
      fireEvent.change(box, { target: { value: "Changed" } })
      expect(screen.getByText("Unsaved changes to the claim")).toBeInTheDocument()
      expect(save).toBeEnabled()
      fireEvent.click(discard)
      expect(box).toHaveValue("The duke is a vampire.")
      expect(save).toBeDisabled()
      expect(server.callsTo("POST", /./)).toHaveLength(0)
    })

    it("saves against the loaded version, stays on the page and confirms only after the server answers", async () => {
      const { router } = setup()
      server.on("POST", UPDATE, () => {
        current = { detail: detail({ truth_status_code: "false" }), view: view({ truth_status: "false", row_version: 2 }) }
        return { body: RECEIPT }
      })
      await claimBox()
      fireEvent.change(screen.getByRole("combobox", { name: /Truth/ }), { target: { value: "false" } })
      fireEvent.click(screen.getByRole("button", { name: "Save claim" }))
      expect(screen.queryByText("Claim saved")).toBeNull()
      expect(await screen.findByText("Claim saved")).toBeInTheDocument()
      expect(server.callsTo("POST", UPDATE)[0]!.body).toEqual({
        expected_row_version: 1,
        statement: "The duke is a vampire.",
        knowledge_type: "secret",
        truth_status: "false",
        sensitivity: "secret",
        subject_entity_id: "l1",
        change_note: null,
      })
      expect(router.state.location.pathname).toBe(CLAIM)
      expect(screen.getByRole("combobox", { name: /Truth/ })).toHaveValue("false")
      expect(screen.getByRole("button", { name: "Save claim" })).toBeDisabled()
    })

    it("asks before changing a published claim", async () => {
      setup()
      current = { detail: detail(), view: view({ canon_status: "canon" }) }
      server.on("GET", VIEW_PATH, () => ({ body: current.view }))
      server.on("POST", UPDATE, { body: RECEIPT })
      await claimBox()
      await screen.findByRole("textbox", { name: /Change note/ })
      fireEvent.change(screen.getByRole("textbox", { name: /^Claim/ }), { target: { value: "Edited" } })
      fireEvent.change(screen.getByRole("textbox", { name: /Change note/ }), { target: { value: "typo" } })
      fireEvent.click(screen.getByRole("button", { name: "Save claim" }))
      const dialog = await screen.findByRole("dialog", { name: "Save changes to a published claim?" })
      expect(server.callsTo("POST", UPDATE)).toHaveLength(0)
      fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }))
      await waitFor(() => expect(server.callsTo("POST", UPDATE)).toHaveLength(1))
      expect(server.callsTo("POST", UPDATE)[0]!.body).toMatchObject({ statement: "Edited", change_note: "typo" })
    })

    it("validates before sending anything", async () => {
      setup()
      fireEvent.change(await claimBox(), { target: { value: "  " } })
      fireEvent.click(screen.getByRole("button", { name: "Save claim" }))
      expect((await screen.findAllByText(/Statement is required/)).length).toBeGreaterThan(0)
      expect(server.callsTo("POST", UPDATE)).toHaveLength(0)
    })

    it("keeps the draft and shows the error when the save fails", async () => {
      setup()
      server.on("POST", UPDATE, { status: 500 })
      fireEvent.change(await claimBox(), { target: { value: "Mine" } })
      fireEvent.click(screen.getByRole("button", { name: "Save claim" }))
      expect(await screen.findByRole("alert")).toBeInTheDocument()
      expect(screen.getByRole("textbox", { name: /^Claim/ })).toHaveValue("Mine")
      expect(screen.queryByText("Claim saved")).toBeNull()
      expect(screen.getByText("Unsaved changes to the claim")).toBeInTheDocument()
    })

    it("keeps the draft across a stale write and resubmits against the latest version", async () => {
      setup()
      let attempts = 0
      server.on("POST", UPDATE, () => {
        attempts += 1
        if (attempts === 1) return STALE
        return { body: RECEIPT }
      })
      fireEvent.change(await claimBox(), { target: { value: "Mine" } })
      fireEvent.click(screen.getByRole("button", { name: "Save claim" }))
      expect(await screen.findByRole("alert")).toHaveTextContent("Someone else changed this record")
      current = { detail: detail(), view: view({ row_version: 6, sensitivity: "public" }) }
      fireEvent.click(screen.getByRole("button", { name: "Load latest version" }))
      await waitFor(() => expect(screen.getByRole("combobox", { name: /Sensitivity/ })).toHaveValue("public"))
      expect(screen.getByRole("textbox", { name: /^Claim/ })).toHaveValue("Mine")
      fireEvent.click(screen.getByRole("button", { name: "Save claim" }))
      await waitFor(() => expect(server.callsTo("POST", UPDATE)).toHaveLength(2))
      expect(server.callsTo("POST", UPDATE)[1]!.body).toMatchObject({ expected_row_version: 6, statement: "Mine" })
    })
  })

  describe("Review & publish", () => {
    it("explains a draft and offers the next step with no list of unavailable actions", async () => {
      withLifecycle(lifecycle())
      setup(at("publication"))
      const group = await screen.findByRole("group", { name: "Lifecycle" })
      expect(screen.getByText(/Submit it for review when it is ready/)).toBeInTheDocument()
      expect(within(group).getByRole("button", { name: "Submit for review" })).toBeInTheDocument()
      expect(within(group).queryByRole("button", { name: "Reject" })).not.toBeVisible()
      fireEvent.click(within(group).getByText("More"))
      for (const name of ["Reject", "Archive", "Delete draft"]) {
        expect(within(group).getByRole("button", { name })).toBeInTheDocument()
      }
      expect(screen.queryByText(/unavailable:/)).toBeNull()
      expect(screen.queryByRole("heading", { name: "Lifecycle" })).toBeNull()
    })

    it.each([
      ["draft", ["submit_for_review", "reject", "archive"], "Submit for review", "publication"],
      ["proposed", ["approve", "return_to_draft", "reject"], "Approve", "review"],
      ["approved", ["publish", "return_to_draft"], "Publish as canon", "publication"],
      ["rejected", ["return_to_draft", "archive"], "Return it to draft to rework it", "publication"],
    ])("points a %s claim at the real next step in the header", async (status, actions, text, section) => {
      withLifecycle(lifecycle({ canon_status: status, available_actions: actions }))
      setup()
      const next = await screen.findByRole("link", { name: new RegExp(text) })
      expect(next).toHaveAttribute("href", `${CLAIM}?section=${section}`)
      // Never points at an action the person cannot take.
      if (status !== "approved") expect(screen.queryByRole("button", { name: "Publish as canon" })).toBeNull()
    })

    it("sends no request when the Next link is followed", async () => {
      withLifecycle(lifecycle())
      const { router } = setup(at("claim"))
      await claimBox()
      const before = server.calls.length
      fireEvent.click(screen.getByRole("link", { name: /Submit for review/ }))
      expect(router.state.location.search).toBe("?section=publication")
      expect(server.calls.length).toBe(before)
    })

    it("says no step is available rather than naming one that is not there", async () => {
      withLifecycle(lifecycle({ available_actions: [] }))
      setup(at("publication"))
      expect(await screen.findByText(/No lifecycle action is available to you right now/)).toBeInTheDocument()
      expect(screen.queryByText(/Next:/)).toBeNull()
    })

    it("names the subject as the blocker of an approved claim whose subject is not published (D1)", async () => {
      withLifecycle(
        lifecycle({
          canon_status: "approved",
          available_actions: ["return_to_draft"],
          blocked_actions: [{ action: "publish", reason: "reference_not_published" }],
        }),
      )
      setup(at("publication"))
      const next = await screen.findByRole("link", { name: /Publish its subject first/ })
      expect(next).toHaveAttribute("href", "/app/mundivita/world/location/l1")
      expect(screen.queryByText(/then submit it for review/)).toBeNull()
      const panel = panelOf("publication")
      expect(within(panel).getByText(/must be published first/)).toHaveTextContent("Its subject, Keep,")
      expect(within(panel).getByRole("link", { name: "Open World entry" })).toHaveAttribute(
        "href",
        "/app/mundivita/world/location/l1",
      )
      expect(within(panel).queryByRole("button", { name: "Publish as canon" })).toBeNull()
    })

    it("says publishing tells nobody, and points to Use in play, for a published claim", async () => {
      withLifecycle(lifecycle({ canon_status: "canon", available_actions: ["supersede", "archive"] }))
      setup(at("publication"))
      const note = await screen.findByText(/Publishing does not tell anyone/)
      expect(within(note).getByRole("link", { name: "record who knows it" })).toHaveAttribute(
        "href",
        `${CLAIM}?section=who-knows`,
      )
      expect(screen.getByRole("link", { name: /Record who knows it/ })).toHaveAttribute("href", `${CLAIM}?section=who-knows`)
      expect(within(panelOf("publication")).queryByText(/source/i)).toBeNull()
    })

    it("summarises exactly what a reviewer approves and ends with the Approve button", async () => {
      withLifecycle(lifecycle({ canon_status: "proposed", available_actions: ["approve", "return_to_draft", "reject"] }))
      server.on("GET", /\/entities\/k1\/provenance$/, {
        body: {
          ...PROVENANCE,
          links: [
            { source_id: "s1", source_type_label: "Note", title: "Ledger", reference: null, attached_at: "2026-10-04T00:00:00Z", attached_by_name: null, detached_at: null, detached_by_name: null, is_attached: true },
          ],
        },
      })
      setup(at("review"))
      current = { detail: detail(), view: view({ canon_status: "proposed", available_actions: [], in_use: true }) }
      server.on("GET", VIEW_PATH, () => ({ body: current.view }))
      const panel = await findPanel("review")
      expect(await within(panel).findByText("1 attached")).toBeInTheDocument()
      expect(within(panel).getByText("The duke is a vampire.")).toBeInTheDocument()
      expect(within(panel).getByText("Keep")).toBeInTheDocument()
      expect(within(panel).getAllByText("Secret")).toHaveLength(2)
      expect(within(panel).getByText(/Someone has already been recorded as knowing it/)).toBeInTheDocument()
      expect(within(panel).getByRole("link", { name: "Edit in Claim" })).toHaveAttribute("href", `${CLAIM}?section=claim`)
      server.on("POST", `${LIFECYCLE}/approve`, { body: { entity_id: "k1", canon_status: "approved", row_version: 3 } })
      fireEvent.click(within(panel).getByRole("button", { name: "Approve" }))
      const dialog = await screen.findByRole("dialog", { name: "Approve this record?" })
      expect(server.callsTo("POST", /./)).toHaveLength(0)
      fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }))
      await waitFor(() => expect(server.callsTo("POST", `${LIFECYCLE}/approve`)).toHaveLength(1))
      expect(server.callsTo("POST", `${LIFECYCLE}/approve`)[0]!.body).toEqual({ expected_row_version: 2 })
    })

    it("offers no decision in Review when the person cannot approve or publish", async () => {
      withLifecycle(lifecycle({ canon_status: "proposed", available_actions: [] }))
      setup(at("review"))
      const panel = await findPanel("review")
      await within(panel).findByText("The duke is a vampire.")
      expect(within(panel).queryByRole("button")).toBeNull()
    })

    it("warns in Review and Publication about unsaved claim edits, which are not part of the step", async () => {
      withLifecycle(lifecycle())
      setup()
      fireEvent.change(await claimBox(), { target: { value: "Not saved yet" } })
      fireEvent.click(stageLink(2))
      const review = panelOf("review")
      expect(within(review).getByText(/unsaved changes to the claim/i)).toHaveTextContent("not part of review or publication")
      expect(within(review).getByText("The duke is a vampire.", { selector: "dd" })).toBeInTheDocument()
      fireEvent.click(screen.getByRole("link", { name: "Publication" }))
      expect(within(panelOf("publication")).getByText(/unsaved changes to the claim/i)).toBeInTheDocument()
    })

    it("asks first when a lifecycle step meets unsaved claim edits, keeps the edits and shows them as not applied (D4)", async () => {
      let submitted = false
      server.on("GET", LIFECYCLE, () => ({
        body: submitted
          ? lifecycle({ canon_status: "proposed", row_version: 3, available_actions: ["approve", "return_to_draft", "reject"] })
          : lifecycle(),
      }))
      server.on("POST", `${LIFECYCLE}/submit-for-review`, () => {
        submitted = true
        current = {
          detail: current.detail,
          view: view({
            canon_status: "proposed",
            row_version: 3,
            available_actions: [],
            blocked_actions: [{ action: "update", reason: "review_in_progress" }],
          }),
        }
        return { body: { entity_id: "k1", canon_status: "proposed", row_version: 3, changed: true } }
      })
      setup()
      fireEvent.change(await claimBox(), { target: { value: "Not saved yet" } })
      fireEvent.click(stageLink(2))
      fireEvent.click(screen.getByRole("link", { name: "Publication" }))
      fireEvent.click(await screen.findByRole("button", { name: "Submit for review" }))
      const dialog = await screen.findByRole("dialog", { name: "Submit for review?" })
      expect(dialog).toHaveTextContent(/unsaved edits are not part of this change/)
      expect(server.callsTo("POST", /./)).toHaveLength(0)
      fireEvent.click(within(dialog).getByRole("button", { name: "Submit for review" }))
      await waitFor(() => expect(server.callsTo("POST", `${LIFECYCLE}/submit-for-review`)).toHaveLength(1))
      expect(server.callsTo("POST", UPDATE)).toHaveLength(0)

      // The form is gone, but the draft is not invisible: it is shown as not applied.
      fireEvent.click(stageLink(1))
      const notice = await screen.findByText(/Unsaved changes not applied/)
      expect(notice.closest("div")).toHaveTextContent("Not saved yet")
      expect(screen.queryByRole("textbox", { name: /^Claim/ })).toBeNull()
      fireEvent.click(screen.getByRole("button", { name: "Discard changes" }))
      expect(screen.queryByText(/Unsaved changes not applied/)).toBeNull()
      // With the draft discarded a later step no longer warns.
      fireEvent.click(stageLink(2))
      expect(within(panelOf("review")).queryByText(/unsaved changes/i)).toBeNull()
    })

    it("submits for review at once when there are no unsaved edits", async () => {
      withLifecycle(lifecycle())
      server.on("POST", `${LIFECYCLE}/submit-for-review`, {
        body: { entity_id: "k1", canon_status: "proposed", row_version: 3, changed: true },
      })
      setup(at("publication"))
      fireEvent.click(await screen.findByRole("button", { name: "Submit for review" }))
      await waitFor(() => expect(server.callsTo("POST", `${LIFECYCLE}/submit-for-review`)).toHaveLength(1))
      expect(screen.queryByRole("dialog")).toBeNull()
    })

    it("keeps a destructive lifecycle action behind its confirmation", async () => {
      withLifecycle(lifecycle())
      setup(at("publication"))
      const group = await screen.findByRole("group", { name: "Lifecycle" })
      fireEvent.click(within(group).getByText("More"))
      fireEvent.click(within(group).getByRole("button", { name: "Delete draft" }))
      const dialog = await screen.findByRole("dialog", { name: "Delete this draft?" })
      expect(server.callsTo("POST", /./)).toHaveLength(0)
      fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
      expect(server.callsTo("POST", /./)).toHaveLength(0)
    })

    it("keeps the claim draft when a lifecycle step fails", async () => {
      withLifecycle(lifecycle())
      server.on("POST", `${LIFECYCLE}/submit-for-review`, { status: 500 })
      setup()
      fireEvent.change(await claimBox(), { target: { value: "Mine" } })
      fireEvent.click(stageLink(2))
      fireEvent.click(screen.getByRole("link", { name: "Publication" }))
      fireEvent.click(await screen.findByRole("button", { name: "Submit for review" }))
      const dialog = await screen.findByRole("dialog", { name: "Submit for review?" })
      fireEvent.click(within(dialog).getByRole("button", { name: "Submit for review" }))
      expect(await within(await screen.findByRole("dialog")).findByRole("alert")).toBeInTheDocument()
      fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }))
      fireEvent.click(stageLink(1))
      expect(screen.getByRole("textbox", { name: /^Claim/ })).toHaveValue("Mine")
    })

    it("sends a deleted draft to the Knowledge list, not the World list (D5)", async () => {
      withLifecycle(lifecycle())
      server.on("POST", `${LIFECYCLE}/delete-draft`, { body: { entity_id: "k1", deleted: true } })
      const { router } = setup(at("publication", "character_id=c1"))
      const group = await screen.findByRole("group", { name: "Lifecycle" })
      fireEvent.click(within(group).getByText("More"))
      fireEvent.click(within(group).getByRole("button", { name: "Delete draft" }))
      const dialog = await screen.findByRole("dialog", { name: "Delete this draft?" })
      fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason/ }), { target: { value: "Duplicate" } })
      fireEvent.click(within(dialog).getByRole("button", { name: "Delete draft" }))
      await waitFor(() => expect(router.state.location.pathname).toBe("/app/mundivita/knowledge"))
      expect(router.state.location.search).toBe("?character_id=c1")
    })
  })

  describe("sources", () => {
    it("says sources are optional and allowed at any status, and keeps the add form compact", async () => {
      withLifecycle(lifecycle({ canon_status: "approved", available_actions: ["publish", "return_to_draft"] }))
      setup(at("sources"))
      expect(await screen.findByText(/They are optional, can be changed at any status/)).toHaveTextContent(
        "do not affect review or publication",
      )
      expect(screen.getByText("GM entry", { selector: "strong" })).toBeInTheDocument()
      expect(screen.getByRole("link", { name: "View provenance" })).toBeInTheDocument()
      expect(screen.queryByRole("form", { name: "Write a new source" })).toBeNull()
      expect(screen.getByRole("button", { name: "Add source" })).toHaveAttribute("aria-expanded", "false")
      expect(screen.queryByRole("heading", { level: 2, name: "Sources" })).toBeInTheDocument()
      expect(screen.getAllByRole("heading", { name: "Sources" })).toHaveLength(1)
    })

    it("keeps what was typed when the add form is closed, and after a failed write", async () => {
      server.on("POST", /\/campaigns\/mundivita\/sources/, { status: 500 })
      setup(at("sources"))
      fireEvent.click(await screen.findByRole("button", { name: "Add source" }))
      const form = screen.getByRole("form", { name: "Write a new source" })
      fireEvent.change(within(form).getByRole("combobox"), { target: { value: "note" } })
      fireEvent.change(within(form).getByRole("textbox", { name: "Title" }), { target: { value: "Ledger page" } })
      fireEvent.click(within(form).getByRole("button", { name: "Write and attach source" }))
      expect(await screen.findAllByRole("alert")).not.toHaveLength(0)
      fireEvent.click(screen.getByRole("button", { name: "Hide add source" }))
      expect(screen.queryByRole("form", { name: "Write a new source" })).toBeNull()
      fireEvent.click(screen.getByRole("button", { name: "Add source" }))
      expect(
        within(screen.getByRole("form", { name: "Write a new source" })).getByRole("textbox", { name: "Title" }),
      ).toHaveValue("Ledger page")
    })

    it("sends two different idempotency keys when it writes and attaches a source (D8)", async () => {
      server.on("POST", /\/campaigns\/mundivita\/sources$/, {
        body: { source_id: "s9", source_type: "note", source_type_label: "Note", title: "Ledger page", reference: null, created_by_name: null, attached_count: 0 },
      })
      server.on("POST", /\/entities\/k1\/sources\/attach$/, { body: PROVENANCE })
      setup(at("sources"))
      fireEvent.click(await screen.findByRole("button", { name: "Add source" }))
      const form = screen.getByRole("form", { name: "Write a new source" })
      fireEvent.change(within(form).getByRole("combobox"), { target: { value: "note" } })
      fireEvent.change(within(form).getByRole("textbox", { name: "Title" }), { target: { value: "Ledger page" } })
      fireEvent.click(within(form).getByRole("button", { name: "Write and attach source" }))
      await waitFor(() => expect(server.callsTo("POST", /\/entities\/k1\/sources\/attach$/)).toHaveLength(1))
      const create = server.callsTo("POST", /\/campaigns\/mundivita\/sources$/)[0]!.headers["Idempotency-Key"]!
      const attach = server.callsTo("POST", /\/entities\/k1\/sources\/attach$/)[0]!.headers["Idempotency-Key"]!
      expect(create).not.toBe(attach)
      expect(create).toMatch(/\.create$/)
      expect(attach).toMatch(/\.attach$/)
      expect(create.replace(/\.create$/, "")).toBe(attach.replace(/\.attach$/, ""))
      // Header-safe characters only, as the server requires.
      expect(create).toMatch(/^[A-Za-z0-9._~-]{1,255}$/)
    })

    it("opens the provenance page and returns to the Sources section with the perspective (D6)", async () => {
      const { router } = setup(at("sources", "character_id=c1"))
      fireEvent.click(await screen.findByRole("link", { name: "View provenance" }))
      expect(await screen.findByRole("heading", { level: 1, name: "Provenance" })).toBeInTheDocument()
      const back = await screen.findByRole("link", { name: "x" })
      expect(back).toHaveAttribute("href", "/app/mundivita/knowledge/k1?character_id=c1&section=sources")
      fireEvent.click(back)
      await waitFor(() => expect(router.state.location.pathname).toBe(CLAIM))
      expect(router.state.location.search).toBe("?character_id=c1&section=sources")
    })

    it("protects a typed source with the unsaved-changes dialog when the person leaves (D7)", async () => {
      const { router } = setup(at("sources"))
      fireEvent.click(await screen.findByRole("button", { name: "Add source" }))
      fireEvent.change(screen.getByRole("textbox", { name: "Title" }), { target: { value: "Ledger page" } })
      fireEvent.click(breadcrumbKnowledge())
      const dialog = await screen.findByRole("dialog", { name: "Discard unsaved changes?" })
      expect(dialog).toHaveTextContent("a source")
      expect(router.state.location.pathname).toBe(CLAIM)
      fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
      expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Ledger page")
      fireEvent.click(breadcrumbKnowledge())
      fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Discard changes" }))
      await waitFor(() => expect(router.state.location.pathname).toBe("/app/mundivita/knowledge"))
    })

    it("protects a source type chosen without a title or reference", async () => {
      setup(at("sources"))
      fireEvent.click(await screen.findByRole("button", { name: "Add source" }))
      const type = within(screen.getByRole("form", { name: "Write a new source" })).getByRole("combobox")
      fireEvent.change(type, { target: { value: "note" } })
      fireEvent.click(breadcrumbKnowledge())
      const dialog = await screen.findByRole("dialog", { name: "Discard unsaved changes?" })
      expect(dialog).toHaveTextContent("a source")
      fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
      expect(type).toHaveValue("note")
    })

    it.each([
      ["Record who learned this", "Record that someone learned this", /How they hold it/, "rumored", "learn"],
      ["Record a telling", "Record that someone told another", /How they hold it/, "suspected", "awareness"],
      ["Record a telling", "Record that someone told another", /^How$/, "rumor", "method"],
      ["Tell a party", "Tell a party", /What the party learns/, "rumored", "party"],
      ["Make public", "Make this public", /How it is known there/, "rumored", "public"],
    ])("protects a choice-only change in %s (%s)", async (open, formName, label, value) => {
      setupPublished(at("who-knows"))
      fireEvent.click(await screen.findByRole("button", { name: open }))
      const select = within(screen.getByRole("form", { name: formName })).getByRole("combobox", { name: label })
      fireEvent.change(select, { target: { value } })
      fireEvent.click(breadcrumbKnowledge())
      const dialog = await screen.findByRole("dialog", { name: "Discard unsaved changes?" })
      expect(dialog).toHaveTextContent("a knowledge entry")
      fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
      expect(select).toHaveValue(value)
    })

    it("does not warn about an untouched source or knowledge form", async () => {
      setupPublished(at("who-knows"))
      fireEvent.click(await screen.findByRole("button", { name: "Record who learned this" }))
      fireEvent.click(breadcrumbKnowledge())
      expect(screen.queryByRole("dialog", { name: "Discard unsaved changes?" })).toBeNull()
    })

    it("does not block leaving when nothing is unsaved", async () => {
      const { router } = setup(at("sources"))
      await screen.findByRole("button", { name: "Add source" })
      fireEvent.click(breadcrumbKnowledge())
      await waitFor(() => expect(router.state.location.pathname).toBe("/app/mundivita/knowledge"))
      expect(screen.queryByRole("dialog", { name: "Discard unsaved changes?" })).toBeNull()
    })
  })

  describe("Use in play", () => {
    it("lists parties, individuals and public places as separate compact groups", async () => {
      setupPublished(at("who-knows"))
      await screen.findByText("Red Company")
      expect(screen.getByRole("heading", { level: 3, name: "Parties" })).toBeInTheDocument()
      expect(screen.getByRole("heading", { level: 3, name: "Characters, NPCs and organizations" })).toBeInTheDocument()
      expect(screen.getByRole("heading", { level: 3, name: "Public places" })).toBeInTheDocument()
      const mira = screen.getByRole("listitem", { name: "Mira" })
      expect(within(mira).getByText("Npc")).toBeInTheDocument()
      expect(within(mira).getByText("Suspects, 60% sure")).toBeInTheDocument()
      expect(screen.getByText("Stonebridge")).toBeInTheDocument()
      expect(screen.getByText(/To undo a record, correct the event that made it/)).toBeInTheDocument()
      // Details stay collapsed until asked for.
      expect(screen.queryByText("He only seems pale.")).toBeNull()
      expect(screen.queryByRole("form", { name: /Tell a party|Make this public|learned this|told another|belief/ })).toBeNull()
    })

    it("puts each group's actions beside its heading and reveals forms locally", async () => {
      setupPublished(at("who-knows"))
      await screen.findByText("Red Company")
      const partiesHead = screen.getByRole("heading", { level: 3, name: "Parties" }).parentElement!
      expect(within(partiesHead).getByRole("button", { name: "Tell a party" })).toBeInTheDocument()
      const knowersHead = screen.getByRole("heading", { level: 3, name: "Characters, NPCs and organizations" }).parentElement!
      expect(within(knowersHead).getByRole("button", { name: "Record who learned this" })).toBeInTheDocument()
      expect(within(knowersHead).getByRole("button", { name: "Record a telling" })).toBeInTheDocument()
      const publicHead = screen.getByRole("heading", { level: 3, name: "Public places" }).parentElement!
      fireEvent.click(within(publicHead).getByRole("button", { name: "Make public" }))
      expect(screen.getByRole("form", { name: "Make this public" })).toBeInTheDocument()
      expect(screen.queryByRole("form", { name: "Tell a party" })).toBeNull()
    })

    it("tells only parties that do not know it, then closes the form after the server confirms", async () => {
      setupPublished(at("who-knows"))
      fireEvent.click(await screen.findByRole("button", { name: "Tell a party" }))
      const form = screen.getByRole("form", { name: "Tell a party" })
      const select = within(form).getByRole("combobox", { name: /Party/ })
      expect(within(select).queryByRole("option", { name: "Red Company" })).toBeNull()
      fireEvent.click(within(form).getByRole("button", { name: "Tell party" }))
      expect(await within(form).findByText("Choose a party.")).toBeInTheDocument()
      expect(server.callsTo("POST", `${KNOWLEDGE}/k1/reveal-to-party`)).toHaveLength(0)
      fireEvent.change(select, { target: { value: "p2" } })
      fireEvent.click(within(form).getByRole("button", { name: "Tell party" }))
      await waitFor(() => expect(server.callsTo("POST", `${KNOWLEDGE}/k1/reveal-to-party`)).toHaveLength(1))
      expect(server.callsTo("POST", `${KNOWLEDGE}/k1/reveal-to-party`)[0]!.body).toEqual({
        party_id: "p2",
        awareness_level: "aware",
      })
      await waitFor(() => expect(screen.queryByRole("form", { name: "Tell a party" })).toBeNull())
    })

    it("says so when every active party already knows it", async () => {
      server.on("GET", AUDIENCE, () => ({
        body: {
          ...audience(),
          parties: [
            ...audience().parties,
            { party_knowledge_id: "pk2", party_id: "p2", party_name: "Blue Company", awareness_level: "aware" },
          ],
        },
      }))
      setupPublished(at("who-knows"))
      expect(await screen.findByText("Every active party already knows this.")).toBeInTheDocument()
      expect(screen.queryByRole("button", { name: "Tell a party" })).toBeNull()
    })

    it("keeps the form and what was typed when a knowledge action is refused", async () => {
      setupPublished(at("who-knows"))
      server.on("POST", `${KNOWLEDGE}/k1/reveal-to-party`, {
        status: 409,
        body: { error: { code: "clock_required", message: "m", correlation_id: "c" } },
      })
      fireEvent.click(await screen.findByRole("button", { name: "Tell a party" }))
      const form = screen.getByRole("form", { name: "Tell a party" })
      fireEvent.change(within(form).getByRole("combobox", { name: /Party/ }), { target: { value: "p2" } })
      fireEvent.click(within(form).getByRole("button", { name: "Tell party" }))
      expect(await screen.findByRole("alert")).toHaveTextContent("Set the campaign time first.")
      expect(screen.getByRole("form", { name: "Tell a party" })).toBeInTheDocument()
      expect(within(screen.getByRole("form", { name: "Tell a party" })).getByRole("combobox", { name: /Party/ })).toHaveValue("p2")
    })

    it("records that someone learned it, picking them from a search", async () => {
      setupPublished(at("who-knows"))
      fireEvent.click(await screen.findByRole("button", { name: "Record who learned this" }))
      const form = screen.getByRole("form", { name: "Record that someone learned this" })
      fireEvent.click(within(form).getByRole("button", { name: "Record knowledge" }))
      expect(await within(form).findByText("Choose who learned it.")).toBeInTheDocument()
      fireEvent.focus(within(form).getByRole("combobox", { name: /Who learned it/ }))
      fireEvent.click((await within(form).findAllByRole("option", { name: /Tom/ }))[0]!)
      fireEvent.click(within(form).getByRole("button", { name: "Record knowledge" }))
      await waitFor(() => expect(server.callsTo("POST", `${KNOWLEDGE}/k1/learn`)).toHaveLength(1))
      expect(server.callsTo("POST", `${KNOWLEDGE}/k1/learn`)[0]!.body).toMatchObject({
        knower_entity_id: "n2",
        awareness_level: "aware",
        confidence: null,
      })
    })

    it("records a telling from an existing knower", async () => {
      setupPublished(at("who-knows"))
      fireEvent.click(await screen.findByRole("button", { name: "Record a telling" }))
      const form = screen.getByRole("form", { name: "Record that someone told another" })
      fireEvent.change(within(form).getByRole("combobox", { name: /Who told/ }), { target: { value: "n1" } })
      fireEvent.focus(within(form).getByRole("combobox", { name: /Who was told/ }))
      fireEvent.click((await within(form).findAllByRole("option", { name: /Tom/ }))[0]!)
      fireEvent.click(within(form).getByRole("button", { name: "Record telling" }))
      await waitFor(() => expect(server.callsTo("POST", `${KNOWLEDGE}/k1/transfer`)).toHaveLength(1))
      expect(server.callsTo("POST", `${KNOWLEDGE}/k1/transfer`)[0]!.body).toEqual({
        source_entity_id: "n1",
        recipient_entity_id: "n2",
        transfer_method: "dialogue",
        awareness_level: "aware",
        modified_interpretation: null,
      })
    })

    it("makes it public at a searched location", async () => {
      setupPublished(at("who-knows"))
      fireEvent.click(await screen.findByRole("button", { name: "Make public" }))
      const form = screen.getByRole("form", { name: "Make this public" })
      fireEvent.focus(within(form).getByRole("combobox", { name: /Location/ }))
      fireEvent.click(await within(form).findByRole("option", { name: /Tom/ }))
      fireEvent.click(within(form).getByRole("button", { name: "Make public" }))
      await waitFor(() => expect(server.callsTo("POST", `${KNOWLEDGE}/k1/make-public`)).toHaveLength(1))
      expect(server.callsTo("POST", `${KNOWLEDGE}/k1/make-public`)[0]!.body).toEqual({
        location_id: "n2",
        awareness_level: "aware",
      })
    })

    it("expands a knower's details inline and changes a belief naming the event that last wrote it", async () => {
      setupPublished(at("who-knows"))
      fireEvent.click(await screen.findByRole("button", { name: "Details for Mira" }))
      expect(screen.getByText("He only seems pale.", { selector: "p" })).toBeInTheDocument()
      const form = screen.getByRole("form", { name: "Change belief of Mira" })
      fireEvent.change(within(form).getByRole("textbox", { name: /Confidence/ }), { target: { value: "150" } })
      fireEvent.click(within(form).getByRole("button", { name: "Save belief" }))
      expect(await within(form).findByText(/whole number from 0 to 100/)).toBeInTheDocument()
      expect(server.callsTo("POST", `${KNOWLEDGE}/knowers/ek1/belief`)).toHaveLength(0)
      fireEvent.change(within(form).getByRole("textbox", { name: /Confidence/ }), { target: { value: "90" } })
      fireEvent.click(within(form).getByRole("button", { name: "Save belief" }))
      await waitFor(() => expect(server.callsTo("POST", `${KNOWLEDGE}/knowers/ek1/belief`)).toHaveLength(1))
      expect(server.callsTo("POST", `${KNOWLEDGE}/knowers/ek1/belief`)[0]!.body).toEqual({
        expected_last_event_id: "ev1",
        awareness_level: "suspected",
        confidence: 90,
        interpretation: "He only seems pale.",
      })
    })

    it("offers no deletion or other operation the API lacks", async () => {
      setupPublished(at("who-knows"))
      await screen.findByText("Red Company")
      expect(screen.queryByRole("button", { name: /remove|delete|forget/i })).toBeNull()
    })

    it("protects a half-filled knowledge form when the person leaves (D7)", async () => {
      setupPublished(at("who-knows"))
      fireEvent.click(await screen.findByRole("button", { name: "Tell a party" }))
      fireEvent.change(
        within(screen.getByRole("form", { name: "Tell a party" })).getByRole("combobox", { name: /Party/ }),
        { target: { value: "p2" } },
      )
      fireEvent.click(breadcrumbKnowledge())
      expect(await screen.findByRole("dialog", { name: "Discard unsaved changes?" })).toHaveTextContent("a knowledge entry")
    })

    it("gives a clear reason when the server still refuses a claim as unavailable", async () => {
      setupPublished(at("who-knows"))
      server.on("POST", `${KNOWLEDGE}/k1/reveal-to-party`, { status: 404 })
      fireEvent.click(await screen.findByRole("button", { name: "Tell a party" }))
      const form = screen.getByRole("form", { name: "Tell a party" })
      fireEvent.change(within(form).getByRole("combobox", { name: /Party/ }), { target: { value: "p2" } })
      fireEvent.click(within(form).getByRole("button", { name: "Tell party" }))
      expect(await screen.findByRole("alert")).toHaveTextContent(/must be published before anyone can be recorded/)
      expect(screen.getByRole("form", { name: "Tell a party" })).toBeInTheDocument()
    })
  })

  describe("claim and knowledge saves stay independent", () => {
    it("keeps an unsaved claim edit through knowledge actions and their refresh", async () => {
      setupPublished()
      fireEvent.change(await claimBox(), { target: { value: "My unsaved edit" } })
      fireEvent.click(stageLink(3))
      fireEvent.click(await screen.findByRole("button", { name: "Tell a party" }))
      fireEvent.change(
        within(screen.getByRole("form", { name: "Tell a party" })).getByRole("combobox", { name: /Party/ }),
        { target: { value: "p2" } },
      )
      fireEvent.click(screen.getByRole("button", { name: "Tell party" }))
      await waitFor(() => expect(server.callsTo("POST", `${KNOWLEDGE}/k1/reveal-to-party`)).toHaveLength(1))
      await waitFor(() => expect(screen.queryByRole("form", { name: "Tell a party" })).toBeNull())
      expect(server.callsTo("GET", AUDIENCE).length).toBeGreaterThanOrEqual(2)
      fireEvent.click(stageLink(1))
      expect(screen.getByRole("textbox", { name: /^Claim/ })).toHaveValue("My unsaved edit")
      expect(server.callsTo("POST", UPDATE)).toHaveLength(0)
    })

    it("keeps an open knowledge form through a claim save and its refresh", async () => {
      setupPublished(at("who-knows"))
      server.on("POST", UPDATE, { body: RECEIPT })
      fireEvent.click(await screen.findByRole("button", { name: "Make public" }))
      expect(screen.getByRole("form", { name: "Make this public" })).toBeInTheDocument()
      fireEvent.click(stageLink(1))
      fireEvent.change(await claimBox(), { target: { value: "Edited" } })
      fireEvent.click(screen.getByRole("button", { name: "Save claim" }))
      fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Save changes" }))
      await screen.findByText("Claim saved")
      fireEvent.click(stageLink(3))
      expect(screen.getByRole("form", { name: "Make this public" })).toBeInTheDocument()
    })

    it("saving the claim sends no knowledge command, and discarding does not roll knowledge back", async () => {
      setupPublished()
      server.on("POST", UPDATE, { body: RECEIPT })
      fireEvent.change(await claimBox(), { target: { value: "Edited" } })
      fireEvent.click(screen.getByRole("button", { name: "Save claim" }))
      fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Save changes" }))
      await screen.findByText("Claim saved")
      expect(server.callsTo("POST", new RegExp(`${KNOWLEDGE}/`))).toHaveLength(0)
      fireEvent.change(screen.getByRole("textbox", { name: /^Claim/ }), { target: { value: "Again" } })
      const audienceReads = server.callsTo("GET", AUDIENCE).length
      fireEvent.click(screen.getByRole("button", { name: "Discard changes" }))
      expect(server.callsTo("GET", AUDIENCE)).toHaveLength(audienceReads)
      expect(screen.getByText(/Claim changes and knowledge actions save independently/)).toBeInTheDocument()
    })
  })

  describe("when knowledge cannot be recorded", () => {
    it("explains a draft once, withholds every action and names the real next step", async () => {
      withLifecycle(lifecycle())
      setup(at("who-knows"))
      const note = await screen.findByText(/Only a published claim can be recorded as known/)
      expect(note).toHaveTextContent("This claim is a draft.")
      expect(within(note).getByRole("link", { name: "Submit for review" })).toHaveAttribute("href", `${CLAIM}?section=publication`)
      for (const name of ["Tell a party", "Record who learned this", "Record a telling", "Make public"]) {
        expect(screen.queryByRole("button", { name })).toBeNull()
      }
      // What was recorded stays visible.
      expect(screen.getByText("Red Company")).toBeInTheDocument()
      expect(screen.getByText("Mira")).toBeInTheDocument()
      expect(server.callsTo("POST", /./)).toHaveLength(0)
    })

    it("names no next step when the person has none available", async () => {
      withLifecycle(lifecycle({ available_actions: [] }))
      setup(at("who-knows"))
      const note = await screen.findByText(/Only a published claim can be recorded as known/)
      expect(note).not.toHaveTextContent("Next:")
    })

    it("lifts the restriction for a published claim", async () => {
      withLifecycle(lifecycle({ canon_status: "canon", available_actions: ["supersede", "archive"] }))
      setupPublished(at("who-knows"))
      expect(await screen.findByRole("button", { name: "Tell a party" })).toBeEnabled()
      expect(screen.queryByText(/only a published claim can be recorded as known/)).toBeNull()
    })

    it("keeps an archived claim's knowledge readable and offers nothing to change it (D2, D3)", async () => {
      withLifecycle(lifecycle({ canon_status: "canon", lifecycle_status: "archived", available_actions: ["restore"] }))
      setup(at("who-knows"))
      current = {
        detail: detail(),
        view: view({
          canon_status: "canon",
          lifecycle_status: "archived",
          available_actions: [],
          blocked_actions: [{ action: "update", reason: "entity_archived" }],
        }),
      }
      server.on("GET", VIEW_PATH, () => ({ body: current.view }))
      const note = await within(await findPanel("who-knows")).findByText(/This claim is archived/)
      expect(note).toHaveTextContent("nothing new can be recorded or changed until it is restored")
      expect(within(note).getByRole("link", { name: "Open Publication" })).toHaveAttribute("href", `${CLAIM}?section=publication`)
      expect(screen.getByRole("link", { name: /Restore it to use it in play/ })).toBeInTheDocument()
      for (const name of ["Tell a party", "Record who learned this", "Record a telling", "Make public"]) {
        expect(screen.queryByRole("button", { name })).toBeNull()
      }
      fireEvent.click(await screen.findByRole("button", { name: "Details for Mira" }))
      expect(screen.getByText("He only seems pale.", { selector: "p" })).toBeInTheDocument()
      expect(screen.queryByRole("button", { name: "Save belief" })).toBeNull()
      expect(screen.queryByRole("form", { name: "Change belief of Mira" })).toBeNull()

      fireEvent.click(stageLink(2))
      fireEvent.click(screen.getByRole("link", { name: "Publication" }))
      // The only way forward is not tucked under "More".
      expect(await screen.findByRole("button", { name: "Restore" })).toBeVisible()
      expect(screen.getByText(/Archived\. It is hidden from players/)).toBeInTheDocument()
    })

    it("offers Return to draft directly for a rejected claim, with Archive under More", async () => {
      withLifecycle(lifecycle({ canon_status: "rejected", available_actions: ["return_to_draft", "archive", "delete_draft"] }))
      setup(at("publication"))
      const group = await screen.findByRole("group", { name: "Lifecycle" })
      expect(within(group).getByRole("button", { name: "Return to draft" })).toBeVisible()
      expect(within(group).getByRole("button", { name: "Archive" })).not.toBeVisible()
    })

    it("sends a restore of a non-canon archived claim back through review, not straight to play", async () => {
      withLifecycle(lifecycle({ canon_status: "draft", lifecycle_status: "archived", available_actions: ["restore"] }))
      setup()
      expect(await screen.findByRole("link", { name: /Restore it, then continue review/ })).toBeInTheDocument()
    })

    it("links a superseded claim to its replacement and keeps its roster read-only", async () => {
      withLifecycle(
        lifecycle({
          canon_status: "superseded",
          available_actions: ["archive"],
          superseded_by: { entity_id: "k2", canonical_name: "The duke was bitten." },
        }),
      )
      setup(`${CLAIM}?character_id=c1`)
      const header = (await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })).closest("header") as HTMLElement
      const banner = await within(header).findByRole("status")
      expect(banner).toHaveTextContent("Replaced by The duke was bitten.")
      expect(within(banner).getByRole("link", { name: "The duke was bitten." })).toHaveAttribute(
        "href",
        "/app/mundivita/knowledge/k2?character_id=c1",
      )
      const note = await within(await findPanel("who-knows")).findByText(/This claim was replaced by/)
      expect(note).toHaveTextContent("record new knowledge on the replacement")
      for (const name of ["Tell a party", "Record who learned this", "Make public"]) {
        expect(screen.queryByRole("button", { name })).toBeNull()
      }
      expect(screen.getByText("Mira")).toBeInTheDocument()
      expect(within(header).getByRole("link", { name: /Replaced by The duke was bitten\./ })).toBeInTheDocument()
    })
  })

  describe("campaign context", () => {
    it("opens, edits and records who knows a claim only under the campaign and claim in the address", async () => {
      setupPublished(`${CLAIM}?character_id=c1&party_id=p1`)
      server.on("POST", UPDATE, { body: RECEIPT })
      fireEvent.change(await claimBox(), { target: { value: "Edited in its own campaign" } })
      fireEvent.click(screen.getByRole("button", { name: "Save claim" }))
      fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Save changes" }))
      await screen.findByText("Claim saved")
      fireEvent.click(stageLink(3))
      fireEvent.click(await screen.findByRole("button", { name: "Tell a party" }))
      const form = screen.getByRole("form", { name: "Tell a party" })
      // "Blue Company" stands in for the campaign's own party (here The Ashen Vigil).
      fireEvent.change(within(form).getByRole("combobox", { name: /Party/ }), { target: { value: "p2" } })
      fireEvent.change(within(form).getByRole("combobox", { name: /What the party learns/ }), {
        target: { value: "rumored" },
      })
      fireEvent.click(within(form).getByRole("button", { name: "Tell party" }))
      await waitFor(() => expect(server.callsTo("POST", `${KNOWLEDGE}/k1/reveal-to-party`)).toHaveLength(1))
      expect(server.callsTo("POST", `${KNOWLEDGE}/k1/reveal-to-party`)[0]!.body).toEqual({
        party_id: "p2",
        awareness_level: "rumored",
      })

      const claimCalls = server.calls.filter((c) => /\/knowledge|\/parties/.test(c.path))
      expect(claimCalls.length).toBeGreaterThan(5)
      for (const call of claimCalls) {
        expect(call.path.startsWith("/campaigns/mundivita/")).toBe(true)
        // The only claim any request names is the one in the address.
        const ids = call.path.match(/\/knowledge\/([^/?]+)/)
        if (ids !== null && ids[1] !== "options" && ids[1] !== "subject-options" && ids[1] !== "knowers") {
          expect(ids[1]).toBe("k1")
        }
      }
    })

    it("offers only the active campaign's own parties", async () => {
      setupPublished(at("who-knows"))
      fireEvent.click(await screen.findByRole("button", { name: "Tell a party" }))
      expect(server.callsTo("GET", /\/campaigns\/mundivita\/parties/).length).toBeGreaterThan(0)
      expect(server.calls.some((c) => c.path.includes("/parties") && !c.path.startsWith("/campaigns/mundivita/"))).toBe(false)
    })

    it("keeps a missing or inaccessible claim a plain unavailable page, never another campaign's copy", async () => {
      server.on("GET", /^\/campaigns\/mundivita\/knowledge\/missing(\?.*)?$/, { status: 404 })
      openApp("/app/mundivita/knowledge/missing", ["canon.edit"])
      expect(await screen.findByRole("heading", { level: 1, name: "Knowledge unavailable" })).toBeInTheDocument()
      expect(screen.queryByRole("textbox")).toBeNull()
      expect(server.calls.some((c) => c.path.includes("/authoring/knowledge/missing"))).toBe(false)
    })
  })

  describe("old addresses", () => {
    it.each([
      ["edit", "claim"],
      ["audience", "who-knows"],
    ])("redirects /%s to the matching section, keeping character and party context", async (old, section) => {
      withLifecycle(lifecycle())
      const { router } = setup(`${CLAIM}/${old}?character_id=c1&party_id=p1`)
      await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })
      expect(router.state.location.pathname).toBe(CLAIM)
      expect(router.state.location.search).toBe(`?character_id=c1&party_id=p1&section=${section}`)
      expect(router.state.location.hash).toBe("")
      expect(server.calls.some((c) => c.path.includes("character_id=c1") && c.path.includes("party_id=p1"))).toBe(true)
      expect(
        await screen.findByRole("heading", { level: 2, name: section === "claim" ? "Claim" : "Who knows this" }),
      ).toBeInTheDocument()
    })

    it("links cards to the unified page carrying the perspective", async () => {
      server.on("GET", /^\/campaigns\/mundivita\/knowledge(\?.*)?$/, {
        body: {
          items: [
            {
              knowledge_item_id: "k1",
              knowledge_type_code: "secret",
              statement: "The duke is a vampire.",
              truth_status_code: null,
              sensitivity: null,
              awareness_level: null,
              confidence: null,
              willing_to_share: null,
              scope: "party",
              discovery_world_time_id: null,
              source_event_id: null,
              source_interaction_id: null,
              subject_entity_id: "l1",
              subject: SUBJECT,
            },
          ],
          next_cursor: null,
        },
      })
      openApp("/app/mundivita/knowledge", ["campaign.view"])
      const link = await screen.findByRole("link", { name: "The duke is a vampire." })
      expect(link.getAttribute("href")).toMatch(/^\/app\/mundivita\/knowledge\/k1(\?|$)/)
      const card = link.closest("li") as HTMLElement
      expect(within(card).getByText("About")).toBeInTheDocument()
      expect(within(card).getByRole("link", { name: "Keep" })).toBeInTheDocument()
      expect(link).not.toContainElement(within(card).getByRole("link", { name: "Keep" }))
    })
  })
})
