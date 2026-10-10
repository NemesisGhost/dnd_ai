import { useId } from "react"
import type { ReactNode } from "react"
import { Link } from "react-router"
import { previewPerspectivesPath } from "../../api/knowledgePreview"
import { useSession } from "../../context/SessionContext"
import { useAccessOverview } from "../../hooks/useAccessOverview"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import type { PreviewPerspectives } from "../../types/knowledgePreview"
import { canPreviewAudience } from "../../utils/canPreviewAudience"
import { memberPreviewPath, memberPreviewSearch } from "../../utils/memberPreviewContext"
import type { MemberPreviewContext } from "../../utils/memberPreviewContext"

// What the pages below the shell may rely on: a member the server resolved, and a character and
// party that are both among that member's own perspectives.
export interface ReadyMemberPreview {
    membershipId: string
    memberName: string
    characterId: string | null
    characterName: string | null
    partyId: string | null
    partyName: string | null
}

interface Props {
    campaignId: string
    context: MemberPreviewContext
    // The collection lets the person choose the member and perspective; a claim only shows them.
    mode: "collection" | "claim"
    onContextChange?: (next: Partial<MemberPreviewContext>) => void
    children: (ready: ReadyMemberPreview) => ReactNode
}

const knowledgePath = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}/knowledge`

// The Knowledge "Member preview" workspace frame: who may use it, the member and perspective
// selection, the persistent "Previewing as" banner, and the rule that nothing is shown until the
// selection is valid. It never fetches Knowledge itself and never falls back to the signed-in
// person's own (unrestricted) data: its children render only for a validated selection, and every
// request they make is the server's preview projection for that member.
export function MemberPreviewShell({ campaignId, context, mode, onContextChange, children }: Props) {
    const { state } = useSession()
    const permitted = canPreviewAudience(state, campaignId)
    const collection = mode === "collection"

    const crumbs = (
        <nav aria-label="Breadcrumb" className="authoring-page__breadcrumb">
            <ol className="session-run__breadcrumb">
                <li>
                    <Link to={knowledgePath(campaignId)}>Knowledge</Link>
                </li>
                {collection ? (
                    <li aria-current="page">Member preview</li>
                ) : (
                    <>
                        <li>
                            <Link to={`${memberPreviewPath(campaignId)}${memberPreviewSearch({ ...context, cursor: context.cursor })}`}>
                                Member preview
                            </Link>
                        </li>
                        <li aria-current="page">Claim</li>
                    </>
                )}
            </ol>
        </nav>
    )

    return (
        <section className="authoring-page member-preview" aria-labelledby="member-preview-heading">
            {crumbs}
            <h1 id="member-preview-heading">Member preview</h1>
            {permitted ? (
                <PermittedShell
                    campaignId={campaignId}
                    context={context}
                    collection={collection}
                    onContextChange={onContextChange}
                >
                    {children}
                </PermittedShell>
            ) : (
                <>
                    <p role="alert">You do not have permission to preview what a member sees.</p>
                    <p>
                        <Link to={knowledgePath(campaignId)}>Return to Knowledge</Link>
                    </p>
                </>
            )}
        </section>
    )
}

function PermittedShell({
    campaignId,
    context,
    collection,
    onContextChange,
    children,
}: Omit<Props, "mode"> & { collection: boolean }) {
    const overview = useAccessOverview(campaignId)
    const memberSelectId = useId()
    const characterSelectId = useId()
    const partySelectId = useId()
    const selectedMember = context.member
    const members =
        overview.state.status === "success"
            ? overview.state.overview.members.filter((m) => m.status_code === "active" && m.account_is_active)
            : []
    const member = members.find((m) => m.campaign_membership_id === selectedMember) ?? null
    // Perspectives are requested only for a member this campaign actually lists.
    const perspectives = useAuthoringResource<PreviewPerspectives>(
        member === null ? null : previewPerspectivesPath(campaignId, member.campaign_membership_id),
    )

    const back = (
        <p>
            <Link to={knowledgePath(campaignId)}>Return to Knowledge</Link>
        </p>
    )

    if (overview.state.status === "loading") return <p role="status">Loading campaign members…</p>
    if (overview.state.status === "unavailable") {
        return (
            <>
                <p role="alert">The member list is not available, so there is nobody to preview.</p>
                {back}
            </>
        )
    }
    if (overview.state.status === "error") {
        return (
            <>
                <p role="alert">The campaign members could not be loaded.</p>
                <button type="button" className="authoring-button" onClick={overview.retry}>
                    Try again
                </button>
            </>
        )
    }

    const memberSelector = collection ? (
        <div className="knowledge-page__field">
            <label htmlFor={memberSelectId}>Member</label>
            <select
                id={memberSelectId}
                value={member?.campaign_membership_id ?? ""}
                onChange={(event) => {
                    const value = event.currentTarget.value
                    // A new member never inherits the previous member's character, party or page.
                    onContextChange?.({ member: value === "" ? null : value, characterId: null, partyId: null, cursor: null })
                }}
            >
                <option value="">Choose a member</option>
                {members.map((m) => (
                    <option key={m.campaign_membership_id} value={m.campaign_membership_id}>
                        {m.display_name}
                    </option>
                ))}
            </select>
        </div>
    ) : null

    const explain = (
        <p className="authoring-note">
            This workspace is read-only. It shows what the chosen member&apos;s own request would return; nothing here
            changes the claim, its sources, its status or who knows it.
        </p>
    )

    if (selectedMember === null) {
        return (
            <>
                {explain}
                <section className="member-preview__empty" aria-label="Choose a member">
                    <h2>Choose a member to preview</h2>
                    <p>
                        Pick a campaign member to see the Knowledge they can open, as they would see it. Until you do, no
                        Knowledge is shown here.
                    </p>
                    {collection ? <div className="knowledge-page__filters">{memberSelector}</div> : null}
                </section>
                {back}
            </>
        )
    }

    const problem = (message: string) => (
        <>
            {explain}
            <div className="knowledge-page__filters">{memberSelector}</div>
            <p role="alert">{message}</p>
            {collection ? null : (
                <p>
                    <Link to={`${memberPreviewPath(campaignId)}${memberPreviewSearch(context)}`}>Back to Member preview</Link>
                </p>
            )}
            {back}
        </>
    )

    if (member === null) {
        return problem("That member cannot be previewed. Choose a member from the list.")
    }
    if (perspectives.state.kind === "loading") return <p role="status">Loading what {member.display_name} can choose…</p>
    if (perspectives.state.kind === "unavailable" || perspectives.state.kind === "denied") {
        return problem(`${member.display_name} cannot be previewed (no longer an active member, or not available).`)
    }
    if (perspectives.state.kind === "error") {
        return problem("The member's perspectives could not be loaded. Try again.")
    }

    const data = perspectives.state.data
    const character =
        context.characterId === null
            ? null
            : (data.character_perspectives.find((c) => c.character_id === context.characterId) ?? null)
    if (context.characterId !== null && character === null) {
        return problem(`That character is not one of ${data.display_name}'s perspectives. Choose another, or none.`)
    }
    const party =
        context.partyId === null || character === null
            ? null
            : (character.authorized_parties.find((p) => p.party_id === context.partyId) ?? null)
    if (context.partyId !== null && party === null) {
        return problem(
            `That party is not available to ${data.display_name}${character === null ? " without a character" : ` as ${character.character_name}`}. Choose another, or none.`,
        )
    }

    const ready: ReadyMemberPreview = {
        membershipId: member.campaign_membership_id,
        memberName: data.display_name,
        characterId: character?.character_id ?? null,
        characterName: character?.character_name ?? null,
        partyId: party?.party_id ?? null,
        partyName: party?.party_name ?? null,
    }
    const key = `${ready.membershipId}|${ready.characterId ?? ""}|${ready.partyId ?? ""}`

    return (
        <>
            <section className="member-preview__banner" aria-label="Preview context" role="region">
                <p className="member-preview__banner-title">
                    Previewing as <strong>{data.display_name}</strong>
                    {data.roles.length > 0 ? <span className="member-preview__roles"> ({data.roles.join(", ")})</span> : null}
                </p>
                <p className="member-preview__banner-perspective">
                    {character === null
                        ? "No character perspective: only what the member can see without one."
                        : `Character perspective: ${character.character_name}${party === null ? "" : `. Party perspective: ${party.party_name}`}.`}
                </p>
                <p className="authoring-note">
                    Read-only. Member access decides which claims {data.display_name} may open. The character and party are
                    fictional perspectives: they decide what that character or party knows, and are offered only when the
                    member may use them.
                </p>
                <p>
                    <Link to={knowledgePath(campaignId)}>Return to Knowledge</Link>
                </p>
            </section>
            {collection ? (
                <div className="knowledge-page__filters" role="group" aria-label="Preview perspective">
                    {memberSelector}
                    <div className="knowledge-page__field">
                        <label htmlFor={characterSelectId}>Character to preview</label>
                        <select
                            id={characterSelectId}
                            value={character?.character_id ?? ""}
                            onChange={(event) => {
                                const value = event.currentTarget.value
                                onContextChange?.({ characterId: value === "" ? null : value, partyId: null, cursor: null })
                            }}
                        >
                            <option value="">No character perspective</option>
                            {data.character_perspectives.map((c) => (
                                <option key={c.character_id} value={c.character_id}>
                                    {c.character_name}
                                </option>
                            ))}
                        </select>
                    </div>
                    <div className="knowledge-page__field">
                        <label htmlFor={partySelectId}>Party to preview</label>
                        <select
                            id={partySelectId}
                            value={party?.party_id ?? ""}
                            disabled={character === null || character.authorized_parties.length === 0}
                            onChange={(event) => {
                                const value = event.currentTarget.value
                                onContextChange?.({ partyId: value === "" ? null : value, cursor: null })
                            }}
                        >
                            <option value="">
                                {character === null
                                    ? "Choose a character first"
                                    : character.authorized_parties.length === 0
                                      ? "No party available"
                                      : "All parties"}
                            </option>
                            {(character?.authorized_parties ?? []).map((p) => (
                                <option key={p.party_id} value={p.party_id}>
                                    {p.party_name}
                                </option>
                            ))}
                        </select>
                    </div>
                </div>
            ) : null}
            <div key={key}>{children(ready)}</div>
        </>
    )
}
