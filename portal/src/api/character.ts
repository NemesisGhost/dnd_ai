import type {
    CharacterDetail,
    CharacterIdentityValue,
    CharacterKind,
    CharacterPublicProfile,
    CharacterRead,
} from "../types/character"

export class CharacterRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(`Character request failed with status ${status}`)
        this.name = "CharacterRequestError"
        this.status = status
    }
}

// An answer that is 2xx but not one the contract allows: an unknown tier, a public tier without its
// profile, or a body that is neither a tiered answer nor a recognized pre-tier one. It is never
// rendered, not even in part: the hook reports it as a read error.
export class CharacterContractError extends Error {
    constructor(reason: string) {
        super(`Character answer is not a recognized shape: ${reason}`)
        this.name = "CharacterContractError"
    }
}

const KINDS: readonly string[] = ["npc", "player_character", "character"]

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isKind(value: unknown): value is CharacterKind {
    return typeof value === "string" && KINDS.includes(value)
}

function nullableText(value: unknown, field: string): string | null {
    if (value === null || value === undefined) return null
    if (typeof value !== "string") throw new CharacterContractError(`${field} is not text`)
    return value
}

function identity(value: unknown, field: string): CharacterIdentityValue | null {
    if (value === null || value === undefined) return null
    if (!isRecord(value) || typeof value.code !== "string" || typeof value.label !== "string") {
        throw new CharacterContractError(`${field} is malformed`)
    }
    // Only the two contracted keys survive.
    return { code: value.code, label: value.label }
}

// The released profile projected onto exactly the contracted keys, so a key the contract does not
// define never reaches a component. This copies what the server sent; it never derives a value.
function profile(value: unknown): CharacterPublicProfile {
    if (!isRecord(value)) throw new CharacterContractError("public_profile is not an object")
    return {
        summary: nullableText(value.summary, "summary"),
        appearance: nullableText(value.appearance, "appearance"),
        background: nullableText(value.background, "background"),
        species: identity(value.species, "species"),
        size: identity(value.size, "size"),
    }
}

// Fields the server nulls for a caller authorized only for the summary tier.
const SUMMARY_NULL_FIELDS = [
    "current_hit_points",
    "maximum_hit_points",
    "temporary_hit_points",
    "exhaustion_level",
    "death_save_successes",
    "death_save_failures",
    "current_location_id",
    "active_encounter_id",
    "conditions",
    "resources",
] as const

function nullableArray(value: unknown): boolean {
    return value === null || Array.isArray(value)
}

// The pre-tier (before A4) summary/full shape: the identity fields and the live definition the old
// read model always carried, with the live-state keys present as arrays or null. A missing
// `view_tier` alone is not enough: a body that lacks the live definition (such as an incomplete
// public-shaped answer) is not this shape, and is refused rather than read as full access.
function isLegacyShape(body: Record<string, unknown>): boolean {
    return (
        typeof body.character_id === "string" &&
        typeof body.name === "string" &&
        isKind(body.character_kind) &&
        typeof body.species_code === "string" &&
        typeof body.size_category === "string" &&
        nullableArray(body.conditions) &&
        nullableArray(body.resources) &&
        !("public_profile" in body) &&
        (body.sections === undefined || isRecord(body.sections))
    )
}

// Reads a character answer as one of the three recognized shapes, or throws CharacterContractError.
//   - "public_profile": rebuilt from exactly the contracted keys.
//   - "summary" / "full": the identity fields must be present, `sections` must be an object and a
//     present profile must be well formed; everything else passes through unchanged.
//   - no `view_tier`: only a recognized pre-tier body (isLegacyShape), read as summary/full.
//   - any other tier value, or a malformed body: refused.
export function normalizeCharacterRead(body: unknown): CharacterRead {
    if (!isRecord(body)) throw new CharacterContractError("not an object")
    const tier = body.view_tier
    if (tier === "public_profile") {
        if (
            typeof body.character_id !== "string" ||
            typeof body.name !== "string" ||
            !isKind(body.character_kind) ||
            !isRecord(body.sections)
        ) {
            throw new CharacterContractError("public tier is incomplete")
        }
        const sections = body.sections
        return {
            view_tier: "public_profile",
            character_id: body.character_id,
            name: body.name,
            character_kind: body.character_kind,
            sections: {
                details: sections.details === true,
                sheet: sections.sheet === true,
                relationships: sections.relationships === true,
                inventory: sections.inventory === true,
                parties: sections.parties === true,
                public_profile: sections.public_profile === true,
            },
            public_profile: profile(body.public_profile),
        }
    }
    if (tier === "summary" || tier === "full") {
        if (
            typeof body.character_id !== "string" ||
            typeof body.name !== "string" ||
            !isKind(body.character_kind) ||
            !isRecord(body.sections)
        ) {
            throw new CharacterContractError(`${tier} tier is incomplete`)
        }
        // The summary tier carries no live mechanics. A summary body that does is contradictory: it is
        // refused rather than shown or run as if it were the full read.
        if (tier === "summary" && SUMMARY_NULL_FIELDS.some((field) => body[field] !== null && body[field] !== undefined)) {
            throw new CharacterContractError("summary tier carries live fields")
        }
        const released = body.public_profile === undefined || body.public_profile === null ? null : profile(body.public_profile)
        return { ...(body as unknown as CharacterDetail), public_profile: released }
    }
    if (tier === undefined && isLegacyShape(body)) {
        return body as unknown as CharacterDetail
    }
    throw new CharacterContractError(tier === undefined ? "no tier and not a pre-tier body" : "unknown tier")
}

export async function fetchCharacter(
    campaignId: string,
    characterId: string,
    signal?: AbortSignal,
): Promise<CharacterRead> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedCharacterId = encodeURIComponent(characterId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/characters/${encodedCharacterId}`,
        {
            method: "GET",
            headers: {
                Accept: "application/json",
            },
            cache: "no-store",
            signal,
        },
    )

    if (!response.ok) {
        throw new CharacterRequestError(response.status)
    }

    return normalizeCharacterRead(await response.json())
}

// The editors' pages (the World workspace, the NPC runtime panel) hold the raw JSON of this read
// through the authoring resource. They recognize it with the same rules as the reader: the one
// normalizer, so a body that is neither a valid tiered answer nor the recognized pre-tier shape is
// null, and the caller shows a controlled "unavailable" state with no character content or controls.
export function editorCharacterRead(body: unknown): CharacterRead | null {
    try {
        return normalizeCharacterRead(body)
    } catch (error) {
        if (error instanceof CharacterContractError) return null
        throw error
    }
}

// Whether this answer is one the NPC runtime panel may offer its controls for. Hit points,
// conditions and resources are full-tier mechanics: the public and summary tiers carry none, so
// neither can be run. A recognized pre-tier body (no `view_tier`) is the full read of a server that
// predates tiers. The server still authorizes every command.
export function isRunnableRead(read: CharacterRead): read is CharacterDetail {
    return read.view_tier === "full" || read.view_tier === undefined
}
