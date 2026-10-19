import { useRef, useState } from "react"
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
    RelationshipPairing,
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
    // What the record is, for the notes beside the Add form. Which types and roles it may take comes
    // from the server's pairings for this record, which stay the authority.
    kind?: WorldKind
    // Where this record's own Members and offices section is, when it has one (an organization).
    membersHref?: string
}

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
    const options = useAuthoringResource<RelationshipOptions>(
        relationshipOptionsPath(campaignId, entityId),
    )
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
    const { reload } = useSession()
    const announce = useAnnounce()
    const [picked, setPicked] = useState("")
    const [myRole, setMyRole] = useState("")
    const [other, setOther] = useState<ReferenceOption | null>(null)
    const [otherRole, setOtherRole] = useState("")
    const [cleared, setCleared] = useState(false)
    // The entity type of each counterpart the search returned, to check a choice against the roles.
    const foundTypes = useRef(new Map<string, string>())
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
    // What this record can take part in comes from the server's pairings for it. Membership is
    // added in the organization's Members and offices (it needs an office, a rank and a required
    // start this form does not have), so it is never offered here.
    const pairings = (allOptions.for_entity?.pairings ?? []).filter((p) => p.relationship_type !== "membership")
    const offered = new Set(pairings.map((p) => p.relationship_type))
    // The type decides the kind, so there is one choice. Each choice is identified by its kind and
    // type codes (stable, and distinct even if two kinds ever shared a type); labels that repeat
    // across kinds name their kind.
    const choices = allOptions.kinds.flatMap((k) =>
        k.types
            .filter((t) => offered.has(t))
            .map((t) => ({ value: `${k.code}/${t}`, type: t, kind: k, label: humanize(t) })),
    )
    const repeated = new Set(choices.map((c) => c.label).filter((l, i, all) => all.indexOf(l) !== i))
    const labelled = choices.map((c) => ({
        ...c,
        label: repeated.has(c.label) ? `${c.label} (${c.kind.label})` : c.label,
    }))
    // Exactly one valid type: it is chosen for the person and shown, not asked for.
    const only = labelled.length === 1 ? labelled[0]! : null
    const choice = only ?? labelled.find((c) => c.value === picked) ?? null
    const shape = choice?.kind
    const kind = shape?.code ?? ""
    const type = choice?.type ?? ""

    const roleLabels = new Map(
        (allOptions.relationship_types.find((t) => t.code === type)?.roles ?? []).map((r) => [r.code, r.label]),
    )
    const roleList = (codes: string[]) =>
        [...new Set(codes)].map((r) => ({ value: r, label: roleLabels.get(r) ?? humanize(r) }))
    const forType = (t: string) => pairings.filter((p) => p.relationship_type === t)
    const myRoles = (t: string) => [...new Set(forType(t).map((p) => p.my_role))]
    const otherRoles = (t: string, mine: string) => [
        ...new Set(forType(t).filter((p) => mine === "" || p.my_role === mine).map((p) => p.other_role)),
    ]
    // A role that is not offered is not held: a single remaining role is the role.
    const settled = (current: string, offeredRoles: string[]) =>
        offeredRoles.length === 1 ? offeredRoles[0]! : offeredRoles.includes(current) ? current : ""
    const myRoleValue = settled(myRole, myRoles(type))
    const otherRoleValue = settled(otherRole, otherRoles(type, myRoleValue))
    const matching = (t: string, mine: string, theirs: string): RelationshipPairing[] =>
        forType(t).filter((p) => (mine === "" || p.my_role === mine) && (theirs === "" || p.other_role === theirs))
    const allowedTypes = (t: string, mine: string, theirs: string): string[] => [
        ...new Set(matching(t, mine, theirs).flatMap((p) => p.other_entity_type_codes)),
    ]
    const allowed = allowedTypes(type, myRoleValue, otherRoleValue)

    // Clear the counterpart when the new choice means it cannot take the other role.
    function reconcile(nextType: string, nextMine: string, nextTheirs: string) {
        const mine = settled(nextMine, myRoles(nextType))
        const theirs = settled(nextTheirs, otherRoles(nextType, mine))
        if (other !== null) {
            const kindOfOther = foundTypes.current.get(other.id) ?? ""
            if (!allowedTypes(nextType, mine, theirs).includes(kindOfOther)) {
                setOther(null)
                setCleared(true)
            }
        }
    }

    function choose(next: string) {
        const nextChoice = labelled.find((c) => c.value === next)
        const nextKind = nextChoice?.kind.code ?? ""
        setCleared(false)
        if (nextKind !== kind) {
            // A different kind has its own roles and fields: nothing from the old one carries over.
            setMyRole("")
            setOtherRole("")
            setUnit("")
            setTitle("")
            setShare("")
            setIsPublic("yes")
            setTerms("")
            setDistance("")
            setDuration("")
            setMode("")
            setConcealed("no")
            setProblem(null)
            if (nextChoice !== undefined) reconcile(nextChoice.type, "", "")
        } else if (nextChoice !== undefined) {
            const nextMine = myRoles(nextChoice.type).includes(myRoleValue) ? myRoleValue : ""
            setMyRole(nextMine)
            const nextTheirs = otherRoles(nextChoice.type, nextMine).includes(otherRoleValue) ? otherRoleValue : ""
            setOtherRole(nextTheirs)
            reconcile(nextChoice.type, nextMine, nextTheirs)
        }
        setPicked(next)
    }

    function chooseMine(next: string) {
        setCleared(false)
        setMyRole(next)
        const theirs = otherRoles(type, next).includes(otherRoleValue) ? otherRoleValue : ""
        setOtherRole(theirs)
        reconcile(type, next, theirs)
    }

    function chooseTheirs(next: string) {
        setCleared(false)
        setOtherRole(next)
        reconcile(type, myRoleValue, next)
    }

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
        // One more than shown, so leaving this record out never shortens the list.
        const page = await fetchWorldEntities(
            campaignId,
            { category: null, query, limit: 11, entityTypes: allowed },
            signal,
        )
        return page.items
            .filter((item) => item.entity_id !== entityId)
            .slice(0, 10)
            .map((item) => {
                foundTypes.current.set(item.entity_id, item.entity_type_code)
                return { id: item.entity_id, label: item.name, detail: humanize(item.entity_type_code) }
            })
    }

    function submit() {
        if (shape === undefined || type === "" || myRoleValue === "" || otherRoleValue === "" || other === null) {
            setProblem("Choose the type, both roles and the other participant.")
            return
        }
        if (!allowedTypes(type, myRoleValue, otherRoleValue).includes(foundTypes.current.get(other.id) ?? "")) {
            setProblem("The other participant cannot take that role in this type of relationship.")
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
                { entity_id: entityId, role: myRoleValue },
                { entity_id: other.id, role: otherRoleValue },
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
            {labelled.length === 0 ? (
                <p className="authoring-note" role="status">
                    No relationship types are available for this record, so a relationship cannot be added here.
                </p>
            ) : only !== null ? (
                <TextField
                    id="rel-new-type"
                    label="Type"
                    hint="The only type available for this record."
                    value={only.label}
                    onChange={() => undefined}
                    readOnly
                />
            ) : (
                <SelectField
                    id="rel-new-type"
                    label="Type"
                    hint={
                        type === "parent_of"
                            ? "For containment use the place\u2019s parent; for an organization\u2019s parent body use its Parent organization field."
                            : undefined
                    }
                    value={choice?.value ?? ""}
                    placeholder="Choose a type"
                    options={labelled.map((c) => ({ value: c.value, label: c.label, group: c.kind.label }))}
                    onChange={choose}
                />
            )}
            {shape !== undefined ? (
                <>
                    <RoleField
                        id="rel-new-my-role"
                        label="This record is the"
                        value={myRoleValue}
                        roles={roleList(myRoles(type))}
                        onChange={chooseMine}
                    />
                    {cleared ? (
                        <p className="authoring-note" role="status">
                            The other participant was cleared because it cannot take that role.
                        </p>
                    ) : null}
                    <ReferenceCombobox
                        id="rel-new-other"
                        label="Other participant"
                        value={other}
                        onChange={(next) => {
                            setCleared(false)
                            setOther(next)
                        }}
                        search={searchOthers}
                        searchKey={`${type}/${myRoleValue}/${otherRoleValue}`}
                        error={problem}
                        placeholder="Search"
                    />
                    <RoleField
                        id="rel-new-other-role"
                        label="The other participant is the"
                        value={otherRoleValue}
                        roles={roleList(otherRoles(type, myRoleValue))}
                        onChange={chooseTheirs}
                    />
                    <TextAreaField
                        id="rel-new-description"
                        label="Description"
                        value={description}
                        onChange={setDescription}
                        maxLength={allOptions.limits.text_max_length}
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

// A role choice. When the type leaves exactly one role, it is shown, not asked for.
function RoleField({
    id,
    label,
    value,
    roles,
    onChange,
}: {
    id: string
    label: string
    value: string
    roles: { value: string; label: string }[]
    onChange: (value: string) => void
}) {
    if (roles.length === 1) {
        return (
            <TextField
                id={id}
                label={label}
                hint="The only role available."
                value={roles[0]!.label}
                onChange={() => undefined}
                readOnly
            />
        )
    }
    return (
        <SelectField
            id={id}
            label={label}
            value={value}
            placeholder="Choose a role"
            options={roles}
            onChange={onChange}
        />
    )
}
