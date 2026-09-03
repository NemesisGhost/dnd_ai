import {
    describe,
    expect,
    it,
} from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { CampaignContext } from "../types/bootstrap"
import { resolveSelectedCharacterId } from "./characterPerspective"

const fixtureCampaign =
    sessionBootstrapFixture.campaigns[0]

if (fixtureCampaign === undefined) {
    throw new Error(
        "The session bootstrap fixture must contain a campaign",
    )
}

describe("resolveSelectedCharacterId", () => {
    it("keeps a requested character that remains authorized", () => {
        const campaign = {
            ...fixtureCampaign,
            selected_character_id: null,
            character_perspectives: [
                ...fixtureCampaign.character_perspectives,
                {
                    character_id: "character-second",
                    character_name: "Second Character",
                },
            ],
        } satisfies CampaignContext

        expect(
            resolveSelectedCharacterId(
                campaign,
                "character-second",
            ),
        ).toBe("character-second")
    })

    it("falls back to the server default when the requested character is unavailable", () => {
        expect(
            resolveSelectedCharacterId(
                fixtureCampaign,
                "character-revoked",
            ),
        ).toBe("character-ixamarra")
    })

    it("returns null when no authorized perspective exists", () => {
        const campaign = {
            ...fixtureCampaign,
            selected_character_id: null,
            character_perspectives: [],
        } satisfies CampaignContext

        expect(
            resolveSelectedCharacterId(
                campaign,
                "character-revoked",
            ),
        ).toBeNull()
    })

    it("rejects an inconsistent server default", () => {
        const campaign = {
            ...fixtureCampaign,
            selected_character_id: "character-not-authorized",
        } satisfies CampaignContext

        expect(
            resolveSelectedCharacterId(campaign, null),
        ).toBeNull()
    })
})