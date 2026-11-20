// The GM read of a character's public profile and the two write receipts
// (docs/api/ACCESS_CONTROL.md §3v; docs/delivery/p15-c02-s01-draft-release-plan.md §2.2). The keys
// are exactly the server's. The copy affordances and the origin and provenance keys are typed so a
// response is complete, and are never rendered or read by this page (they belong to the copy
// consumer, a separate piece of work).

export interface PublicProfileLabel {
    name: string
    summary: string | null
}

export interface PublicProfileDraft {
    character_public_profile_id: string
    row_version: number
    updated_at: string
    public_summary: string | null
    publish_species: boolean
    publish_size: boolean
    // The text, or null when it is withheld from this reader (and `_withheld` says so).
    public_appearance: string | null
    public_appearance_withheld: boolean
    public_background: string | null
    public_background_withheld: boolean
    // Origin and provenance: typed, never rendered here.
    [origin: `public_${"appearance" | "background"}_${string}`]: unknown
}

export interface PublicProfileValue {
    code: string
    label: string
}

export interface PublicProfileRelease {
    character_public_profile_release_id: string
    version_number: number
    from_draft_row_version: number
    authority_source: "owner" | "delegation"
    released_at: string
    released_by: string | null
}

// The full snapshot of the latest release: its own text and published labels, never the draft's.
export interface PublicProfileLatestRelease extends PublicProfileRelease {
    public_appearance: string | null
    public_background: string | null
    public_summary: string | null
    release_note: string | null
    species: PublicProfileValue | null
    size: PublicProfileValue | null
    identity_entity_row_version: number | null
    [origin: `public_${"appearance" | "background"}_${string}`]: unknown
}

export interface IdentityPreview {
    character_row_version: number
    species: PublicProfileValue
    size: PublicProfileValue
}

export interface CharacterPublicProfileRead {
    character_id: string
    label: PublicProfileLabel
    draft: PublicProfileDraft | null
    has_unreleased_changes: boolean
    latest_release: PublicProfileLatestRelease | null
    // Metadata of every release, newest first, without text.
    releases: PublicProfileRelease[]
    can_edit: boolean
    can_release: boolean
    identity_preview: IdentityPreview | null
    identity_preview_withheld: boolean
    identity_differs_from_latest_release: boolean | null
    // Copy affordances: not rendered by this page.
    legacy_copy: unknown
    player_profile_copy: unknown
}

// The save body: `expected_row_version` is `null` for "no draft yet". A key left out is untouched,
// `null` clears a text field, and the two flags are strict booleans.
export interface SavePublicProfileDraftBody {
    expected_row_version: number | null
    public_summary?: string | null
    public_appearance?: string | null
    public_background?: string | null
    publish_species?: boolean
    publish_size?: boolean
}

export interface SavePublicProfileDraftReceipt {
    character_public_profile_id: string
    character_id: string
    row_version: number
    created: boolean
    changed: boolean
}

export interface ReleasePublicProfileBody {
    expected_draft_row_version: number
    release_note?: string
    // Only when the draft publishes species or size.
    expected_character_row_version?: number
}

export interface ReleasePublicProfileReceipt {
    character_public_profile_release_id: string
    character_public_profile_id: string
    character_id: string
    version_number: number
    from_draft_row_version: number
    authority_source: "owner" | "delegation"
    created: boolean
    is_latest: boolean
    species_published: boolean
    size_published: boolean
    identity_entity_row_version: number | null
}
