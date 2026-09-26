import { describe, expect, it } from "vitest"
import { buildInvitationOnboardingLink } from "./invitationLink"

describe("buildInvitationOnboardingLink", () => {
    it("builds a link from window.location.origin with an encoded token fragment", () => {
        const link = buildInvitationOnboardingLink("raw token/with special+chars")
        expect(link).toBe(
            `${window.location.origin}/campaign-invitations/accept#token=raw%20token%2Fwith%20special%2Bchars`,
        )
    })

    it("never appears un-encoded when the token contains a fragment-breaking character", () => {
        const link = buildInvitationOnboardingLink("a&b=c#d")
        expect(link).not.toContain("a&b=c#d")
        expect(decodeURIComponent(link.split("#token=")[1] ?? "")).toBe("a&b=c#d")
    })
})
