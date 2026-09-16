import { useId } from "react"
import formatSignedNumber from "../utils/signedNumbers"

export interface AbilityScoreCardSavingThrow {
    bonus: number | null
    isProficient: boolean
}

interface AbilityScoreCardProps {
    abilityDisplayName: string
    score: number
    modifier: number | null
    savingThrow: AbilityScoreCardSavingThrow | null
}

export function AbilityScoreCard({
    abilityDisplayName,
    score,
    modifier,
    savingThrow,
}: AbilityScoreCardProps) {
    const headingId = useId()

    return (
        <article
            className="ability-score-card"
            aria-labelledby={headingId}
        >
            <h3
                id={headingId}
                className="ability-score-card__name"
            >
                {abilityDisplayName}
            </h3>

            <p className="ability-score-card__modifier">
                {formatSignedNumber(modifier)}
            </p>

            <p className="ability-score-card__score">
                Score {score}
            </p>

            <p className="ability-score-card__save">
                <span className="ability-score-card__save-label">
                    Save
                </span>{" "}
                {savingThrow !== null ? (
                    <>
                        <span className="ability-score-card__save-bonus">
                            {formatSignedNumber(savingThrow.bonus)}
                        </span>{" "}
                        <span
                            className={
                                savingThrow.isProficient
                                    ? "ability-score-card__proficiency ability-score-card__proficiency--proficient"
                                    : "ability-score-card__proficiency"
                            }
                        >
                            {savingThrow.isProficient
                                ? "Proficient"
                                : "Not proficient"}
                        </span>
                    </>
                ) : (
                    <span className="ability-score-card__proficiency">
                        Not recorded
                    </span>
                )}
            </p>
        </article>
    )
}
