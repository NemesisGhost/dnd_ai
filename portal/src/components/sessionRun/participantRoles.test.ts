import { describe, expect, it } from "vitest"
import { effectiveRole, rolesForKind } from "./participantRoles"

const CATALOG = { player_character: ["player_character", "guest"], npc: ["npc", "guest"] }

describe("participant roles", () => {
  it("reads the roles from the server catalog, none for an unknown kind or a missing catalog", () => {
    expect(rolesForKind(CATALOG, "npc")).toEqual(["npc", "guest"])
    expect(rolesForKind(CATALOG, "character")).toEqual([])
    expect(rolesForKind(CATALOG, null)).toEqual([])
    expect(rolesForKind(undefined, "npc")).toEqual([])
  })

  it("defaults to the matching role and keeps Guest only when it was chosen and is allowed", () => {
    expect(effectiveRole(["npc", "guest"], false)).toBe("npc")
    expect(effectiveRole(["npc", "guest"], true)).toBe("guest")
    expect(effectiveRole([], true)).toBe("")
  })
})
