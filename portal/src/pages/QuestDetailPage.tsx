import { Link } from "react-router"
import type { QuestDetail } from "../types/quest"

interface QuestDetailPageProps {
    quest: QuestDetail
}

export function QuestDetailPage({
    quest,
}: QuestDetailPageProps) {
    const stages = quest.stages

    return (
        <section aria-labelledby="quest-heading">
            <Link to=".." relative="path">
                Back to quests
            </Link>
            <h1 id="quest-heading">{quest.name}</h1>
            <p>Status: {quest.status_code ?? "No status recorded"}</p>
            <section aria-labelledby="quest-stages-heading">
                <h2 id="quest-stages-heading">Stages and objectives</h2>
                {stages.length > 0 ? (
                    <table>
                        <caption>Quest stages and objectives</caption>
                        <thead>
                            <tr>
                                <th scope="col">Sequence</th>
                                <th scope="col">Name</th>
                                <th scope="col">Type</th>
                                <th scope="col">Description</th>
                                <th scope="col">Objectives</th>
                            </tr>
                        </thead>
                        <tbody>
                            {stages.map((stage) => (
                                <tr key={stage.quest_stage_id}>
                                    <td>{stage.sequence_number}</td>
                                    <td>{stage.name}</td>
                                    <td>{stage.stage_type}</td>
                                    <td>
                                        {stage.description ??
                                            "No description recorded"}
                                    </td>
                                    <td>
                                        {stage.objectives.length > 0 ? (
                                            <details>
                                                <summary>
                                                    {stage.objectives.length === 1
                                                        ? "1 available objective"
                                                        : `${stage.objectives.length} available objectives`}
                                                </summary>
                                                <ul>
                                                    {stage.objectives.map((objective) => (
                                                        <li key={objective.quest_objective_id}>
                                                            <details>
                                                                <summary>
                                                                    {objective.name}
                                                                </summary>
                                                                <dl>
                                                                    <div>
                                                                        <dt>Description</dt>
                                                                        <dd>
                                                                            {objective.description ??
                                                                                "No description recorded"}
                                                                        </dd>
                                                                    </div>
                                                                    <div>
                                                                        <dt>Status</dt>
                                                                        <dd>
                                                                            {objective.status_code ??
                                                                                "No status recorded"}
                                                                        </dd>
                                                                    </div>
                                                                    <div>
                                                                        <dt>Requirement level</dt>
                                                                        <dd>
                                                                            {objective.requirement_level}
                                                                        </dd>
                                                                    </div>
                                                                    <div>
                                                                        <dt>Completion mode</dt>
                                                                        <dd>
                                                                            {objective.completion_mode}
                                                                        </dd>
                                                                    </div>
                                                                    {objective.quantity_required !==
                                                                        null && (
                                                                        <div>
                                                                            <dt>Quantity required</dt>
                                                                            <dd>
                                                                                {objective.quantity_required}
                                                                            </dd>
                                                                        </div>
                                                                    )}
                                                                </dl>
                                                            </details>
                                                        </li>
                                                    ))}
                                                </ul>
                                            </details>
                                        ) : (
                                            "No objectives are available for this stage."
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                ) : (
                    <p>No stages are available for this quest.</p>
                )}
            </section>
        </section>
    )
}
