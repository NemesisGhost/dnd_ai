import type { CharacterDetail, CharacterSections } from "../types/character"

// What a character answer without `sections` (a server that predates them) is read as. Missing
// contract data is not eligibility: the pages keep what they did before sections existed and add
// nothing the server has not explicitly granted.
//   - The sheet is still tried (its own read falls back to the summary panels when refused), and the
//     relationships show themselves only when their reads are allowed: both are what these pages
//     always did.
//   - The inventory is NOT offered. Before sections it was only ever requested (and hidden when
//     refused); a reader cannot tell from a missing field whether they hold the full tier, so no
//     link is shown and no request is made. A server that sends `sections` decides.
//   - There is no Parties entry, which never existed on these pages.
const WITHOUT_SECTIONS: CharacterSections = {
    details: true,
    sheet: true,
    relationships: true,
    inventory: false,
    parties: false,
}

// A present `sections` is always the server's answer: a flag that is false, or missing from it, is
// not offered. Only an absent `sections` falls back, and the fallback never grants inventory.
export function sectionsOf(character: Pick<CharacterDetail, "sections">): CharacterSections {
    const sections = character.sections
    if (sections === undefined || sections === null) return WITHOUT_SECTIONS
    return {
        details: sections.details === true,
        sheet: sections.sheet === true,
        relationships: sections.relationships === true,
        inventory: sections.inventory === true,
        parties: sections.parties === true,
    }
}
