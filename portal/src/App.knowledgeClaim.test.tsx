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
    expect(screen.getByRole("link", { name: "Keep" })).toHaveAttribute("href", "/app/mundivita/world/location/l1")
  })

  it("renders editable controls straight away, with no view or edit toggle", async () => {
    setup()
    expect(await claimBox()).toHaveValue("The duke is a vampire.")
    expect(screen.getByRole("combobox", { name: /Kind/ })).toHaveValue("secret")
    expect(screen.getByRole("combobox", { name: /Truth/ })).toHaveValue("true")
    expect(screen.getByRole("combobox", { name: /Sensitivity/ })).toHaveValue("secret")
    expect(screen.getByRole("combobox", { name: "Subject" })).toHaveValue("Keep")
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
      expect(screen.getByText(/The subject cannot change/)).toBeInTheDocument()
      expect(screen.getByRole("link", { name: "Keep" })).toBeInTheDocument()
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
      setup()
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
      setup()
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
      setup()
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
      setup()
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
      setup()
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
      setup()
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
      setup()
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
      setup()
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
      setup()
      await screen.findByText("Red Company")
      expect(screen.queryByRole("button", { name: /remove|delete|forget/i })).toBeNull()
    })
  })

  describe("claim and knowledge saves stay independent", () => {
    it("keeps an unsaved claim edit through knowledge actions and their refresh", async () => {
      setup()
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
      setup()
      server.on("POST", UPDATE, { body: RECEIPT })
      fireEvent.change(await claimBox(), { target: { value: "Edited" } })
      fireEvent.click(screen.getByRole("button", { name: "Save claim" }))
      await screen.findByText("Claim saved")
      expect(server.callsTo("POST", new RegExp(`${KNOWLEDGE}/`))).toHaveLength(0)
      fireEvent.change(screen.getByRole("textbox", { name: /^Claim/ }), { target: { value: "Again" } })
      const audienceReads = server.callsTo("GET", AUDIENCE).length
      fireEvent.click(screen.getByRole("button", { name: "Discard changes" }))
      expect(server.callsTo("GET", AUDIENCE)).toHaveLength(audienceReads)
      expect(screen.getByText(/Claim changes and knowledge actions save independently/)).toBeInTheDocument()
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
