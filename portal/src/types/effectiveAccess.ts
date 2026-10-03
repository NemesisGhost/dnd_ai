export interface EffectiveAccessSource {
    // One of "role" | "character_relationship" | "resource_grant" |
    // "access_group" — server-authoritative, never narrowed client-side.
    kind: string
    label: string
    target_display_name: string | null
}

export interface EffectiveAccessCapability {
    code: string
    display_name: string
    sources: EffectiveAccessSource[]
}

export interface EffectiveAccessDenial {
    capability_code: string
    target_type: string
    target_display_name: string | null
}

export interface MemberEffectiveAccess {
    display_name: string
    capabilities: EffectiveAccessCapability[]
    denials: EffectiveAccessDenial[]
}
