import { useId, useState } from "react"
import { useAudiencePreview } from "../hooks/useAudiencePreview"
import { ResourceTargetSelector, type ResourceOption } from "./ResourceTargetSelector"
import type { AudiencePreviewResourceType } from "../types/audiencePreview"

interface AudiencePreviewMember {
    campaign_membership_id: string
    display_name: string
}

interface AudiencePreviewContentProps {
    campaignId: string
    campaignMembershipId: string
    resourceType: AudiencePreviewResourceType
    resourceId: string
}

// Mounted (via a composite React key on the caller's side) only for the
// exact (member, resource type, resource) combination currently selected —
// remounting on any change, rather than merely updating props, is what
// guarantees the previously-rendered content is gone the instant a
// different selection is made, per this checkpoint's own "closing the
// panel or changing either selection clears the rendered result
// immediately" security invariant.
function AudiencePreviewContent({
    campaignId,
    campaignMembershipId,
    resourceType,
    resourceId,
}: AudiencePreviewContentProps) {
    const { state, retry } = useAudiencePreview(
        campaignId,
        campaignMembershipId,
        resourceType,
        resourceId,
    )

    if (state.status === "loading") {
        return <p>Loading preview…</p>
    }

    if (state.status === "unavailable") {
        return <p>This member cannot see this resource.</p>
    }

    if (state.status === "error") {
        return (
            <p>
                The preview could not be loaded.{" "}
                <button type="button" onClick={retry}>
                    Retry
                </button>
            </p>
        )
    }

    const { result } = state

    if (result.resourceType === "quest") {
        const { quest } = result
        return (
            <div className="audience-preview-panel__result">
                <p>
                    <strong>{quest.name}</strong>
                    {quest.status_code !== null && ` (${quest.status_code})`}
                </p>
                {quest.stages.length > 0 ? (
                    <ul>
                        {quest.stages.map((stage) => (
                            <li key={stage.quest_stage_id}>
                                {stage.name}
                                <ul>
                                    {stage.objectives.map((objective) => (
                                        <li key={objective.quest_objective_id}>
                                            {objective.name}
                                            {objective.status_code !== null &&
                                                ` — ${objective.status_code}`}
                                        </li>
                                    ))}
                                </ul>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p>No stages are visible to this member.</p>
                )}
            </div>
        )
    }

    const { knowledgeItem } = result
    return (
        <div className="audience-preview-panel__result">
            <p>{knowledgeItem.statement}</p>
            {knowledgeItem.truth_status_code !== null && (
                <p>Truth status: {knowledgeItem.truth_status_code}</p>
            )}
            {knowledgeItem.confidence !== null && <p>Confidence: {knowledgeItem.confidence}</p>}
        </div>
    )
}

interface AudiencePreviewPanelProps {
    campaignId: string
    members: AudiencePreviewMember[]
}

// The spoiler-checking half of D-1's "preview as a selected member" answer
// (docs/UI_DESIGN.md §16 / PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §8.4b,
// checkpoint 15) — never a global mode, never reachable from the player-
// facing screens, no route/URL change. Pick a member, pick a quest or
// knowledge item (reusing checkpoint 12's ResourceTargetSelector), see the
// rendered result inside a persistently labelled container naming both.
// Closing the panel, or changing either selection, clears the rendered
// result immediately — AudiencePreviewContent above is remounted (never
// merely re-rendered) for every distinct (member, resource) combination.
export function AudiencePreviewPanel({ campaignId, members }: AudiencePreviewPanelProps) {
    const [isOpen, setIsOpen] = useState(false)
    const [selectedMembershipId, setSelectedMembershipId] = useState("")
    const [selectedResourceType, setSelectedResourceType] =
        useState<AudiencePreviewResourceType>("quest")
    const [selectedResource, setSelectedResource] = useState<ResourceOption | null>(null)

    const headingId = useId()
    const memberSelectId = useId()
    const resourceTypeSelectId = useId()
    const resourceLabelId = useId()

    const selectedMember = members.find(
        (member) => member.campaign_membership_id === selectedMembershipId,
    )

    const canPreview = selectedMember !== undefined && selectedResource !== null

    return (
        <div className="audience-preview-panel">
            <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => setIsOpen((currentIsOpen) => !currentIsOpen)}
            >
                {isOpen ? "Hide audience preview" : "Preview as member"}
            </button>

            {isOpen && (
                <section aria-labelledby={headingId}>
                    <h4 id={headingId}>Preview as a member</h4>

                    <label htmlFor={memberSelectId}>Member</label>
                    <select
                        id={memberSelectId}
                        value={selectedMembershipId}
                        onChange={(event) => {
                            setSelectedMembershipId(event.currentTarget.value)
                        }}
                    >
                        <option value="">Select a member</option>
                        {members.map((member) => (
                            <option
                                key={member.campaign_membership_id}
                                value={member.campaign_membership_id}
                            >
                                {member.display_name}
                            </option>
                        ))}
                    </select>

                    <label htmlFor={resourceTypeSelectId}>Resource type</label>
                    <select
                        id={resourceTypeSelectId}
                        value={selectedResourceType}
                        onChange={(event) => {
                            setSelectedResourceType(
                                event.currentTarget.value as AudiencePreviewResourceType,
                            )
                            setSelectedResource(null)
                        }}
                    >
                        <option value="quest">Quest</option>
                        <option value="knowledge_item">Knowledge item</option>
                    </select>

                    <label id={resourceLabelId}>
                        {selectedResourceType === "quest" ? "Quest" : "Knowledge item"}
                    </label>
                    <ResourceTargetSelector
                        campaignId={campaignId}
                        targetType={selectedResourceType}
                        assignableCharacters={[]}
                        value={selectedResource?.id ?? ""}
                        disabled={false}
                        labelId={resourceLabelId}
                        onChange={setSelectedResource}
                    />

                    {canPreview && (
                        <div aria-live="polite">
                            <p className="audience-preview-panel__target">
                                Previewing {selectedResourceType === "quest" ? "quest" : "knowledge item"}{" "}
                                <strong>{selectedResource.display_name}</strong> as{" "}
                                <strong>{selectedMember.display_name}</strong>
                            </p>
                            <AudiencePreviewContent
                                key={`${selectedMembershipId}-${selectedResourceType}-${selectedResource.id}`}
                                campaignId={campaignId}
                                campaignMembershipId={selectedMembershipId}
                                resourceType={selectedResourceType}
                                resourceId={selectedResource.id}
                            />
                        </div>
                    )}
                </section>
            )}
        </div>
    )
}
