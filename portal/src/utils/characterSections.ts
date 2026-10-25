import type { CharacterDetail, CharacterSections } from "../types/character"

// What a character answer without `sections` (a server that predates them) is read as: the pages
// behave as they did before sections existed. The sheet is still tried (its own read falls back to
// the summary panels when refused), the relationships and the inventory panel show themselves only
// when their reads are allowed, and there is no Parties entry, which never existed on these pages.
const BEFORE_SECTIONS: CharacterSections = {
    details: true,
    sheet: true,
    relationships: true,
    inventory: true,
    parties: false,
}

export function sectionsOf(character: Pick<CharacterDetail, "sections">): CharacterSections {
    return character.sections ?? BEFORE_SECTIONS
}
