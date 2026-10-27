import type { RecordAuthoring } from "../utils/recordAuthoring"

// What a world Owner holds on a record in their own campaign: the fixtures' default, so a test
// about anything else is not about roles.
export const FULL_RECORD_AUTHORING: RecordAuthoring = {
    campaign_originated: false,
    can_read_private: true,
    can_edit: true,
    can_review: true,
}

// A campaign GM with no world role: runs the campaign, and holds nothing of the shared definition.
export const CAMPAIGN_ONLY_RECORD_AUTHORING: RecordAuthoring = {
    campaign_originated: false,
    can_read_private: false,
    can_edit: false,
    can_review: false,
}

export const EDITOR_RECORD_AUTHORING: RecordAuthoring = {
    campaign_originated: false,
    can_read_private: true,
    can_edit: true,
    can_review: false,
}

export const REVIEWER_RECORD_AUTHORING: RecordAuthoring = {
    campaign_originated: false,
    can_read_private: true,
    can_edit: false,
    can_review: true,
}

// A campaign-originated record (player-character identity, an item instance): the campaign alone
// authorizes it, so a campaign-only GM holds all of it.
export const ORIGINATED_RECORD_AUTHORING: RecordAuthoring = {
    campaign_originated: true,
    can_read_private: true,
    can_edit: true,
    can_review: true,
}

// The world capabilities of an Owner (the bootstrap's per-campaign snapshot).
export const OWNER_WORLD_CAPABILITIES: readonly string[] = [
    "world.view",
    "world.canon.read",
    "world.canon.read_private",
    "world.canon.edit",
    "world.canon.review",
    "timeline.manage",
]

// A campaign GM with no world role.
export const NO_WORLD_CAPABILITIES: readonly string[] = []
