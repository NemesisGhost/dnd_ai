import { useState } from "react"
import {
    createRelationship,
    entityRelationshipsPath,
    relationshipOptionsPath,
} from "../api/relationshipAuthoring"
import { fetchWorldEntities } from "../api/world"
import { useAnnounce } from "./authoring/announcer"
import { RelationshipEditor } from "./authoring/RelationshipEditor"
import { SelectField, TextAreaField, TextField } from "./authoring/fields"
import { MutationStatusMessage } from "./authoring/feedback"
import { ReferenceCombobox } from "./authoring/ReferenceCombobox"
import type { ReferenceOption } from "./authoring/ReferenceCombobox"
import { WorldTimePicker } from "./authoring/WorldTimePicker"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import type {
    CreateRelationshipBody,
    RelationshipList,
    RelationshipOptions,
    RelationshipView,
} from "../types/relationshipAuthoring"
import { RELATIONSHIP_CODE_MESSAGE } from "../utils/relationshipForm"
import "./authoring/authoring.css"

interface Props {
    campaignId: string
    entityId: string
}

const humanize = (code: string): string => code.replace(/_/g, " ")

// The relationships an entity takes part in, for editors: every edge (private and archived
// ones included), the editor for each, and a form to add another. Mounted on the world
// detail pages; players and observers get nothing and send no request.
export function RelationshipsPanel({ campaignId, entityId }: Props) {
    if (!useCampaignCapability(campaignId, "canon.edit")) return null
    return <LoadedPanel campaignId={campaignId} entityId={entityId} />
}

function LoadedPanel({ campaignId, entityId }: Props) {
    const [showArchived, setShowArchived] = useState(false)
    const [open, setOpen] = useState<string | null>(null)
    const list = useAuthoringResource<RelationshipList>(
        entityRelationshipsPath(campaignId, entityId, showArchived),
    )
    const options = useAuthoringResource<RelationshipOptions>(relationshipOptionsPath(campaignId))
    if (list.state.kind !== "ready" || options.state.kind !== "ready") return null
    const items = list.state.data.items
    const loadedOptions = options.state.data
    return (
        <section className="authoring-aside" aria-labelledby="relationships-heading">
            <h2 id="relationships-heading">Relationships</h2>
            {items.length === 0 ? <p>No relationships recorded.</p> : null}
            <ul className="authoring-choice-list">
                {items.map((item) => (
                    <li key={item.relationship_id}>
                        {item.participants.map((p) => `${p.name} (${p.role_label})`).join(" and ")}:{" "}
                        {item.relationship_type_label}
                        {item.lifecycle_status !== "active" ? " (archived)" : ""}
                        {item.ended ? " (ended)" : ""}
                        {item.is_public === false ? " (private)" : ""}{" "}
                        <button
                            type="button"
                            className="authoring-button"
                            aria-expanded={open === item.relationship_id}
                            onClick={() => setOpen(open === item.relationship_id ? null : item.relationship_id)}
                        >
                            {open === item.relationship_id ? "Close" : `Open ${humanize(item.relationship_type)}`}
                        </button>
                        {open === item.relationship_id ? (
                            <RelationshipEditor
                                campaignId={campaignId}
                                relationshipId={item.relationship_id}
                                options={loadedOptions}
                                onChanged={() => void list.refetch()}
                            />
                        ) : null}
                    </li>
                ))}
            </ul>
            <SelectField
                id="relationships-archived"
                label="Show archived relationships"
                value={showArchived ? "yes" : "no"}
                options={[
                    { value: "no", label: "No" },
                    { value: "yes", label: "Yes" },
                ]}
                onChange={(value) => setShowArchived(value === "yes")}
            />
            {loadedOptions.can_create ? (
                <AddRelationship
                    campaignId={campaignId}
                    entityId={entityId}
                    options={loadedOptions}
                    onCreated={() => void list.refetch()}
                />
            ) : null}
        </section>
    )
}

function AddRelationship({
    campaignId,
    entityId,
    options,
    onCreated,
}: {
    campaignId: string
    entityId: string
    options: RelationshipOptions
    onCreated: () => void
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [kind, setKind] = useState("")
    const [type, setType] = useState("")
    const [myRole, setMyRole] = useState("")
    const [other, setOther] = useState<ReferenceOption | null>(null)
    const [otherRole, setOtherRole] = useState("")
    const [description, setDescription] = useState("")
    const [start, setStart] = useState("")
    const [unit, setUnit] = useState("")
    const [title, setTitle] = useState("")
    const [share, setShare] = useState("")
    const [isPublic, setIsPublic] = useState("yes")
    const [terms, setTerms] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    const shape = options.kinds.find((k) => k.code === kind)

    const mutation = useAuthoringMutation<CreateRelationshipBody, RelationshipView>({
        scopeKey: `create-relationship:${entityId}`,
        request: (body, ctx) => createRelationship(campaignId, body, ctx),
        onSuccess: () => {
            setOther(null)
            setDescription("")
            onCreated()
            announce("Relationship added")
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const explained = error?.code ? (RELATIONSHIP_CODE_MESSAGE[error.code] ?? null) : null

    async function searchOthers(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchWorldEntities(campaignId, { category: null, query, limit: 10 }, signal)
        return page.items
            .filter((item) => item.category !== "item" && item.category !== "event" && item.entity_id !== entityId)
            .map((item) => ({ id: item.entity_id, label: item.name, detail: humanize(item.entity_type_code) }))
    }

    function submit() {
        if (shape === undefined || type === "" || myRole === "" || otherRole === "" || other === null) {
            setProblem("Choose the kind, the type, both roles and the other participant.")
            return
        }
        const shareValue = share.trim() === "" ? null : Number(share)
        if (kind === "ownership" && shareValue !== null && (!Number.isInteger(shareValue) || shareValue < 0 || shareValue > 100)) {
            setProblem("Share is a whole number from 0 to 100.")
            return
        }
        setProblem(null)
        const body: CreateRelationshipBody = {
            kind,
            relationship_type: type,
            participants: [
                { entity_id: entityId, role: myRole },
                { entity_id: other.id, role: otherRole },
            ],
            description: description.trim() === "" ? null : description.trim(),
            started_world_time_id: start === "" ? null : start,
        }
        if (kind === "family" && unit.trim() !== "") body.family_unit_name = unit.trim()
        if (kind === "employment" && title.trim() !== "") body.job_title = title.trim()
        if (kind === "ownership") {
            body.ownership_share = shareValue
            body.is_public = isPublic === "yes"
        }
        if (kind === "political" && terms.trim() !== "") body.treaty_terms = terms.trim()
        mutation.submit(body)
    }

    const roleOptions = (shape?.roles ?? []).map((r) => ({ value: r, label: humanize(r) }))
    return (
        <form
            noValidate
            aria-label="Add a relationship"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                submit()
            }}
        >
            <h3>Add a relationship</h3>
            {explained !== null ? (
                <p role="alert">{explained}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            <SelectField
                id="rel-new-kind"
                label="Kind"
                value={kind}
                placeholder="Choose a kind"
                options={options.kinds.map((k) => ({ value: k.code, label: k.label }))}
                onChange={(next) => {
                    setKind(next)
                    setType("")
                    setMyRole("")
                    setOtherRole("")
                }}
            />
            {shape !== undefined ? (
                <>
                    <SelectField
                        id="rel-new-type"
                        label="Type"
                        value={type}
                        placeholder="Choose a type"
                        options={shape.types.map((t) => ({ value: t, label: humanize(t) }))}
                        onChange={setType}
                    />
                    <SelectField
                        id="rel-new-my-role"
                        label="This record is the"
                        value={myRole}
                        placeholder="Choose a role"
                        options={roleOptions}
                        onChange={setMyRole}
                    />
                    <ReferenceCombobox
                        id="rel-new-other"
                        label="Other participant"
                        value={other}
                        onChange={setOther}
                        search={searchOthers}
                        error={problem}
                        placeholder="Search"
                    />
                    <SelectField
                        id="rel-new-other-role"
                        label="The other participant is the"
                        value={otherRole}
                        placeholder="Choose a role"
                        options={roleOptions}
                        onChange={setOtherRole}
                    />
                    <TextAreaField
                        id="rel-new-description"
                        label="Description"
                        value={description}
                        onChange={setDescription}
                        maxLength={options.limits.text_max_length}
                    />
                    <WorldTimePicker
                        campaignId={campaignId}
                        id="rel-new-start"
                        label="Started (optional)"
                        value={start}
                        onChange={setStart}
                    />
                    {kind === "family" ? (
                        <TextField id="rel-new-unit" label="Family name" value={unit} onChange={setUnit} />
                    ) : null}
                    {kind === "employment" ? (
                        <TextField id="rel-new-title" label="Job title" value={title} onChange={setTitle} />
                    ) : null}
                    {kind === "ownership" ? (
                        <>
                            <TextField id="rel-new-share" label="Share (0 to 100)" value={share} onChange={setShare} />
                            <SelectField
                                id="rel-new-public"
                                label="Known to the public"
                                value={isPublic}
                                options={[
                                    { value: "yes", label: "Yes" },
                                    { value: "no", label: "No, only editors see it" },
                                ]}
                                onChange={setIsPublic}
                            />
                        </>
                    ) : null}
                    {kind === "political" ? (
                        <TextAreaField id="rel-new-terms" label="Terms" value={terms} onChange={setTerms} />
                    ) : null}
                    <button
                        type="submit"
                        className="authoring-button"
                        disabled={mutation.status.kind === "pending"}
                    >
                        Add relationship
                    </button>
                </>
            ) : null}
        </form>
    )
}
