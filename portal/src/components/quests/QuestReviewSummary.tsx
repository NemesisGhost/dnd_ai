import type { QuestAuthoringView, QuestOptions } from "../../types/questAuthoring"
import { statusDetail } from "../../utils/locationForm"

const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`

// What a reviewer checks in a quest, read from the saved definition: its shape and the records its
// objectives point at. Information only; the decision is the server-offered step beside it, and a
// target that is not published is shown with its own status because it blocks publishing.
export function QuestReviewSummary({ view, options }: { view: QuestAuthoringView; options: QuestOptions }) {
    const objectives = view.stages.flatMap((s) => s.objectives)
    const required = objectives.filter((o) => o.requirement_level === "required").length
    const visibility = options.visibility_policies
        .map((choice) => ({
            label: choice.label,
            count: objectives.filter((o) => o.visibility_policy === choice.value).length,
        }))
        .filter((entry) => entry.count > 0)
    const targets = new Map<string, { name: string; status: string }>()
    for (const o of objectives) {
        if (o.target !== null) {
            targets.set(o.target.entity_id, {
                name: o.target.name,
                status: statusDetail(o.target.canon_status, o.target.lifecycle_status),
            })
        }
    }
    return (
        <dl className="authoring-fact-list" aria-label="Quest structure">
            <dt>Stages</dt>
            <dd>{view.stages.length === 0 ? "None yet" : plural(view.stages.length, "stage")}</dd>
            <dt>Objectives</dt>
            <dd>
                {objectives.length === 0
                    ? "None yet. A quest needs a stage with an objective before it can be published."
                    : `${plural(objectives.length, "objective")}, ${required} required`}
            </dd>
            {visibility.length > 0 ? (
                <>
                    <dt>Who sees objectives</dt>
                    <dd>{visibility.map((entry) => `${entry.label}: ${entry.count}`).join(", ")}</dd>
                </>
            ) : null}
            {targets.size > 0 ? (
                <>
                    <dt>Records the objectives point at</dt>
                    <dd>
                        <ul className="record-list">
                            {[...targets.entries()].map(([id, t]) => (
                                <li key={id}>
                                    {t.name} ({t.status})
                                </li>
                            ))}
                        </ul>
                    </dd>
                </>
            ) : null}
            <dt>Completion design</dt>
            <dd>
                {plural((view.dependencies ?? []).length, "dependency", "dependencies")},{" "}
                {plural((view.outcomes ?? []).length, "outcome")}, {plural((view.participants ?? []).length, "participant")}
            </dd>
        </dl>
    )
}
