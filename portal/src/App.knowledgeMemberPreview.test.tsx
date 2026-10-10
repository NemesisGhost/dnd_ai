import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const BASE = "/app/mundivita/knowledge"
const PREVIEW = `${BASE}/member-preview`
const SERVER = "/campaigns/mundivita"
const OVERVIEW = `${SERVER}/access-overview`
const preview = (member: string) => `${SERVER}/members/${member}/preview/knowledge`

const member = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  campaign_membership_id: id,
  user_id: `u-${id}`,
  display_name: name,
  status_code: "active",
  status_display_name: "Active",
  joined_at: "2026-01-01T00:00:00Z",
  account_is_active: true,
  roles: [],
  character_relationships: [],
  grants: [],
  ...extra,
})

const OVERVIEW_BODY = {
  members: [
    member("m1", "Mira"),
    member("m2", "Tom"),
    member("m3", "Gone", { status_code: "departed" }),
    member("m4", "Disabled", { account_is_active: false }),
  ],
  assignable_roles: [],
  assignable_characters: [],
  assignable_relationship_types: [],
  grantable_resource_capabilities: [],
  access_groups: [],
}

const PERSPECTIVES: Record<string, object> = {
  m1: {
    display_name: "Mira",
    roles: ["player"],
    character_perspectives: [
      {
        character_id: "c1",
        character_name: "Ixa",
        authorized_parties: [{ party_id: "p1", party_name: "Red Company" }],
      },
      { character_id: "c2", character_name: "Bo", authorized_parties: [] },
    ],
  },
  m2: { display_name: "Tom", roles: ["observer"], character_perspectives: [] },
}

const item = (id: string, statement: string, extra: Record<string, unknown> = {}) => ({
  knowledge_item_id: id,
  knowledge_type_code: "rumor",
  statement,
  truth_status_code: null,
  sensitivity: null,
  awareness_level: null,
  confidence: null,
  willing_to_share: null,
  scope: "public",
  discovery_world_time_id: null,
  source_event_id: null,
  source_interaction_id: null,
  subject_entity_id: null,
  subject: null,
  ...extra,
})

const SUBJECT = { entity_id: "l1", name: "Keep", category: "location", entity_type_code: "fortress" }

let server: MockServer
let lists: Record<string, { items: object[]; next_cursor: string | null }>

const listPath = (m: string) => new RegExp(`^${preview(m)}\\?`)

function setup(path: string, capabilities: string[] = ["access.manage", "canon.edit"]) {
  return openApp(path, capabilities)
}

beforeEach(() => {
  lists = {
    m1: { items: [item("k1", "Mira can see this.", { subject: SUBJECT })], next_cursor: null },
    m2: { items: [item("k9", "Tom can see this.")], next_cursor: null },
  }
  server = installCampaignShellMocks()
  server.on("GET", OVERVIEW, { body: OVERVIEW_BODY })
  for (const id of ["m1", "m2"]) {
    server.on("GET", `${preview(id)}/perspectives`, { body: PERSPECTIVES[id] })
    server.on("GET", listPath(id), () => ({ body: lists[id] }))
  }
  server.on("GET", /\/members\/m1\/preview\/knowledge\/k1(\?.*)?$/, {
    body: {
      knowledge_item_id: "k1",
      knowledge_type_code: "rumor",
      statement: "Mira can see this.",
      truth_status_code: null,
      sensitivity: null,
      awareness_level: "aware",
      confidence: 70,
      willing_to_share: true,
      subject: SUBJECT,
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const requestsTo = (pattern: RegExp) => server.calls.filter((c) => pattern.test(c.path))
const previewReads = () => requestsTo(/\/preview\/knowledge/)
const normalKnowledgeReads = () =>
  server.calls.filter(
    (c) => c.method === "GET" && /^\/campaigns\/mundivita\/knowledge(\/|\?|$)/.test(c.path),
  )
const chooseMember = async (name: string) => {
  fireEvent.change(await screen.findByRole("combobox", { name: "Member" }), {
    target: { value: name },
  })
}

describe("Knowledge Member preview", () => {
  describe("access", () => {
    it("tells someone who cannot manage access they may not preview, and sends no preview request", async () => {
      const { router } = setup(PREVIEW, ["campaign.view", "canon.edit"])
      expect(await screen.findByText(/do not have permission to preview/)).toBeInTheDocument()
      expect(screen.queryByRole("combobox", { name: "Member" })).toBeNull()
      expect(previewReads()).toHaveLength(0)
      expect(requestsTo(/access-overview/)).toHaveLength(0)
      expect(router.state.location.pathname).toBe(PREVIEW)
    })

    it("denies a claim preview address the same way", async () => {
      setup(`${PREVIEW}/k1?member=m1`, ["campaign.view"])
      expect(await screen.findByText(/do not have permission to preview/)).toBeInTheDocument()
      expect(previewReads()).toHaveLength(0)
    })
  })

  describe("selection", () => {
    it("shows a choose-a-member state, with no Knowledge, before a member is picked", async () => {
      setup(PREVIEW)
      expect(await screen.findByRole("heading", { level: 2, name: "Choose a member to preview" })).toBeInTheDocument()
      expect(screen.getByText(/read-only/)).toBeInTheDocument()
      expect(screen.queryByRole("region", { name: "Preview context" })).toBeNull()
      expect(screen.queryByRole("region", { name: "Preview knowledge results" })).toBeNull()
      expect(previewReads()).toHaveLength(0)
      expect(normalKnowledgeReads()).toHaveLength(0)
    })

    it("offers only members who are open and active", async () => {
      setup(PREVIEW)
      const select = await screen.findByRole("combobox", { name: "Member" })
      const names = within(select).getAllByRole("option").map((o) => o.textContent)
      expect(names).toEqual(["Choose a member", "Mira", "Tom"])
    })

    it("previews the chosen member through the server's preview routes only, and says so in a persistent banner", async () => {
      const { router } = setup(PREVIEW)
      await chooseMember("m1")
      const banner = await screen.findByRole("region", { name: "Preview context" })
      expect(banner).toHaveTextContent("Previewing as Mira (player)")
      expect(banner).toHaveTextContent("Read-only")
      expect(banner).toHaveTextContent("Member access decides which claims Mira may open")
      expect(banner).toHaveTextContent("No character perspective")
      expect(within(banner).getByRole("link", { name: "Return to Knowledge" })).toHaveAttribute("href", BASE)
      expect(router.state.location.search).toBe("?member=m1")
      expect(await screen.findByText("Mira can see this.")).toBeInTheDocument()
      expect(requestsTo(listPath("m1"))).toHaveLength(1)
      // Nothing came from the ordinary, unrestricted Knowledge routes.
      expect(normalKnowledgeReads()).toHaveLength(0)
      expect(server.calls.filter((c) => c.method !== "GET")).toHaveLength(0)
    })

    it("opens claims inside the preview with the whole context, and shows no subject link", async () => {
      setup(`${PREVIEW}?member=m1&view=rumors&q=mira`)
      const link = await screen.findByRole("link", { name: "Mira can see this." })
      expect(link).toHaveAttribute("href", `${PREVIEW}/k1?member=m1&view=rumors&q=mira`)
      expect(screen.queryByRole("link", { name: "Keep" })).toBeNull()
    })
  })

  describe("perspective", () => {
    it("offers only the member's own characters and their parties, and asks the server for that perspective", async () => {
      setup(`${PREVIEW}?member=m1`)
      const character = await screen.findByRole("combobox", { name: "Character to preview" })
      expect(within(character).getAllByRole("option").map((o) => o.textContent)).toEqual([
        "No character perspective",
        "Ixa",
        "Bo",
      ])
      const party = screen.getByRole("combobox", { name: "Party to preview" })
      expect(party).toBeDisabled()
      fireEvent.change(character, { target: { value: "c1" } })
      await waitFor(() => expect(requestsTo(/character_id=c1/).length).toBeGreaterThan(0))
      expect(screen.getByRole("combobox", { name: "Party to preview" })).toBeEnabled()
      expect(
        within(screen.getByRole("combobox", { name: "Party to preview" })).getAllByRole("option").map((o) => o.textContent),
      ).toEqual(["No party perspective", "Red Company"])
      fireEvent.change(screen.getByRole("combobox", { name: "Party to preview" }), { target: { value: "p1" } })
      await waitFor(() => expect(requestsTo(/party_id=p1/).length).toBeGreaterThan(0))
      const banner = screen.getByRole("region", { name: "Preview context" })
      expect(banner).toHaveTextContent("Character perspective: Ixa. Party perspective: Red Company.")
      expect(banner).toHaveTextContent("fictional perspectives")
    })

    it("says no party is available for a character without one", async () => {
      setup(`${PREVIEW}?member=m1&character_id=c2`)
      const party = await screen.findByRole("combobox", { name: "Party to preview" })
      expect(party).toBeDisabled()
      expect(within(party).getByRole("option")).toHaveTextContent("No party available")
    })

    it("resets the character, party and page when the member changes, and never shows the old member's results under the new banner", async () => {
      setup(`${PREVIEW}?member=m1&character_id=c1&party_id=p1&cursor=abc`)
      await screen.findByText("Mira can see this.")
      let release: () => void = () => undefined
      server.on("GET", listPath("m2"), async () => {
        await new Promise<void>((resolve) => {
          release = resolve
        })
        return { body: lists.m2 }
      })
      await chooseMember("m2")
      const banner = await screen.findByRole("region", { name: "Preview context" })
      expect(banner).toHaveTextContent("Previewing as Tom")
      // The previous member's claim is gone while Tom's list is still loading.
      expect(screen.queryByText("Mira can see this.")).toBeNull()
      expect(screen.getByText(/Loading what Tom can see/)).toBeInTheDocument()
      release()
      expect(await screen.findByText("Tom can see this.")).toBeInTheDocument()
      const last = requestsTo(listPath("m2")).at(-1)!
      expect(last.path).not.toMatch(/character_id|party_id|cursor/)
    })
  })

  describe("invalid selections never fall back to unrestricted data", () => {
    it("refuses a member who is not an active campaign member", async () => {
      for (const id of ["m3", "m4", "nobody"]) {
        const { unmount } = setup(`${PREVIEW}?member=${id}`)
        expect(await screen.findByRole("alert")).toHaveTextContent(/cannot be previewed/)
        expect(previewReads()).toHaveLength(0)
        expect(normalKnowledgeReads()).toHaveLength(0)
        unmount()
      }
    })

    it("refuses a character the member does not have, and a party the character cannot use", async () => {
      const first = setup(`${PREVIEW}?member=m2&character_id=c1`)
      expect(await screen.findByRole("alert")).toHaveTextContent(/not one of Tom's perspectives/)
      expect(requestsTo(listPath("m2"))).toHaveLength(0)
      first.unmount()
      setup(`${PREVIEW}?member=m1&character_id=c1&party_id=p-other`)
      expect(await screen.findByRole("alert")).toHaveTextContent(/party is not available to Mira as Ixa/)
      expect(requestsTo(listPath("m1"))).toHaveLength(0)
    })

    it("refuses a party named without a character", async () => {
      setup(`${PREVIEW}?member=m1&party_id=p1`)
      expect(await screen.findByRole("alert")).toHaveTextContent(/party is not available to Mira without a character/)
      expect(requestsTo(listPath("m1"))).toHaveLength(0)
    })

    it("explains a member the server will not preview", async () => {
      server.on("GET", `${preview("m1")}/perspectives`, { status: 404 })
      setup(`${PREVIEW}?member=m1`)
      expect(await screen.findByRole("alert")).toHaveTextContent(/Mira cannot be previewed/)
      expect(requestsTo(listPath("m1"))).toHaveLength(0)
    })

    it("explains a member who cannot open Knowledge at all, and offers a retry for a failure", async () => {
      server.on("GET", listPath("m1"), { status: 404 })
      setup(`${PREVIEW}?member=m1`)
      expect(await screen.findByRole("alert")).toHaveTextContent(/Mira cannot open Knowledge/)
    })

    it("keeps an error retryable", async () => {
      server.on("GET", listPath("m1"), { status: 500 })
      setup(`${PREVIEW}?member=m1`)
      expect(await screen.findByText("The preview could not be loaded.")).toBeInTheDocument()
      server.on("GET", listPath("m1"), () => ({ body: lists.m1 }))
      fireEvent.click(screen.getByRole("button", { name: "Try again" }))
      expect(await screen.findByText("Mira can see this.")).toBeInTheDocument()
    })
  })

  describe("filters and paging stay in the address", () => {
    it("sends the view, search and public choice to the preview and keeps them for claims", async () => {
      const { router } = setup(`${PREVIEW}?member=m1`)
      fireEvent.change(await screen.findByRole("combobox", { name: "View" }), { target: { value: "rumors" } })
      await waitFor(() => expect(router.state.location.search).toBe("?member=m1&view=rumors"))
      fireEvent.click(screen.getByRole("checkbox", { name: "Include public knowledge" }))
      await waitFor(() => expect(router.state.location.search).toBe("?member=m1&view=rumors&public=0"))
      fireEvent.change(screen.getByRole("searchbox"), { target: { value: "moon" } })
      await waitFor(() => expect(router.state.location.search).toBe("?member=m1&view=rumors&q=moon&public=0"))
      await waitFor(() =>
        expect(requestsTo(listPath("m1")).at(-1)!.path).toContain("view=rumors&q=moon&include_public=false"),
      )
      expect(await screen.findByRole("link", { name: "Mira can see this." })).toHaveAttribute(
        "href",
        `${PREVIEW}/k1?member=m1&view=rumors&q=moon&public=0`,
      )
    })

    it("pages with the cursor in the address, so Back returns to the previous page", async () => {
      lists.m1 = { items: [item("k1", "Page one.")], next_cursor: "c-2" }
      const { router } = setup(`${PREVIEW}?member=m1`)
      fireEvent.click(await screen.findByRole("button", { name: "Next page" }))
      await waitFor(() => expect(router.state.location.search).toBe("?member=m1&cursor=c-2"))
      expect(requestsTo(listPath("m1")).at(-1)!.path).toContain("cursor=c-2")
      expect(await screen.findByRole("button", { name: "First page" })).toBeInTheDocument()
      await router.navigate(-1)
      await waitFor(() => expect(router.state.location.search).toBe("?member=m1"))
    })

    it("restores the same preview after a reload (the address alone reproduces it)", async () => {
      setup(`${PREVIEW}?member=m1&character_id=c1&party_id=p1&view=recent`)
      const banner = await screen.findByRole("region", { name: "Preview context" })
      expect(banner).toHaveTextContent("Character perspective: Ixa. Party perspective: Red Company.")
      expect(screen.getByRole("combobox", { name: "View" })).toHaveValue("recent")
      expect(requestsTo(listPath("m1")).at(-1)!.path).toContain("view=recent&character_id=c1&party_id=p1")
    })

    it("treats an unknown view as the default rather than sending it", async () => {
      setup(`${PREVIEW}?member=m1&view=everything`)
      await screen.findByText("Mira can see this.")
      expect(requestsTo(listPath("m1")).at(-1)!.path).toContain("view=known")
    })
  })

  describe("a claim in the preview", () => {
    it("shows the member's own projection, read-only, with the context preserved", async () => {
      const { router } = setup(`${PREVIEW}/k1?member=m1&character_id=c1&view=rumors&cursor=abc`)
      expect(await screen.findByRole("heading", { level: 2, name: "Mira can see this." })).toBeInTheDocument()
      const banner = screen.getByRole("region", { name: "Preview context" })
      expect(banner).toHaveTextContent("Previewing as Mira")
      expect(banner).toHaveTextContent("Character perspective: Ixa")
      expect(requestsTo(/\/members\/m1\/preview\/knowledge\/k1\?character_id=c1$/)).toHaveLength(1)
      expect(screen.getByText("Aware")).toBeInTheDocument()
      expect(screen.getByText("70%")).toBeInTheDocument()
      // The subject is text, not a link out of the preview; absent fields are simply absent.
      expect(screen.getByText("Keep")).toBeInTheDocument()
      expect(screen.queryByRole("link", { name: "Keep" })).toBeNull()
      expect(screen.queryByText("Truth")).toBeNull()
      expect(screen.queryByText("Sensitivity")).toBeNull()

      const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" })
      expect(within(crumbs).getByRole("link", { name: "Knowledge" })).toHaveAttribute("href", BASE)
      expect(within(crumbs).getByRole("link", { name: "Member preview" })).toHaveAttribute(
        "href",
        `${PREVIEW}?member=m1&character_id=c1&view=rumors&cursor=abc`,
      )
      expect(within(crumbs).getByText("Claim")).toHaveAttribute("aria-current", "page")
      fireEvent.click(screen.getByRole("link", { name: "Back to Member preview" }))
      await waitFor(() => expect(router.state.location.pathname).toBe(PREVIEW))
      expect(router.state.location.search).toBe("?member=m1&character_id=c1&view=rumors&cursor=abc")
    })

    it("has no editing, source, lifecycle or knowledge-management control, and makes none of those requests", async () => {
      setup(`${PREVIEW}/k1?member=m1`)
      await screen.findByRole("heading", { level: 2, name: "Mira can see this." })
      const main = within(screen.getByRole("main"))
      expect(main.queryByRole("textbox")).toBeNull()
      expect(main.queryByRole("combobox", { name: /^(Member|Character to preview|Party to preview|View)$/ })).toBeNull()
      expect(
        main.queryByRole("button", { name: /Save|Discard|Submit|Approve|Publish|Archive|Restore|Tell|Make public|Add source|Record/ }),
      ).toBeNull()
      expect(screen.queryByRole("navigation", { name: "Claim stages" })).toBeNull()
      expect(requestsTo(/\/authoring\/|\/lifecycle|\/provenance|\/sources|\/audience$|\/parties/)).toHaveLength(0)
      expect(server.calls.filter((c) => c.method !== "GET")).toHaveLength(0)
      expect(normalKnowledgeReads()).toHaveLength(0)
    })

    it("says a claim the member cannot see is not visible to them, rather than missing", async () => {
      server.on("GET", /\/members\/m1\/preview\/knowledge\/k1(\?.*)?$/, { status: 404 })
      setup(`${PREVIEW}/k1?member=m1`)
      expect(await screen.findByRole("alert")).toHaveTextContent(/Mira cannot see this claim/)
    })

    it("shows ground truth only when the server's projection for that member includes it", async () => {
      server.on("GET", /\/members\/m1\/preview\/knowledge\/k1(\?.*)?$/, {
        body: {
          knowledge_item_id: "k1",
          knowledge_type_code: "secret",
          statement: "A GM-level view.",
          truth_status_code: "true",
          sensitivity: "secret",
          awareness_level: null,
          confidence: null,
          willing_to_share: null,
          subject: null,
        },
      })
      setup(`${PREVIEW}/k1?member=m1`)
      expect(await screen.findByText("Truth")).toBeInTheDocument()
      expect(screen.getByText("True")).toBeInTheDocument()
      expect(screen.getByText(/No character or party perspective is selected/)).toBeInTheDocument()
    })

    it("labels values as character knowledge for a character perspective", async () => {
      setup(`${PREVIEW}/k1?member=m1&character_id=c1`)
      expect(await screen.findByRole("heading", { level: 3, name: "Character knowledge: Ixa" })).toBeInTheDocument()
      expect(screen.queryByRole("heading", { name: /Party knowledge/ })).toBeNull()
      expect(screen.getByText("70%")).toBeInTheDocument()
    })

    it("labels values as party knowledge when a party is selected", async () => {
      setup(`${PREVIEW}/k1?member=m1&character_id=c1&party_id=p1`)
      expect(await screen.findByRole("heading", { level: 3, name: "Party knowledge: Red Company" })).toBeInTheDocument()
      expect(screen.queryByRole("heading", { name: /Character knowledge/ })).toBeNull()
      expect(screen.getByText("Aware")).toBeInTheDocument()
    })

    it.each([
      ["c1", "p1", "Red Company"],
      ["c1", null, "Ixa"],
    ])("uses neutral wording when the projection omits the details (%s, %s)", async (character, party, name) => {
      server.on("GET", /\/members\/m1\/preview\/knowledge\/k1(\?.*)?$/, {
        body: {
          knowledge_item_id: "k1",
          knowledge_type_code: "rumor",
          statement: "Mira can see this.",
          subject: null,
        },
      })
      setup(`${PREVIEW}/k1?member=m1&character_id=${character}${party === null ? "" : `&party_id=${party}`}`)
      const note = await screen.findByText(/This projection includes no awareness, confidence or sharing details/)
      expect(note).toHaveTextContent(`for ${name}`)
      expect(screen.queryByText(/has no recorded knowledge/)).toBeNull()
    })

    it("uses the same neutral wording when the details are explicitly null", async () => {
      server.on("GET", /\/members\/m1\/preview\/knowledge\/k1(\?.*)?$/, {
        body: {
          knowledge_item_id: "k1",
          knowledge_type_code: "rumor",
          statement: "Mira can see this.",
          truth_status_code: null,
          sensitivity: null,
          awareness_level: null,
          confidence: null,
          willing_to_share: null,
          subject: null,
        },
      })
      setup(`${PREVIEW}/k1?member=m1&character_id=c1&party_id=p1`)
      expect(await screen.findByText(/This projection includes no awareness, confidence or sharing details for Red Company/)).toBeInTheDocument()
      expect(screen.queryByText(/has no recorded knowledge/)).toBeNull()
    })

    it("does not read the preview address as a claim id", async () => {
      setup(`${PREVIEW}?member=m1`)
      await screen.findByText("Mira can see this.")
      expect(requestsTo(/\/campaigns\/mundivita\/knowledge\/member-preview/)).toHaveLength(0)
      expect(requestsTo(/\/authoring\/knowledge\/member-preview/)).toHaveLength(0)
    })

    it("refuses an invalid selection on a claim address too", async () => {
      setup(`${PREVIEW}/k1?member=nobody`)
      expect(await screen.findByRole("alert")).toHaveTextContent(/cannot be previewed/)
      expect(requestsTo(/\/preview\/knowledge\/k1/)).toHaveLength(0)
    })
  })

  describe("leaving the preview", () => {
    beforeEach(() => {
      server.on("GET", /^\/campaigns\/mundivita\/knowledge\?/, { body: { items: [item("k5", "Normal claim.")], next_cursor: null } })
    })

    it("returns to the ordinary Knowledge collection with none of the preview's selections", async () => {
      const { router } = setup(`${PREVIEW}?member=m1&character_id=c1&party_id=p1&view=rumors&q=x`)
      const banner = await screen.findByRole("region", { name: "Preview context" })
      fireEvent.click(within(banner).getByRole("link", { name: "Return to Knowledge" }))
      await waitFor(() => expect(router.state.location.pathname).toBe(BASE))
      expect(router.state.location.search).toBe("")
      expect(await screen.findByText("Normal claim.")).toBeInTheDocument()
      const normal = normalKnowledgeReads().at(-1)!
      expect(normal.path).not.toMatch(/member|q=x|rumors|party_id=p1/)
      expect(screen.queryByRole("region", { name: "Preview context" })).toBeNull()
      expect(screen.getByRole("heading", { level: 1, name: "Knowledge" })).toBeInTheDocument()
    })

    it("lets the sidebar move between Claims and Member preview with the right item active", async () => {
      const { router } = setup(BASE)
      await screen.findByText("Normal claim.")
      const group = screen.getByRole("button", { name: "Knowledge" })
      expect(group).toHaveAttribute("aria-expanded", "true")
      expect(screen.getByRole("link", { name: "Claims" })).toHaveAttribute("aria-current", "page")
      expect(screen.getByRole("link", { name: "Member preview" })).not.toHaveAttribute("aria-current")
      fireEvent.click(screen.getByRole("link", { name: "Member preview" }))
      await waitFor(() => expect(router.state.location.pathname).toBe(PREVIEW))
      expect(router.state.location.search).toBe("")
      await screen.findByRole("heading", { level: 2, name: "Choose a member to preview" })
      fireEvent.click(screen.getByRole("button", { name: "Knowledge" }))
      expect(screen.getByRole("link", { name: "Member preview" })).toHaveAttribute("aria-current", "page")
      expect(screen.getByRole("link", { name: "Claims" })).not.toHaveAttribute("aria-current")
    })

    it("keeps Member preview active on a preview claim, and Claims active on an ordinary claim", async () => {
      const first = setup(`${PREVIEW}/k1?member=m1`)
      await screen.findByRole("heading", { level: 2, name: "Mira can see this." })
      const sidebar = () => within(screen.getByRole("navigation", { name: "Main" }))
      expect(sidebar().getByRole("link", { name: "Member preview" })).toHaveAttribute("aria-current", "page")
      expect(sidebar().getByRole("link", { name: "Claims" })).not.toHaveAttribute("aria-current")
      first.unmount()
      server.on("GET", /^\/campaigns\/mundivita\/knowledge\/k1/, { body: { knowledge_item_id: "k1", knowledge_type_code: "rumor", statement: "Ordinary.", truth_status_code: null, sensitivity: null, awareness_level: null, confidence: null, willing_to_share: null, subject: null } })
      server.on("GET", /\/authoring\/knowledge\/k1$/, { status: 404 })
      server.on("GET", /\/authoring\/knowledge\/options$/, { status: 404 })
      server.on("GET", /\/entities\/k1\//, { status: 404 })
      server.on("GET", /\/audience$/, { status: 404 })
      server.on("GET", /\/parties/, { status: 404 })
      setup(`${BASE}/k1`)
      await screen.findByRole("heading", { level: 1, name: "Ordinary." })
      expect(sidebar().getByRole("link", { name: "Claims" })).toHaveAttribute("aria-current", "page")
      expect(sidebar().getByRole("link", { name: "Member preview" })).not.toHaveAttribute("aria-current")
    })
  })

  describe("the normal Knowledge pages", () => {
    it("no longer carry a per-page 'Preview as member' control", async () => {
      server.on("GET", /^\/campaigns\/mundivita\/knowledge\?/, { body: { items: [item("k5", "Normal claim.")], next_cursor: null } })
      setup(BASE)
      await screen.findByText("Normal claim.")
      expect(screen.queryByRole("button", { name: /Preview as member/ })).toBeNull()
      expect(requestsTo(/access-overview/)).toHaveLength(0)
    })

    it("shows the plain Knowledge link, and no Member preview, to someone who cannot manage access", async () => {
      server.on("GET", /^\/campaigns\/mundivita\/knowledge\?/, { body: { items: [], next_cursor: null } })
      setup(BASE, ["campaign.view", "canon.edit"])
      await screen.findByRole("heading", { level: 1, name: "Knowledge" })
      const nav = screen.getByRole("navigation", { name: "Main" })
      expect(within(nav).getByRole("link", { name: "Knowledge" })).toHaveAttribute("aria-current", "page")
      expect(within(nav).queryByRole("link", { name: "Member preview", hidden: true })).toBeNull()
    })
  })
})
