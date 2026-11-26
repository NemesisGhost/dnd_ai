import type { QuestAction, ScopeProgress } from "../../types/questRuntime"
import type { QuestChoice, QuestOutcomeView } from "../../types/questAuthoring"
import { statusLabel } from "./questStatusLabel"

export interface QuestOptionLabels {
    outcomeCategories: readonly QuestChoice[]
    rewardTypes: readonly QuestChoice[]
}

const VERB: Readonly<Partial<Record<QuestAction, string>>> = {
    complete: "Completing",
    fail: "Failing",
    abandon: "Abandoning",
}

const labelOf = (choices: readonly QuestChoice[], value: string): string =>
    choices.find((c) => c.value === value)?.label ?? value

interface Props {
    // The scope as it was when the person chose the action: the same one the command will name.
    scope: ScopeProgress
    action: QuestAction
    // Null when this view cannot read the quest's definition (a campaign GM without a world role runs
    // the quest but does not prepare it): nothing is invented, and the absence is said.
    outcomes: readonly QuestOutcomeView[] | null
    labels: QuestOptionLabels
}

// What finishing a quest will change, and what the quest only describes. The status command records
// the quest's status for one scope and nothing else: it chooses no outcome and gives no reward, so the
// authored outcomes and rewards are shown as descriptions, never as consequences. Read-only.
export function QuestFinishReview({ scope, action, outcomes, labels }: Props) {
    const who = scope.party_name ?? "Everyone"
    const notComplete = scope.objectives.filter((o) => o.requirement_level === "required" && o.status !== "completed").length
    return (
        <div className="quest-finish-review">
            <p>For: {who}</p>
            <p>Now: {statusLabel(scope.status)}</p>
            {scope.objectives.length === 0 ? (
                <p>This quest has no objectives.</p>
            ) : (
                <>
                    <ul className="op-list">
                        {scope.objectives.map((o) => (
                            <li key={o.quest_objective_id}>
                                {`${o.stage_name}: ${o.name}${o.requirement_level === "required" ? "" : " (optional)"} — ${statusLabel(o.status)}`}
                            </li>
                        ))}
                    </ul>
                    <p>
                        {notComplete === 0
                            ? "All required objectives are complete."
                            : notComplete === 1
                              ? "1 required objective is not complete."
                              : `${notComplete} required objectives are not complete.`}
                    </p>
                </>
            )}
            {outcomes === null ? (
                <p>This view does not show the quest&apos;s authored outcomes or rewards.</p>
            ) : outcomes.length === 0 ? (
                <p>This quest describes no outcomes or rewards.</p>
            ) : (
                <>
                    <h3>Described in this quest</h3>
                    <ul className="op-list">
                        {outcomes.map((outcome) => (
                            <li key={outcome.quest_outcome_id}>
                                <span>{`${outcome.name} (${labelOf(labels.outcomeCategories, outcome.outcome_category)})`}</span>
                                {outcome.rewards.length > 0 ? (
                                    <ul>
                                        {outcome.rewards.map((r) => (
                                            <li key={r.quest_reward_id}>
                                                {`${labelOf(labels.rewardTypes, r.reward_type)}: ${r.description}${r.knowledge !== null ? ` (${r.knowledge.name})` : ""}`}
                                            </li>
                                        ))}
                                    </ul>
                                ) : null}
                            </li>
                        ))}
                    </ul>
                </>
            )}
            <p>
                {`${VERB[action] ?? "Finishing"} records only the quest's status for ${who}. No outcome is chosen and no reward is given or recorded. Apply any reward yourself.`}
            </p>
        </div>
    )
}
