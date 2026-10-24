import type { CharacterKnowledgePath, KnowledgeDetail } from "../types/knowledge"
import { humanizeCode } from "./humanize"

// How the selected character knows a claim, as the server resolved it (the same resolution the
// Knowledge list uses). A claim being viewable never implies the character knows it, and a
// missing personal record never implies the character does not: the path says which it is.
export interface CharacterKnowledgeView {
    // Where the knowledge comes from; null only for a payload that predates the path.
    path: CharacterKnowledgePath | null
    facts: { key: string; label: string; value: string }[]
}

const PATH_SENTENCE: Readonly<Record<CharacterKnowledgePath, string>> = {
    character: "Known directly by the character.",
    party: "Known through a party the character belongs to.",
    public: "Public knowledge. The character has no personal record of it.",
}

export function characterKnowledgePathSentence(path: CharacterKnowledgePath): string {
    return PATH_SENTENCE[path]
}

// `null` means no character-knowledge path covers the claim for the selected character. Only the
// values a record actually holds are listed; nothing is filled in for a record that omits them.
export function characterKnowledgeOf(item: KnowledgeDetail): CharacterKnowledgeView | null {
    const known = item.character_knowledge
    const source =
        known === undefined
            ? {
                  path: null,
                  awareness_level: item.awareness_level,
                  confidence: item.confidence,
                  willing_to_share: item.willing_to_share,
              }
            : known
    if (source === null) return null
    const facts = [
        source.awareness_level !== null && source.awareness_level !== undefined
            ? { key: "awareness", label: "Awareness", value: humanizeCode(source.awareness_level) }
            : null,
        source.confidence !== null && source.confidence !== undefined
            ? { key: "confidence", label: "Confidence", value: `${source.confidence}%` }
            : null,
        source.willing_to_share !== null && source.willing_to_share !== undefined
            ? { key: "share", label: "Willing to share", value: source.willing_to_share ? "Yes" : "No" }
            : null,
    ].filter((entry) => entry !== null)
    // A payload without the block and without any recorded value is the old "nothing recorded".
    if (known === undefined && facts.length === 0) return null
    return { path: source.path, facts }
}
