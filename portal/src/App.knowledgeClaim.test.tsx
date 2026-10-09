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

const RECEIPT = { knowledge_item_id: "k1", record_id: "r1", changed: true, event_id: "e1" }
const STALE = { status: 409, body: { error: { code: "stale_write", message: "m", correlation_id: "c" } } }

let server: MockServer
let current: { detail: object; view: object }

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
  server.on("GET", /audience-preview|audience_preview/, { status: 404 })
  server.on("POST", /\/campaigns\/mundivita\/knowledge\//, { body: RECEIPT })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const claimBox = () => screen.findByRole("textbox", { name: /^Claim/ })

describe("unified knowledge claim page", () => {
  it("orders the claim, canonical information, character knowledge and who knows this", async () => {
    setup()
    await screen.findByRole("heading", { level: 2, name: "Who knows this" })
    expect(screen.getByRole("heading", { level: 1, name: "Knowledge claim" })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    const names = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)
    expect(names.slice(0, 3)).toEqual([
      "GM and canonical information",
      "Character knowledge",
      "Who knows this",
    ])
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" })
    expect(within(crumbs).getByRole("link", { name: "Knowledge" })).toHaveAttribute("href", "/app/mundivita/knowledge")
    expect(within(crumbs).getByText("Claim")).toHaveAttribute("aria-current", "page")
    // The subject block sits between the claim and the canonical information.
    const about = screen.getByText("About this World entry")
    const canonical = screen.getByRole("heading", { name: "GM and canonical information" })
    expect(about.compareDocumentPosition(canonical) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByRole("link", { name: "Open World entry" })).toHaveAttribute(
      "href",
      "/app/mundivita/world/location/l1",
    )
  })

  it("renders editable controls straight away, with no view or edit toggle", async () => {
    setup()
    expect(await claimBox()).toHaveValue("The duke is a vampire.")
    expect(screen.getByRole("combobox", { name: /Kind/ })).toHaveValue("secret")
    expect(screen.getByRole("combobox", { name: /Truth/ })).toHaveValue("true")
    expect(screen.getByRole("combobox", { name: /Sensitivity/ })).toHaveValue("secret")
    // The subject is one readable field with separate actions, not a name repeated in an input.
    const about = screen.getByText("About this World entry").parentElement as HTMLElement
    expect(within(about).getByText("Keep")).toBeInTheDocument()
    expect(within(about).getByRole("link", { name: "Open World entry" })).toBeInTheDocument()
    expect(within(about).getByRole("button", { name: "Change subject" })).toBeInTheDocument()
    expect(within(about).getByRole("button", { name: "Clear subject" })).toBeInTheDocument()
    expect(within(about).queryByRole("combobox")).toBeNull()
    expect(screen.queryByRole("button", { name: /^Edit/ })).toBeNull()
    expect(screen.queryByRole("link", { name: /Edit knowledge claim|Who knows this/ })).toBeNull()
  })

  it("shows readable values, with no editing actions and no authoring or audience requests, to a reader", async () => {
    setup(CLAIM, ["campaign.view"])
    expect(await screen.findByText("The duke is a vampire.")).toBeInTheDocument()
    expect(screen.queryByRole("textbox")).toBeNull()
    expect(screen.queryByRole("combobox", { name: /Kind|Truth|Sensitivity|Subject/ })).toBeNull()
    expect(screen.queryByRole("button", { name: /Save claim|Discard changes/ })).toBeNull()
    expect(screen.getByRole("heading", { name: "GM and canonical information" })).toBeInTheDocument()
    expect(screen.getByText("Truth")).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "Who knows this" })).toBeNull()
    expect(server.calls.some((c) => c.path.includes("/authoring/") || c.path.endsWith("/audience"))).toBe(false)
  })

  it("keeps restricted canonical fields absent when the server withheld them", async () => {
    current = { detail: detail({ truth_status_code: null, sensitivity: null }), view: view() }
    server.on("GET", DETAIL, () => ({ body: current.detail }))
    openApp(CLAIM, ["campaign.view"])
    await screen.findByText("The duke is a vampire.")
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
    await screen.findByText("The duke is a vampire.")
    expect(screen.queryByText("About this World entry")).toBeNull()
  })

  it("lets an editor set a subject on an unlinked claim, inside the same About block", async () => {
    current = { detail: detail({ subject: null }), view: view({ subject: null }) }
    server.on("GET", DETAIL, () => ({ body: current.detail }))
    server.on("GET", VIEW_PATH, () => ({ body: current.view }))
    openApp(CLAIM, ["canon.edit"])
    await claimBox()
    const about = screen.getByText("About this World entry").parentElement as HTMLElement
    expect(within(about).getByRole("combobox", { name: "Subject" })).toBeInTheDocument()
    expect(within(about).queryByRole("link")).toBeNull()
  })

  describe("character knowledge", () => {
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

  describe("subject lock and restrictions", () => {
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
      expect(screen.getByRole("link", { name: "Open World entry" })).toBeInTheDocument()
      expect(screen.getByRole("combobox", { name: /Truth/ })).toBeEnabled()
    })

    it("shows text and the server's reason when editing is blocked, while who-knows stays manageable", async () => {
      setup()
      current = {
        detail: detail(),
        view: view({ available_actions: [], blocked_actions: [{ action: "update", reason: "archived" }] }),
      }
      server.on("GET", VIEW_PATH, () => ({ body: current.view }))
      expect(await screen.findByText(/Editing unavailable/)).toBeInTheDocument()
      expect(screen.queryByRole("textbox", { name: /^Claim/ })).toBeNull()
      expect(screen.queryByRole("button", { name: "Save claim" })).toBeNull()
      expect(screen.getByRole("button", { name: "Make public" })).toBeInTheDocument()
    })

    it("keeps the claim editable when nobody may see who knows it", async () => {
      setup()
      server.on("GET", AUDIENCE, { status: 403 })
      expect(await claimBox()).toBeEnabled()
      await waitFor(() => expect(server.callsTo("GET", AUDIENCE).length).toBeGreaterThan(0))
      expect(screen.queryByRole("heading", { name: "Who knows this" })).toBeNull()
      expect(screen.queryByText(/Red Company/)).toBeNull()
    })
  })

  describe("who knows this", () => {
    it("lists parties, individuals and public places as separate compact groups", async () => {
      setupPublished()
      await screen.findByText("Red Company")
      expect(screen.getByRole("heading", { level: 3, name: "Parties" })).toBeInTheDocument()
      expect(screen.getByRole("heading", { level: 3, name: "Characters, NPCs and organizations" })).toBeInTheDocument()
      expect(screen.getByRole("heading", { level: 3, name: "Public places" })).toBeInTheDocument()
      const mira = screen.getByRole("listitem", { name: "Mira" })
      expect(within(mira).getByText("Npc")).toBeInTheDocument()
      expect(within(mira).getByText("Suspects, 60% sure")).toBeInTheDocument()
      expect(screen.getByText("Stonebridge")).toBeInTheDocument()
      // Details stay collapsed until asked for.
      expect(screen.queryByText("He only seems pale.")).toBeNull()
      expect(screen.queryByRole("form", { name: /Tell a party|Make this public|learned this|told another|belief/ })).toBeNull()
    })

    it("puts each group's actions beside its heading and reveals forms locally", async () => {
      setupPublished()
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
      setupPublished()
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

    it("keeps the form and what was typed when a knowledge action is refused", async () => {
      setupPublished()
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
      setupPublished()
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
      setupPublished()
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
      setupPublished()
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
      setupPublished()
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
      setupPublished()
      await screen.findByText("Red Company")
      expect(screen.queryByRole("button", { name: /remove|delete|forget/i })).toBeNull()
    })
  })

  describe("claim and knowledge saves stay independent", () => {
    it("keeps an unsaved claim edit through knowledge actions and their refresh", async () => {
      setupPublished()
      fireEvent.change(await claimBox(), { target: { value: "My unsaved edit" } })
      fireEvent.click(screen.getByRole("button", { name: "Tell a party" }))
      fireEvent.change(
        within(screen.getByRole("form", { name: "Tell a party" })).getByRole("combobox", { name: /Party/ }),
        { target: { value: "p2" } },
      )
      fireEvent.click(screen.getByRole("button", { name: "Tell party" }))
      await waitFor(() => expect(server.callsTo("POST", `${KNOWLEDGE}/k1/reveal-to-party`)).toHaveLength(1))
      await waitFor(() => expect(screen.queryByRole("form", { name: "Tell a party" })).toBeNull())
      expect(server.callsTo("GET", AUDIENCE).length).toBeGreaterThanOrEqual(2)
      expect(screen.getByRole("textbox", { name: /^Claim/ })).toHaveValue("My unsaved edit")
      expect(server.callsTo("POST", UPDATE)).toHaveLength(0)
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

  describe("an unpublished claim", () => {
    it("explains that nobody can be recorded as knowing a draft, and withholds the actions", async () => {
      setup()
      expect(
        await screen.findByText(/This claim is a draft, and only a published claim can be recorded as known/),
      ).toBeInTheDocument()
      // The lifecycle read is unavailable here, so no action is pointed at.
      expect(screen.getByText(/No lifecycle action is available to you right now/)).toBeInTheDocument()
      for (const name of ["Tell a party", "Record who learned this", "Make public"]) {
        expect(screen.getByRole("button", { name })).toBeDisabled()
      }
      expect(server.callsTo("POST", /./)).toHaveLength(0)
    })

    it("offers the lifecycle controls that publish it, and enables the roster once it is published", async () => {
      server.on("GET", /\/entities\/k1\/lifecycle$/, {
        body: {
          entity_id: "k1",
          entity_type_code: "knowledge_item",
          canonical_name: "x",
          canon_status: "draft",
          lifecycle_status: "active",
          row_version: 2,
          lifecycle_managed: true,
          superseded_by: null,
          available_actions: ["submit_for_review"],
          blocked_actions: [],
        },
      })
      setup()
      expect(await screen.findByRole("button", { name: "Submit for review" })).toBeInTheDocument()
    })

    it("enables the actions for a published claim", async () => {
      setupPublished()
      expect(await screen.findByRole("button", { name: "Tell a party" })).toBeEnabled()
      expect(screen.queryByText(/only a published claim can be recorded as known/)).toBeNull()
    })

    it("gives a clear reason when the server still refuses a claim as unavailable", async () => {
      setupPublished()
      server.on("POST", `${KNOWLEDGE}/k1/reveal-to-party`, { status: 404 })
      fireEvent.click(await screen.findByRole("button", { name: "Tell a party" }))
      const form = screen.getByRole("form", { name: "Tell a party" })
      fireEvent.change(within(form).getByRole("combobox", { name: /Party/ }), { target: { value: "p2" } })
      fireEvent.click(within(form).getByRole("button", { name: "Tell party" }))
      expect(await screen.findByRole("alert")).toHaveTextContent(/must be published before anyone can be recorded/)
      expect(screen.getByRole("form", { name: "Tell a party" })).toBeInTheDocument()
    })
  })

  describe("lifecycle, sources and the subject field", () => {
    const LIFECYCLE = "/campaigns/mundivita/entities/k1/lifecycle"
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
    const withLifecycle = (body: object) => {
      server.on("GET", LIFECYCLE, () => ({ body }))
    }

    it("shows the status once, the next step, and the rest under More, with no list of unavailable actions", async () => {
      withLifecycle(lifecycle())
      setup()
      const group = await screen.findByRole("group", { name: "Lifecycle" })
      expect(within(group).getAllByText("Draft")).toHaveLength(1)
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
      ["draft", ["submit_for_review", "reject", "archive"], "Submit for review", "submit it for review, then approve and publish it"],
      ["proposed", ["approve", "return_to_draft", "reject"], "Approve", "approve it, then publish it"],
      ["approved", ["publish", "return_to_draft"], "Publish as canon", "publish it"],
    ])("offers the real next step for a %s claim, and names it in the roster note", async (status, actions, label, step) => {
      withLifecycle(lifecycle({ canon_status: status, available_actions: actions }))
      setup()
      const group = await screen.findByRole("group", { name: "Lifecycle" })
      expect(within(group).getByRole("button", { name: label })).toBeInTheDocument()
      expect(await screen.findByText(new RegExp(`Next: ${step}`))).toBeInTheDocument()
      // Never points at an action the person cannot take.
      if (status !== "approved") expect(screen.queryByRole("button", { name: "Publish as canon" })).toBeNull()
    })

    it("says no action is available rather than naming one that is not there", async () => {
      withLifecycle(lifecycle({ available_actions: [] }))
      setup()
      expect(await screen.findByText(/No lifecycle action is available to you right now/)).toBeInTheDocument()
      expect(screen.queryByText(/Next:/)).toBeNull()
    })

    it("lifts the restriction for a published claim", async () => {
      withLifecycle(lifecycle({ canon_status: "canon", available_actions: ["supersede", "archive"] }))
      setupPublished()
      const group = await screen.findByRole("group", { name: "Lifecycle" })
      expect(within(group).getByText("Canon")).toBeInTheDocument()
      await waitFor(() => expect(screen.getByRole("button", { name: "Tell a party" })).toBeEnabled())
      expect(screen.queryByText(/only a published claim can be recorded as known/)).toBeNull()
    })

    it("asks first when a lifecycle action meets unsaved claim edits, and keeps the edits", async () => {
      withLifecycle(lifecycle())
      server.on("POST", `${LIFECYCLE}/submit-for-review`, () => {
        current = { detail: current.detail, view: view({ canon_status: "proposed", row_version: 2 }) }
        return { body: { entity_id: "k1", canon_status: "proposed", row_version: 3, changed: true } }
      })
      setup()
      fireEvent.change(await claimBox(), { target: { value: "Not saved yet" } })
      fireEvent.click(await screen.findByRole("button", { name: "Submit for review" }))
      const dialog = await screen.findByRole("dialog", { name: "Submit for review?" })
      expect(dialog).toHaveTextContent(/unsaved edits are not part of this change/)
      expect(server.callsTo("POST", /./)).toHaveLength(0)
      fireEvent.click(within(dialog).getByRole("button", { name: "Submit for review" }))
      await waitFor(() => expect(server.callsTo("POST", `${LIFECYCLE}/submit-for-review`)).toHaveLength(1))
      expect(server.callsTo("POST", UPDATE)).toHaveLength(0)
      expect(screen.getByRole("textbox", { name: /^Claim/ })).toHaveValue("Not saved yet")
    })

    it("submits for review at once when there are no unsaved edits", async () => {
      withLifecycle(lifecycle())
      server.on("POST", `${LIFECYCLE}/submit-for-review`, {
        body: { entity_id: "k1", canon_status: "proposed", row_version: 3, changed: true },
      })
      setup()
      fireEvent.click(await screen.findByRole("button", { name: "Submit for review" }))
      await waitFor(() => expect(server.callsTo("POST", `${LIFECYCLE}/submit-for-review`)).toHaveLength(1))
      expect(screen.queryByRole("dialog")).toBeNull()
    })

    it("keeps a destructive lifecycle action behind its confirmation", async () => {
      withLifecycle(lifecycle())
      setup()
      const group = await screen.findByRole("group", { name: "Lifecycle" })
      fireEvent.click(within(group).getByText("More"))
      fireEvent.click(within(group).getByRole("button", { name: "Delete draft" }))
      const dialog = await screen.findByRole("dialog", { name: "Delete this draft?" })
      expect(server.callsTo("POST", /./)).toHaveLength(0)
      fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
      expect(server.callsTo("POST", /./)).toHaveLength(0)
    })

    it("keeps Who knows this directly after the claim sections, and sources after it", async () => {
      withLifecycle(lifecycle())
      server.on("GET", /\/entities\/k1\/provenance$/, { body: PROVENANCE })
      server.on("GET", "/campaigns/mundivita/sources", { body: SOURCES })
      setup()
      const roster = await screen.findByRole("heading", { level: 2, name: "Who knows this" })
      const sources = await screen.findByRole("heading", { level: 2, name: "Sources" })
      const character = screen.getByRole("heading", { name: "Character knowledge" })
      expect(character.compareDocumentPosition(roster) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
      expect(roster.compareDocumentPosition(sources) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
      const between = screen
        .getAllByRole("heading", { level: 2 })
        .map((h) => h.textContent)
        .filter((name) => name === "Lifecycle")
      expect(between).toHaveLength(0)
    })

    it("keeps sources compact until Add source is opened, and keeps what was typed when it is closed", async () => {
      withLifecycle(lifecycle())
      server.on("GET", /\/entities\/k1\/provenance$/, { body: PROVENANCE })
      server.on("GET", "/campaigns/mundivita/sources", { body: SOURCES })
      server.on("POST", /\/campaigns\/mundivita\/sources/, { status: 500 })
      setup()
      expect(await screen.findByText("GM entry", { selector: "strong" })).toBeInTheDocument()
      expect(screen.getByRole("link", { name: "View provenance" })).toBeInTheDocument()
      expect(screen.queryByRole("form", { name: "Write a new source" })).toBeNull()
      const add = screen.getByRole("button", { name: "Add source" })
      expect(add).toHaveAttribute("aria-expanded", "false")
      fireEvent.click(add)
      const form = screen.getByRole("form", { name: "Write a new source" })
      fireEvent.change(within(form).getByRole("combobox"), { target: { value: "note" } })
      fireEvent.change(within(form).getByRole("textbox", { name: "Title" }), { target: { value: "Ledger page" } })
      fireEvent.click(within(form).getByRole("button", { name: "Write and attach source" }))
      expect(await screen.findAllByRole("alert")).not.toHaveLength(0)
      // Closing and reopening keeps the draft and the error.
      fireEvent.click(screen.getByRole("button", { name: "Hide add source" }))
      expect(screen.queryByRole("form", { name: "Write a new source" })).toBeNull()
      fireEvent.click(screen.getByRole("button", { name: "Add source" }))
      expect(
        within(screen.getByRole("form", { name: "Write a new source" })).getByRole("textbox", { name: "Title" }),
      ).toHaveValue("Ledger page")
    })

    it("shows the subject once, with Open, Change and Clear as separate actions", async () => {
      withLifecycle(lifecycle())
      setup()
      await claimBox()
      const aboutBlock = () => screen.getByText("About this World entry").parentElement as HTMLElement
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
      withLifecycle(lifecycle())
      server.on("POST", UPDATE, { body: RECEIPT })
      setup()
      await claimBox()
      const aboutBlock = () => screen.getByText("About this World entry").parentElement as HTMLElement
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

    it("shows a reader nothing of lifecycle, sources or the roster", async () => {
      setup(CLAIM, ["campaign.view"])
      await screen.findByText("The duke is a vampire.")
      expect(screen.queryByRole("group", { name: "Lifecycle" })).toBeNull()
      expect(screen.queryByRole("button", { name: "Add source" })).toBeNull()
      expect(screen.queryByRole("heading", { name: "Sources" })).toBeNull()
      expect(server.calls.some((c) => /lifecycle|provenance|\/sources/.test(c.path))).toBe(false)
      expect(screen.getByRole("link", { name: "Keep" })).toBeInTheDocument()
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
      setupPublished()
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
      ["edit", "#claim"],
      ["audience", "#who-knows"],
    ])("redirects /%s to the unified page, keeping character and party context", async (old, hash) => {
      const { router } = setup(`${CLAIM}/${old}?character_id=c1&party_id=p1`)
      await screen.findByRole("heading", { level: 1, name: "Knowledge claim" })
      expect(router.state.location.pathname).toBe(CLAIM)
      expect(router.state.location.search).toBe("?character_id=c1&party_id=p1")
      expect(router.state.location.hash).toBe(hash)
      expect(router.state.historyAction).toBe("REPLACE")
      expect(server.calls.some((c) => c.path.includes("character_id=c1") && c.path.includes("party_id=p1"))).toBe(true)
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
