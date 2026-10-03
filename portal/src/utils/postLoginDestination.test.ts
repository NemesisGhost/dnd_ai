import { describe, expect, it } from "vitest"
import { resolvePostLoginDestination } from "./postLoginDestination"

describe("resolvePostLoginDestination", () => {
  it("defaults to /home when there is no continuation state", () => {
    expect(resolvePostLoginDestination(undefined)).toBe("/home")
    expect(resolvePostLoginDestination(null)).toBe("/home")
    expect(resolvePostLoginDestination({})).toBe("/home")
  })

  it("accepts an allowlisted path with a query string", () => {
    expect(
      resolvePostLoginDestination({ from: "/app/mundivita/quests?x=1" }),
    ).toBe("/app/mundivita/quests?x=1")
  })

  it.each([
    ["home", "/home"],
    ["campaigns", "/campaigns"],
    ["settings", "/settings"],
    ["account", "/account"],
    ["platform accounts", "/platform/accounts"],
    ["a campaign subsection", "/app/mundivita/access/audit"],
    ["a bare campaign route", "/app/mundivita"],
  ])("accepts %s", (_description, from) => {
    expect(resolvePostLoginDestination({ from })).toBe(from)
  })

  it.each([
    ["a protocol-relative URL", "//evil"],
    ["an absolute URL", "https://evil"],
    ["the login route itself", "/login"],
    ["account activation", "/auth/activate"],
    ["invitation acceptance", "/campaign-invitations/accept"],
    ["a non-string value", 42],
    ["an oversized path", `/home${"a".repeat(2048)}`],
    ["a backslash", "/\\evil"],
    ["an unknown top-level route", "/nope"],
    ["an empty string", ""],
  ])("rejects %s and falls back to /home", (_description, from) => {
    expect(resolvePostLoginDestination({ from })).toBe("/home")
  })
})
