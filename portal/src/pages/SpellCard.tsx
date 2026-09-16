import { FactGrid } from "../components/FactGrid"
import type { CharacterSheetSpell } from "../types/characterSheet"
import { describeSpellLevel, humanizeCode } from "./characterSheetPresentation"

export function SpellCard({ spell }: { spell: CharacterSheetSpell }) {
    return (
        <details className="character-disclosure-card">
            <summary>
                <strong>{spell.display_name}</strong>
                <span>{describeSpellLevel(spell.level)}</span>
                {spell.school !== null && <span>{humanizeCode(spell.school)}</span>}
                <span>{spell.is_known ? "Known" : "Not known"}</span>
                <span>{spell.is_prepared ? "Prepared" : "Not prepared"}</span>
                <span className="character-disclosure-card__indicator" aria-hidden="true" />
            </summary>
            <div className="character-disclosure-card__body">
                <FactGrid items={[
                    { key: "casting", label: "Casting time", value: spell.casting_time ?? "Not recorded" },
                    { key: "range", label: "Range", value: spell.range ?? "Not recorded" },
                    { key: "duration", label: "Duration", value: spell.duration ?? "Not recorded" },
                    { key: "damage", label: "Damage type", value: spell.damage_type_display_name ?? "Not recorded" },
                ]} />
                <p>{spell.description ?? "No description recorded."}</p>
            </div>
        </details>
    )
}
