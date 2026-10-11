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

function ObjectiveItem({ objective }: { objective: QuestObjective }) {
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

    // A restrained list item inside the expanded stage (no nested card). The details stay a native
    // disclosure with a text indicator, so state never relies on colour.
    // quest_objective_id is only a React key and is never rendered.
    return (
        <li className="quest-objective-list__item">
            <details className="disclosure">
                <summary>
                    <strong>{objective.name}</strong>
                    <span className="quest-objective-list__meta">{status}</span>
                    <span className="quest-objective-list__meta">
                        {humanizeCode(objective.requirement_level)}
                    </span>
                    <span
                        className="disclosure__indicator disclosure__indicator--expand"
                        aria-hidden="true"
                    />
                </summary>
                <div className="quest-objective-list__body">
                    <FactGrid items={factItems} />
                </div>
            </details>
        </li>
    )
}

// A collapsible stage card. The objective list is audience-filtered, so the count
// describes only the objectives shown; it is never a whole-stage status.
function StagePanel({
    stage,
    expanded,
    onToggle,
}: {
    stage: QuestStage
    expanded: boolean
    onToggle: () => void
}) {
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
                    onClick={onToggle}
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
                    <ul className="quest-objective-list">
                        {stage.objectives.map((objective) => (
                            <ObjectiveItem
                                key={objective.quest_objective_id}
                                objective={objective}
                            />
                        ))}
                    </ul>
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
    // Presentation only: stages start collapsed; nothing is persisted or sent.
    const [opened, setOpened] = useState<ReadonlySet<string>>(new Set())
    const allOpen = stages.length > 0 && stages.every((s) => opened.has(s.quest_stage_id))
    const toggle = (id: string) =>
        setOpened((prev) => {
            const next = new Set(prev)
            if (next.has(id)) next.delete(id)
            else next.add(id)
            return next
        })

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
                    <>
                        <p>
                            <button
                                type="button"
                                className="authoring-button"
                                onClick={() =>
                                    setOpened(allOpen ? new Set() : new Set(stages.map((s) => s.quest_stage_id)))
                                }
                            >
                                {allOpen ? "Collapse all" : "Expand all"}
                            </button>
                        </p>
                        <div className="quest-detail__stage-list">
                            {stages.map((stage) => (
                                <StagePanel
                                    key={stage.quest_stage_id}
                                    stage={stage}
                                    expanded={opened.has(stage.quest_stage_id)}
                                    onToggle={() => toggle(stage.quest_stage_id)}
                                />
                            ))}
                        </div>
                    </>
                ) : (
                    <p>No stages are available for this quest.</p>
                )}
            </section>
        </section>
    )
}
