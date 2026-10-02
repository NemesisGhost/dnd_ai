import { describe, expect, it } from "vitest"
import { deriveInitials, deriveProfileAvatar } from "./profileIdentity"

describe("deriveInitials", () => {
  it.each([
    ["Campaign Administrator", "CA"],
    ["gm2", "G"],
    ["Ana María de la Cruz", "AC"],
    ["  ", null],
    ["—", null],
    ["Émile", "É"],
  ])("derives %j as %j", (input, expected) => {
    expect(deriveInitials(input)).toBe(expected)
  })

  it("does not split a combined grapheme cluster (emoji family)", () => {
    const familyEmoji = "👨‍👩‍👧‍👦"
    expect(deriveInitials(`${familyEmoji} Smith`)).toBe(
      `${familyEmoji.toLocaleUpperCase()}S`,
    )
  })

  it("returns at most two graphemes for many words", () => {
    expect(deriveInitials("Alpha Beta Gamma Delta")).toBe("AD")
  })
})

describe("deriveProfileAvatar", () => {
  it("prefers an image when imageUrl is a non-empty string", () => {
    expect(
      deriveProfileAvatar({
        displayName: "Campaign Administrator",
        imageUrl: "https://example.test/avatar.png",
      }),
    ).toEqual({ kind: "image", url: "https://example.test/avatar.png" })
  })

  it("falls back to initials when there is no image", () => {
    expect(
      deriveProfileAvatar({ displayName: "Campaign Administrator" }),
    ).toEqual({ kind: "initials", text: "CA" })
  })

  it("falls back to initials when imageUrl is an empty string", () => {
    expect(
      deriveProfileAvatar({
        displayName: "Campaign Administrator",
        imageUrl: "",
      }),
    ).toEqual({ kind: "initials", text: "CA" })
  })

  it("falls back to the generic icon when no usable name exists", () => {
    expect(
      deriveProfileAvatar({ displayName: "  " }),
    ).toEqual({ kind: "icon" })
  })
})
