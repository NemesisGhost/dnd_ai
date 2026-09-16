import type { CharacterSheetFeature } from "../types/characterSheet"
import { humanizeCode } from "./characterSheetPresentation"

export function FeatureCard({ feature }: { feature: CharacterSheetFeature }) {
    return (
        <details className="character-disclosure-card">
            <summary>
                <strong>{feature.display_name}</strong>
                <span>{humanizeCode(feature.source_category)}</span>
                {feature.granted_at_level !== null && <span>Granted at level {feature.granted_at_level}</span>}
                <span className="character-disclosure-card__indicator" aria-hidden="true" />
            </summary>
            <div className="character-disclosure-card__body">
                <p>{feature.description ?? "No description recorded."}</p>
            </div>
        </details>
    )
}
