import type { ReactNode } from "react"
import type { CharacterPublicProfile } from "../../types/character"
import { DetailPanel } from "../DetailPanel"
import { FactGrid } from "../FactGrid"

// The released public profile, read-only. It takes only the released profile, so it cannot show a
// live field, and it renders only what was released: a null field is omitted, never replaced by a
// placeholder. Nothing here says anything about what was withheld.
export function CharacterPublicProfilePanel({ profile }: { profile: CharacterPublicProfile }) {
    const facts: { key: string; label: string; value: ReactNode }[] = []
    if (profile.species !== null) facts.push({ key: "species", label: "Species", value: profile.species.label })
    if (profile.size !== null) facts.push({ key: "size", label: "Size", value: profile.size.label })
    const paragraphs: { key: string; label: string; text: string }[] = []
    if (profile.summary !== null) paragraphs.push({ key: "summary", label: "Summary", text: profile.summary })
    if (profile.appearance !== null) paragraphs.push({ key: "appearance", label: "Appearance", text: profile.appearance })
    if (profile.background !== null) paragraphs.push({ key: "background", label: "Background", text: profile.background })
    const empty = facts.length === 0 && paragraphs.length === 0

    return (
        <DetailPanel title="Public profile" headingId="character-public-profile-heading">
            {empty ? (
                <p className="detail-panel__empty">No public details have been shared.</p>
            ) : (
                <>
                    {facts.length > 0 ? <FactGrid items={facts} /> : null}
                    {paragraphs.map((paragraph) => (
                        <div key={paragraph.key}>
                            <h3>{paragraph.label}</h3>
                            <p>{paragraph.text}</p>
                        </div>
                    ))}
                </>
            )}
        </DetailPanel>
    )
}
