import { useState } from "react"
import { Link } from "react-router"
import { AudiencePreviewSection } from "../components/AudiencePreviewSection"
import { FactGrid } from "../components/FactGrid"
import type {
    QuestDetail,
    QuestObjective,
    QuestStage,
} from "../types/quest"
import { humanizeCode } from "../utils/humanize"
import "../components/authoring/authoring.css"

interface QuestDetailPageProps {
    campaignId: string
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

// A collapsible stage card. The objective list is audience-filtered, so the count
// describes only the objectives shown; it is never a whole-stage status.
function StagePanel({ stage }: { stage: QuestStage }) {
    const [expanded, setExpanded] = useState(true)
    const bodyId = `stage-body-${stage.quest_stage_id}`
    const total = stage.objectives.length
    const completed = stage.objectives.filter((o) => o.status_code === "completed").length
    const progress =
        total === 0 ? "No objectives shown" : `Shown objectives: ${completed} of ${total} complete`

    return (
        <div className="quest-stage-card">
            <h3 className="quest-stage-card__title">
                <button
                    type="button"
                    className="quest-stage-card__toggle"
                    aria-expanded={expanded}
                    aria-controls={bodyId}
                    onClick={() => setExpanded((open) => !open)}
                >
                    <span className="quest-stage-card__name">
                        <span className="quest-stage-card__number">{stage.sequence_number}.</span>{" "}
                        {stage.name}
                    </span>
                    <span className="quest-stage-card__summary">
                        {progress} · {humanizeCode(stage.stage_type)}
                    </span>
                    <span className="quest-stage-card__chevron" aria-hidden="true">
                        {expanded ? "Collapse −" : "Expand +"}
                    </span>
                </button>
            </h3>
            <div id={bodyId} className="quest-stage-card__body" hidden={!expanded}>
                {stage.description !== null && (
                    <p className="quest-detail__stage-description">{stage.description}</p>
                )}
                <p className="quest-stage-card__status-line">
                    {progress}.
                </p>
                {stage.objectives.length === 0 ? (
                    <p>No objectives are shown for this stage.</p>
                ) : (
                    <div className="quest-detail__objective-grid">
                        {stage.objectives.map((objective) => (
                            <ObjectiveCard
                                key={objective.quest_objective_id}
                                objective={objective}
                            />
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}

export function QuestDetailPage({
    campaignId,
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

            <AudiencePreviewSection
                campaignId={campaignId}
                resourceType="quest"
                fixedResource={{ id: quest.quest_id, display_name: quest.name }}
            />

            <section aria-labelledby="quest-stages-heading">
                <h2 id="quest-stages-heading">Stages and Objectives</h2>

                {stages.length > 0 ? (
                    <div className="quest-detail__stage-list">
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
