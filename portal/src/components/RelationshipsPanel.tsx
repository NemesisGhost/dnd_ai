import { useState } from "react"
import { Link } from "react-router"
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
import type { WorldKind } from "./world/worldStages"
import "./authoring/authoring.css"
import { PanelFrame } from "./DetailPanel"

interface Props {
    campaignId: string
    entityId: string
    // A staged section already supplies the surface and the heading: render the content only.
    embedded?: boolean
    // What the record is, so the Add form offers only the kinds that can apply to it. The server
    // stays the authority and refuses a kind that does not fit.
    kind?: WorldKind
    // Where this record's own Members and offices section is, when it has one (an organization).
    membersHref?: string
}

const PLACE_KINDS: readonly WorldKind[] = ["place", "dungeon", "area"]

// A membership is one relationship record, but it is added and changed in the organization's
// Members and offices, where a change of office keeps its history. This is where that is.
function organizationOf(item: { participants: { entity_id: string; role: string }[] }): string | null {
    return item.participants.find((p) => p.role === "organization")?.entity_id ?? null
}

function membersPath(campaignId: string, organizationId: string): string {
    return `/app/${encodeURIComponent(campaignId)}/world/organization/${encodeURIComponent(organizationId)}?section=members`
}

const humanize = (code: string): string => code.replace(/_/g, " ")

// The relationships an entity takes part in, for editors: every edge (private and archived
// ones included), the editor for each, and a form to add another. Mounted on the world
// detail pages; players and observers get nothing and send no request.
export function RelationshipsPanel(props: Props) {
    if (!useCampaignCapability(props.campaignId, "canon.edit")) return null
    return <LoadedPanel {...props} />
}

function LoadedPanel({ campaignId, entityId, embedded, kind: recordKind, membersHref }: Props) {
    const [showArchived, setShowArchived] = useState(false)
    const [open, setOpen] = useState<string | null>(null)
    const list = useAuthoringResource<RelationshipList>(
        entityRelationshipsPath(campaignId, entityId, showArchived),
    )
    const options = useAuthoringResource<RelationshipOptions>(relationshipOptionsPath(campaignId))
    if (list.state.kind !== "ready" || options.state.kind !== "ready") {
        // Inside a staged section a missing body would read as "no relationships", so say why.
        if (embedded !== true) return null
        return list.state.kind === "loading" || options.state.kind === "loading" ? (
            <p role="status">Loading relationships…</p>
        ) : (
            <p role="alert">Relationships could not be loaded.</p>
        )
    }
    const items = list.state.data.items
    const loadedOptions = options.state.data
    return (
        <PanelFrame embedded={embedded} title="Relationships" headingId="relationships-heading">
            <p className="authoring-note">
                Relationships describe the story world. They never decide who can see or play a character; that is
                Character access, on the Access page. Memberships appear here with their office, but are added and
                changed in the organization&rsquo;s Members and offices, where a change of office is kept as history.
            </p>
            {items.length === 0 ? <p>No relationships recorded.</p> : null}
            <ul className="op-list">
                {items.map((item) => {
                    const organizationId = item.kind === "membership" ? organizationOf(item) : null
                    const manage =
                        organizationId === null
                            ? null
                            : {
                                  to:
                                      organizationId === entityId && membersHref !== undefined
                                          ? membersHref
                                          : membersPath(campaignId, organizationId),
                                  label:
                                      organizationId === entityId
                                          ? "Manage in Members and offices"
                                          : "Open organization members",
                              }
                    return (
                    <li key={item.relationship_id}>
                        {item.participants.map((p) => `${p.name} (${p.role_label})`).join(" and ")}:{" "}
                        {item.relationship_type_label}
                        {item.lifecycle_status !== "active" ? " (archived)" : ""}
                        {item.ended ? " (ended)" : ""}
                        {item.is_public === false ? " (private)" : ""}{" "}
                        {manage === null ? null : (
                            <Link to={manage.to} className="authoring-button">
                                {manage.label}
                            </Link>
                        )}{" "}
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
                    )
                })}
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
                    recordKind={recordKind}
                    membersHref={membersHref}
                    options={loadedOptions}
                    onCreated={() => void list.refetch()}
                />
            ) : null}
        </PanelFrame>
    )
}

function AddRelationship({
    campaignId,
    entityId,
    recordKind,
    membersHref,
    options: allOptions,
    onCreated,
}: {
    campaignId: string
    entityId: string
    recordKind?: WorldKind
    membersHref?: string
    options: RelationshipOptions
    onCreated: () => void
}) {
    // Membership is added in the organization's Members and offices (it needs an office, a rank and a
    // required start this form does not have), and a route joins two places, so offer it only on a place.
    const options: RelationshipOptions = {
        ...allOptions,
        kinds: allOptions.kinds.filter(
            (k) =>
                k.code !== "membership" &&
                (k.code !== "route" || recordKind === undefined || PLACE_KINDS.includes(recordKind)),
        ),
    }
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
    const [distance, setDistance] = useState("")
    const [duration, setDuration] = useState("")
    const [mode, setMode] = useState("")
    const [concealed, setConcealed] = useState("no")
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
        if (kind === "route") {
            if (distance.trim() !== "") body.distance_text = distance.trim()
            if (duration.trim() !== "") body.travel_time_text = duration.trim()
            if (mode.trim() !== "") body.travel_mode = mode.trim()
            body.is_hidden = concealed === "yes"
        }
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
            {recordKind === "organization" ? (
                <p className="authoring-note">
                    To add a member, use{" "}
                    {membersHref === undefined ? (
                        "Members and offices"
                    ) : (
                        <Link to={membersHref}>Members and offices</Link>
                    )}
                    .
                </p>
            ) : recordKind === "npc" || recordKind === "pc" || recordKind === "character" ? (
                <p className="authoring-note">
                    To make this character a member of an organization, open the organization&rsquo;s Members and
                    offices.
                </p>
            ) : null}
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
                        hint={
                            kind === "general"
                                ? "For containment use the place\u2019s parent; for an organization\u2019s parent body use its Parent organization field."
                                : undefined
                        }
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
                    {kind === "route" ? (
                        <>
                            <TextField id="rel-new-distance" label="Distance" value={distance} onChange={setDistance} />
                            <TextField id="rel-new-duration" label="Travel time" value={duration} onChange={setDuration} />
                            <TextField id="rel-new-mode" label="Mode of travel" value={mode} onChange={setMode} />
                            <SelectField
                                id="rel-new-concealed"
                                label="Concealed"
                                hint="Only editors see a concealed route."
                                value={concealed}
                                options={[
                                    { value: "no", label: "No" },
                                    { value: "yes", label: "Yes" },
                                ]}
                                onChange={setConcealed}
                            />
                        </>
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
