import { useId } from "react"
import { FactGrid } from "../components/FactGrid"
import type { CharacterSheet } from "../types/characterSheet"
import { humanizeCode } from "./characterSheetPresentation"

export function CharacterDetailsPanel({ sheet }: { sheet: CharacterSheet }) {
    const headingId = useId()
    return (
        <header className="detail-panel character-sheet__header" aria-labelledby={headingId}>
            <p className="character-sheet__eyebrow">Character Details</p>
            <h1 id={headingId}>{sheet.name}</h1>
            <FactGrid className="character-sheet__header-facts" items={[
                { key: "species", label: "Species", value: sheet.species_display_name },
                { key: "size", label: "Size", value: humanizeCode(sheet.size_category) },
                { key: "classes", label: "Classes", value: sheet.class_levels.length > 0 ? (
                    <ul className="character-sheet__inline-list">{sheet.class_levels.map((entry) => (
                        <li key={entry.class_id}>{entry.class_display_name} {entry.level}
                            {entry.subclass_display_name !== null && ` — ${entry.subclass_display_name}`}
                            {` — d${entry.hit_die}`}</li>
                    ))}</ul>
                ) : "None recorded" },
                { key: "total-level", label: "Character level", value: sheet.total_level },
                { key: "build", label: "Build", value: sheet.build_label ?? "No active build" },
                { key: "ruleset", label: "Ruleset", value: sheet.ruleset_display_name ?? "Not recorded" },
                { key: "ruleset-version", label: "Ruleset version", value: sheet.ruleset_version_label ?? "Not recorded" },
            ]} />
        </header>
    )
}
