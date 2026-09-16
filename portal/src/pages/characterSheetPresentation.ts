import type { CharacterSheetSkill } from "../types/characterSheet"

export function humanizeCode(code: string): string {
    return code.split("_").filter(Boolean)
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ")
}

export function describeSpellLevel(level: number): string {
    return level === 0 ? "Cantrip" : `Level ${level}`
}

export function distributeSkills(
    skills: CharacterSheetSkill[],
    requestedCount: number,
): CharacterSheetSkill[][] {
    if (skills.length === 0) return []
    const count = Math.min(skills.length, Math.max(1, Math.floor(requestedCount)), 3)
    const base = Math.floor(skills.length / count)
    const extra = skills.length % count
    let offset = 0
    return Array.from({ length: count }, (_, index) => {
        const size = base + (index < extra ? 1 : 0)
        const group = skills.slice(offset, offset + size)
        offset += size
        return group
    })
}
