import { useId } from "react"
import { characterKnowledgePathSentence } from "../../utils/characterKnowledge"
import type { CharacterKnowledgeView } from "../../utils/characterKnowledge"
import { humanizeCode } from "../../utils/humanize"

interface Props {
    // The claim's kind code, shown first.
    kindCode: string
    // How the selected perspective knows the claim: `null` when no knowledge path covers it, and
    // `undefined` while there is nothing to resolve (no perspective is selected).
    known: CharacterKnowledgeView | null | undefined
    // Heading level: the claim page uses h2, a section panel or the preview h3.
    headingLevel?: 2 | 3
    // Whose knowledge this is, when the page does not already say (the Member preview).
    perspective?: string | null
    // Shown instead of the recorded values; defaults cover the normal cases.
    noPerspectiveNote?: string
    noKnowledgeNote?: string
    // Shown when a perspective is selected but the projection carries neither a path nor a value.
    neutralNote?: string
    // For a screen-reader name on a panel that sits under another section's heading.
    ariaLabel?: string
}

// One compact surface holding the claim's kind and what the selected perspective knows about it,
// each label above its value. Only values the record actually holds are listed: a missing
// confidence is never shown as 0, nor a missing willingness to share as No. The origin sentence
// ("Known through a party the character belongs to.") sits under the heading.
export function KnowledgeDetailsPanel({
    kindCode,
    known,
    headingLevel = 2,
    perspective = null,
    noPerspectiveNote = "Select a character perspective to see what that character knows.",
    noKnowledgeNote = "The selected character has no recorded knowledge of this claim.",
    neutralNote,
    ariaLabel,
}: Props) {
    const headingId = useId()
    const Heading = headingLevel === 2 ? "h2" : "h3"
    const facts = [{ key: "kind", label: "Kind", value: humanizeCode(kindCode) }, ...(known?.facts ?? [])]
    return (
        <section
            className="knowledge-details"
            {...(ariaLabel === undefined ? { "aria-labelledby": headingId } : { "aria-label": ariaLabel })}
        >
            <Heading id={headingId} className="knowledge-details__heading">
                Knowledge details
            </Heading>
            {perspective !== null ? <p className="knowledge-details__perspective">{perspective}</p> : null}
            {known === undefined ? (
                <p className="authoring-note">{noPerspectiveNote}</p>
            ) : known === null ? (
                <p className="authoring-note">{noKnowledgeNote}</p>
            ) : known.path !== null ? (
                <p className="authoring-note">{characterKnowledgePathSentence(known.path)}</p>
            ) : known.facts.length === 0 && neutralNote !== undefined ? (
                <p className="authoring-note">{neutralNote}</p>
            ) : null}
            <dl className="knowledge-details__grid">
                {facts.map((fact) => (
                    <div key={fact.key} className="knowledge-details__item">
                        <dt>{fact.label}</dt>
                        <dd>{fact.value}</dd>
                    </div>
                ))}
            </dl>
        </section>
    )
}
