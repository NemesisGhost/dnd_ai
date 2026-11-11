import type { SessionBootstrap } from "../types/bootstrap"

// The authority a breadcrumb label was read under (docs/UI_DESIGN.md §4.8, plan §5.3).
//
// A label is a cached result of an authorized read, so it is only worth showing while the client still
// believes the same things about who the person is and what they may see. The fingerprint is a string
// built from exactly the bootstrap fields the client uses to decide that:
//
//   - the signed-in user and the browser session,
//   - for the scope campaign: its world and timeline, the person's roles, capabilities and world
//     capabilities, the character perspectives the person may take, and whether the campaign clock is
//     set (party-scoped eligibility depends on it, DEF-007),
//   - the committed perspective.
//
// Limits, stated plainly:
//   - It changes only when the client RECEIVES different bootstrap data (a refresh, a reload, a
//     perspective commit). It cannot detect a permission change the client has not yet learned about;
//     until then a label read earlier can still be shown. Following the link is what is authorized: the
//     server answers every read, and a denied read fails closed exactly as it does today.
//   - It is a comparison key kept in memory. It is never written to history, a URL or storage.
//
// `null` means there is no authority (no authenticated session, or the campaign is not in it).

function sorted(values: readonly string[] | undefined): string[] {
    return [...(values ?? [])].sort()
}

export function authorityFingerprint(
    bootstrap: SessionBootstrap | null,
    campaignId: string | null,
    characterId: string | null,
): string | null {
    if (bootstrap === null || campaignId === null) return null
    const campaign = bootstrap.campaigns.find((candidate) => candidate.campaign_id === campaignId)
    if (campaign === undefined) return null
    return JSON.stringify([
        bootstrap.user.user_id,
        bootstrap.browser_session_id,
        campaign.campaign_id,
        campaign.world_id,
        campaign.timeline_id,
        sorted(campaign.roles),
        sorted(campaign.capabilities),
        sorted(campaign.world_capabilities),
        sorted(campaign.character_perspectives.map((perspective) => perspective.character_id)),
        // Absent from an older server: treated as set, the same reading the pages use.
        campaign.current_time_set ?? true,
        characterId,
    ])
}
