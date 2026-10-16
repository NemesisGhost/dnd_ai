import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const BUILDS = "/campaigns/mundivita/authoring/characters/c1/builds"
const OPTIONS = "/campaigns/mundivita/authoring/character-build-options"

const BUILD_OPTIONS = {
  limits: {
    label_max_length: 200,
    ability_score_min: 1,
    ability_score_max: 30,
    class_level_min: 1,
    class_level_max: 20,
    target_label_max_length: 200,
    max_hit_points: 10000,
  },
  unsupported: [],
  spells: [{ id: "sp-bolt", name: "Fire Bolt", code: "fire_bolt", level: 0 }],
  abilities: [
    { id: "ab-str", name: "Strength", code: "strength" },
    { id: "ab-dex", name: "Dexterity", code: "dexterity" },
  ],
  classes: [{ id: "cl-fighter", name: "Fighter", code: "fighter", hit_die: 10 }],
  subclasses: [{ id: "sc-champ", name: "Champion", code: "champion", class_id: "cl-fighter" }],
  skills: [{ id: "sk-ath", name: "Athletics", code: "athletics" }],
  proficiency_types: [
    { id: "pt-skill", name: "Skill", code: "skill", target_kind: "skill" },
    { id: "pt-save", name: "Saving throw", code: "saving_throw", target_kind: "saving_throw" },
    { id: "pt-weapon", name: "Weapon", code: "weapon", target_kind: "free_text" },
  ],
  features: [
    { id: "ft-second", name: "Second Wind", code: "second_wind", class_id: "cl-fighter", subclass_id: null, granted_at_level: 1 },
  ],
}

const build = (id: string, label: string, active: boolean) => ({
  character_build_id: id,
  label,
  ruleset_version_id: "rv",
  created_at: "2026-01-01T00:00:00Z",
  is_active: active,
  counts: { abilities: 2, classes: 1, proficiencies: 3, features: 1, spellcasting: 0 },
})

function listing(overrides: Record<string, unknown> = {}) {
  return {
    character: { character_id: "c1", name: "Aldric", kind: "player_character" },
    state: { initialized: true, current_hit_points: 9, maximum_hit_points: 12 },
    active_build_id: "b1",
    builds: [build("b1", "Level 1", true), build("b2", "Level 2", false)],
    ...overrides,
  }
}

let server: MockServer

beforeEach(() => {
  server = installCampaignShellMocks()
  server.on("GET", OPTIONS, { body: BUILD_OPTIONS })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("character build pages", () => {
  it("lists builds, marks the active one, and offers activation only for the others", async () => {
    server.on("GET", BUILDS, { body: listing() })
    openApp("/app/mundivita/characters/c1/builds")
    expect(await screen.findByRole("heading", { level: 1, name: "Builds" })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(await screen.findByText(/Hit points: 9 of 12/)).toBeInTheDocument()
    expect(screen.getByText(/\(active\)/)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Activate Level 1" })).toBeNull()
    expect(screen.getByRole("button", { name: "Activate Level 2" })).toBeEnabled()
    expect(screen.getByRole("link", { name: "New build" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/c1/builds/new",
    )
  })

  it("activates after a confirmation, sending the build the editor saw as active", async () => {
    let state = listing()
    server.on("GET", BUILDS, () => ({ body: state }))
    server.on("POST", `${BUILDS}/b2/activate`, () => {
      state = listing({
        active_build_id: "b2",
        builds: [build("b1", "Level 1", false), build("b2", "Level 2", true)],
      })
      return { body: { character_id: "c1", character_build_id: "b2", event_id: "ev", created: false, changed: true } }
    })
    openApp("/app/mundivita/characters/c1/builds")
    fireEvent.click(await screen.findByRole("button", { name: "Activate Level 2" }))
    expect(server.callsTo("POST", /./)).toHaveLength(0)
    const dialog = await screen.findByRole("dialog", { name: "Activate this build?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Activate build" }))
    await waitFor(() => expect(server.callsTo("POST", `${BUILDS}/b2/activate`)).toHaveLength(1))
    const [call] = server.callsTo("POST", `${BUILDS}/b2/activate`)
    expect(call!.body).toEqual({ expected_active_build_id: "b1" })
    expect(call!.headers["Idempotency-Key"]).toBeTruthy()
    await waitFor(() =>
      expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Build activated"),
    )
  })

  it.each([
    ["character_not_published", /Publish the character/],
    ["clock_required", /Set the campaign time/],
  ])("explains %s inside the confirmation", async (code, text) => {
    server.on("GET", BUILDS, { body: listing() })
    server.on("POST", `${BUILDS}/b2/activate`, {
      status: 409,
      body: { error: { code, message: "m", correlation_id: "c" } },
    })
    openApp("/app/mundivita/characters/c1/builds")
    fireEvent.click(await screen.findByRole("button", { name: "Activate Level 2" }))
    const dialog = await screen.findByRole("dialog", { name: "Activate this build?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Activate build" }))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(text)
  })

  it("asks for starting state first and will not activate without it", async () => {
    server.on("GET", BUILDS, {
      body: listing({
        state: { initialized: false, current_hit_points: null, maximum_hit_points: null },
        active_build_id: null,
        builds: [build("b1", "Level 1", false)],
      }),
    })
    server.on("POST", "/campaigns/mundivita/authoring/characters/c1/state/initialize", {
      status: 201,
      body: { character_id: "c1", created: true, changed: true },
    })
    openApp("/app/mundivita/characters/c1/builds")
    expect(await screen.findByRole("button", { name: "Activate Level 1" })).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: "Set starting state" }))
    expect(await screen.findAllByText(/Maximum hit points must be a whole number/)).not.toHaveLength(0)
    expect(server.callsTo("POST", /./)).toHaveLength(0)
    fireEvent.change(screen.getByLabelText(/Maximum hit points/), { target: { value: "14" } })
    fireEvent.click(screen.getByRole("button", { name: "Set starting state" }))
    await waitFor(() => expect(server.callsTo("POST", /initialize/)).toHaveLength(1))
    expect(server.callsTo("POST", /initialize/)[0]!.body).toEqual({
      maximum_hit_points: 14,
      current_hit_points: null,
    })
  })

  it("shows a plain unavailable message for a character that has no builds read", async () => {
    server.on("GET", BUILDS, {
      status: 404,
      body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
    })
    openApp("/app/mundivita/characters/c1/builds")
    expect(await screen.findByRole("alert")).toHaveTextContent("does not exist, or you do not have access")
  })

  it("builds a request from the form: scores, class, proficiencies, features", async () => {
    server.on("POST", BUILDS, {
      status: 201,
      body: { character_id: "c1", character_build_id: "b9", created: true, changed: true },
    })
    server.on("GET", BUILDS, { body: listing() })
    openApp("/app/mundivita/characters/c1/builds/new")
    expect(await screen.findByRole("heading", { level: 1, name: "New build" })).toBeInTheDocument()

    // Nothing is sent until the form is valid.
    fireEvent.change(await screen.findByLabelText("Strength"), { target: { value: "99" } })
    fireEvent.click(screen.getByRole("button", { name: "Create build" }))
    expect(await screen.findAllByText(/Strength must be a whole number from 1 to 30/)).not.toHaveLength(0)
    expect(server.callsTo("POST", /./)).toHaveLength(0)

    fireEvent.change(screen.getByLabelText("Strength"), { target: { value: "16" } })
    fireEvent.change(screen.getByLabelText("Label"), { target: { value: "Level 1" } })
    fireEvent.click(screen.getByRole("button", { name: "Add a class" }))
    fireEvent.change(screen.getByLabelText(/Class 1/), { target: { value: "cl-fighter" } })
    fireEvent.change(screen.getByLabelText(/Level 1 \(required\)/), { target: { value: "3" } })
    fireEvent.click(screen.getByLabelText("Athletics"))
    fireEvent.click(screen.getByLabelText("Strength saving throw"))
    fireEvent.click(screen.getByLabelText("Second Wind"))
    fireEvent.click(screen.getByRole("button", { name: "Add spellcasting" }))
    fireEvent.change(screen.getByLabelText(/Casting ability 1/), { target: { value: "ab-dex" } })
    const known = screen.getByRole("group", { name: "Known spells 1" })
    fireEvent.click(within(known).getByLabelText(/Fire Bolt/))
    fireEvent.click(screen.getByRole("button", { name: "Create build" }))

    await waitFor(() => expect(server.callsTo("POST", BUILDS)).toHaveLength(1))
    expect(server.callsTo("POST", BUILDS)[0]!.body).toEqual({
      label: "Level 1",
      ability_scores: [{ ability_id: "ab-str", score: 16 }],
      class_levels: [{ class_id: "cl-fighter", subclass_id: null, level: 3 }],
      proficiencies: [
        { proficiency_type_id: "pt-skill", skill_id: "sk-ath", is_expertise: false },
        { proficiency_type_id: "pt-save", saving_throw_ability_id: "ab-str", is_expertise: false },
      ],
      feature_ids: ["ft-second"],
      spellcasting: [
        {
          class_id: null,
          spellcasting_ability_id: "ab-dex",
          known_spell_ids: ["sp-bolt"],
          prepared_spell_ids: [],
        },
      ],
    })
  })

  it("gives editors a Builds link on a character and a player nothing", async () => {
    server.on("GET", "/campaigns/mundivita/characters/c1", {
      body: {
        character_id: "c1",
        name: "Aldric",
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
      },
    })
    for (const path of [
      "/campaigns/mundivita/authoring/npcs/c1",
      "/campaigns/mundivita/authoring/player-characters/c1",
      "/campaigns/mundivita/entities/c1/lifecycle",
    ]) {
      server.on("GET", path, {
        status: 404,
        body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
      })
    }
    server.on("GET", BUILDS, { body: listing() })
    const editor = openApp("/app/mundivita/world/character/c1")
    expect(await screen.findByRole("link", { name: "Builds and starting state" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/c1/builds",
    )
    editor.unmount()
    server.calls.length = 0
    openApp("/app/mundivita/world/character/c1", ["campaign.view"])
    await screen.findByRole("heading", { level: 1, name: "Aldric" })
    expect(screen.queryByRole("link", { name: "Builds and starting state" })).toBeNull()
    expect(server.calls.some((c) => c.path.includes("/authoring/"))).toBe(false)
  })
})
