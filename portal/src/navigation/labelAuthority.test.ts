import { describe, expect, it } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { SessionBootstrap } from "../types/bootstrap"
import { authorityFingerprint } from "./labelAuthority"

const base = (): SessionBootstrap => structuredClone(sessionBootstrapFixture) as SessionBootstrap
const CAMPAIGN = "mundivita"
const fp = (bootstrap: SessionBootstrap, character: string | null = "character-ixamarra") =>
    authorityFingerprint(bootstrap, CAMPAIGN, character)

function withCampaign(change: (campaign: SessionBootstrap["campaigns"][number]) => void): SessionBootstrap {
    const bootstrap = base()
    change(bootstrap.campaigns[0]!)
    return bootstrap
}

describe("authorityFingerprint", () => {
    it("is null without a session, a campaign, or a campaign the session lists", () => {
        expect(authorityFingerprint(null, CAMPAIGN, null)).toBeNull()
        expect(authorityFingerprint(base(), null, null)).toBeNull()
        expect(authorityFingerprint(base(), "someone-elses", null)).toBeNull()
    })

    it("is stable for the same authority, whatever order lists arrive in", () => {
        const reordered = withCampaign((c) => {
            c.capabilities = ["b", "a"]
            c.world_capabilities = ["y", "x"]
        })
        const original = withCampaign((c) => {
            c.capabilities = ["a", "b"]
            c.world_capabilities = ["x", "y"]
        })
        expect(fp(reordered)).toBe(fp(original))
        expect(fp(base())).toBe(fp(base()))
    })

    it("ignores bootstrap fields that are not authority (names, the CSRF token, features)", () => {
        const renamed = withCampaign((c) => {
            c.campaign_name = "Renamed"
            c.world_name = "Renamed"
        })
        renamed.csrf_token = "another"
        renamed.features.ask = true
        expect(fp(renamed)).toBe(fp(base()))
    })

    it.each<[string, (bootstrap: SessionBootstrap) => void]>([
        ["the signed-in user", (b) => void (b.user.user_id = "someone-else")],
        ["the browser session", (b) => void (b.browser_session_id = "another-session")],
        ["campaign roles", (b) => void (b.campaigns[0]!.roles = ["player"])],
        ["campaign capabilities", (b) => void b.campaigns[0]!.capabilities.push("canon.edit")],
        ["world capabilities", (b) => void (b.campaigns[0]!.world_capabilities = ["world.view"])],
        ["the available perspectives", (b) => void (b.campaigns[0]!.character_perspectives = [])],
        ["the campaign's world", (b) => void (b.campaigns[0]!.world_id = "another-world")],
        ["the campaign's timeline", (b) => void (b.campaigns[0]!.timeline_id = "another-timeline")],
        ["the clock-set state", (b) => void (b.campaigns[0]!.current_time_set = false)],
    ])("changes with %s", (_name, change) => {
        const changed = base()
        change(changed)
        expect(fp(changed)).not.toBeNull()
        expect(fp(changed)).not.toBe(fp(base()))
    })

    it("changes with the committed perspective, including clearing it", () => {
        expect(fp(base(), "character-ixamarra")).not.toBe(fp(base(), null))
        expect(fp(base(), "character-ixamarra")).not.toBe(fp(base(), "character-other"))
    })

    it("treats an absent clock-set field as set, as the pages do", () => {
        const explicit = withCampaign((c) => void (c.current_time_set = true))
        expect(fp(explicit)).toBe(fp(base()))
    })
})
