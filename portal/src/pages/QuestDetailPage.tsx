import { Link } from "react-router"
import { DetailPanel } from "../components/DetailPanel"
import { FactGrid } from "../components/FactGrid"
import type {
    QuestDetail,
    QuestObjective,
    QuestStage,
} from "../types/quest"
import { humanizeCode } from "../utils/humanize"

interface QuestDetailPageProps {
    quest: QuestDetail
}

function ObjectiveCard({ objective }: { objective: QuestObjective }) {
    const status =
        objective.status_code !== null
            ? humanizeCode(objective.status_code)
            : "No status recorded"

    const factItems = [
        {
            key: "description",
            label: "Description",
            value: objective.description ?? "No description recorded.",
        },
        {
            key: "completion-mode",
            label: "Completion mode",
            value: humanizeCode(objective.completion_mode),
        },
    ]

    if (objective.quantity_required !== null) {
        factItems.push({
            key: "quantity",
            label: "Quantity required",
            value: String(objective.quantity_required),
        })
    }

    // Reuses the character-sheet disclosure card visual/accessibility
    // precedent (native <details>/<summary>, explicit expand/collapse
    // indicator, no reliance on color). quest_objective_id is only a React
    // key — never rendered.
    return (
        <details className="quest-objective-card">
            <summary>
                <strong>{objective.name}</strong>
                <span>{status}</span>
                <span>{humanizeCode(objective.requirement_level)}</span>
                <span
                    className="quest-objective-card__indicator"
                    aria-hidden="true"
                />
            </summary>
            <div className="quest-objective-card__body">
                <FactGrid items={factItems} />
            </div>
        </details>
    )
}

function StagePanel({ stage }: { stage: QuestStage }) {
    return (
        <DetailPanel
            title={`${stage.sequence_number}. ${stage.name}`}
            description={humanizeCode(stage.stage_type)}
            isEmpty={stage.objectives.length === 0}
            emptyState={<p>No objectives are available for this stage.</p>}
        >
            {stage.description !== null && (
                <p className="quest-detail__stage-description">
                    {stage.description}
                </p>
            )}

            <div className="quest-detail__objective-grid">
                {stage.objectives.map((objective) => (
                    <ObjectiveCard
                        key={objective.quest_objective_id}
                        objective={objective}
                    />
                ))}
            </div>
        </DetailPanel>
    )
}

export function QuestDetailPage({
    quest,
}: QuestDetailPageProps) {
    const stages = quest.stages

    return (
        <section aria-labelledby="quest-heading">
            <p>
                <Link to=".." relative="path">
                    Back to quests
                </Link>
            </p>

            <p className="quest-detail__eyebrow">Quest</p>
            <h1 id="quest-heading">{quest.name}</h1>
            <p className="quest-detail__status">
                Status: {quest.status_code !== null
                    ? humanizeCode(quest.status_code)
                    : "No status recorded"}
            </p>

            <section aria-labelledby="quest-stages-heading">
                <h2 id="quest-stages-heading">Stages and Objectives</h2>

                {stages.length > 0 ? (
                    <div className="quest-detail__stage-grid">
                        {stages.map((stage) => (
                            <StagePanel
                                key={stage.quest_stage_id}
                                stage={stage}
                            />
                        ))}
                    </div>
                ) : (
                    <p>No stages are available for this quest.</p>
                )}
            </section>
        </section>
    )
}
