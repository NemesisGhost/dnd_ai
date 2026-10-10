import { Link, useParams, useSearchParams } from "react-router"
import { previewKnowledgeDetailPath } from "../api/knowledgePreview"
import { MemberPreviewShell } from "../components/knowledge/MemberPreviewShell"
import type { ReadyMemberPreview } from "../components/knowledge/MemberPreviewShell"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { KnowledgeDetail } from "../types/knowledge"
import { humanizeCode } from "../utils/humanize"
import { memberPreviewPath, memberPreviewSearch, parseMemberPreviewContext } from "../utils/memberPreviewContext"
import type { MemberPreviewContext } from "../utils/memberPreviewContext"
import PlaceholderPage from "./PlaceholderPage"

// /app/:campaignId/knowledge/member-preview/:knowledgeItemId: one claim exactly as the previewed
// member's own request returns it. Read-only by construction: the response is the server's
// projection for that member (a field they may not see is absent, not hidden), and this page has
// no form, source, lifecycle or knowledge-management control. The subject is shown as text
// because opening it would leave the preview for the signed-in person's own, unrestricted view.
function PreviewClaim({
    campaignId,
    knowledgeItemId,
    ready,
    context,
}: {
    campaignId: string
    knowledgeItemId: string
    ready: ReadyMemberPreview
    context: MemberPreviewContext
}) {
    const detail = useAuthoringResource<KnowledgeDetail>(
        previewKnowledgeDetailPath(campaignId, ready.membershipId, knowledgeItemId, ready.characterId, ready.partyId),
    )
    const state = detail.state
    const back = (
        <p>
            <Link to={`${memberPreviewPath(campaignId)}${memberPreviewSearch(context)}`}>Back to Member preview</Link>
        </p>
    )

    if (state.kind === "loading") return <p role="status">Loading this claim as {ready.memberName} sees it…</p>
    if (state.kind === "unavailable" || state.kind === "denied") {
        return (
            <>
                <p role="alert">
                    {ready.memberName} cannot see this claim
                    {ready.characterId === null ? "" : " from this perspective"}. It may be unpublished, not yet known to
                    them, or outside what they may open.
                </p>
                {back}
            </>
        )
    }
    if (state.kind === "error") {
        return (
            <>
                <p role="alert">The preview could not be loaded.</p>
                <button type="button" className="authoring-button" onClick={() => void detail.refetch()}>
                    Try again
                </button>
                {back}
            </>
        )
    }

    const item = state.data
    const recorded = [
        item.awareness_level != null ? { label: "Awareness", value: humanizeCode(item.awareness_level) } : null,
        item.confidence != null ? { label: "Confidence", value: `${item.confidence}%` } : null,
        item.willing_to_share != null ? { label: "Willing to share", value: item.willing_to_share ? "Yes" : "No" } : null,
    ].filter((entry) => entry !== null)

    // With a party selected the server projects these values from the party's knowledge record,
    // otherwise from the character's; null values only mean the projection did not include them.
    const partyKnowledge = ready.partyId !== null
    const perspectiveName = partyKnowledge ? (ready.partyName ?? "the party") : (ready.characterName ?? "the character")
    const knowledgeHeading = partyKnowledge
        ? `Party knowledge: ${perspectiveName}`
        : ready.characterId !== null
          ? `Character knowledge: ${perspectiveName}`
          : "Perspective knowledge"

    return (
        <article aria-labelledby="member-preview-claim-heading">
            <h2 id="member-preview-claim-heading" className="member-preview__claim">
                {item.statement}
            </h2>
            {item.subject !== null && item.subject !== undefined ? (
                <p>
                    About: <strong>{item.subject.name}</strong>{" "}
                    <span className="knowledge-about__type">{humanizeCode(item.subject.entity_type_code)}</span>
                </p>
            ) : null}
            <dl className="authoring-fact-list">
                <dt>Kind</dt>
                <dd>{humanizeCode(item.knowledge_type_code)}</dd>
                {item.truth_status_code != null ? (
                    <>
                        <dt>Truth</dt>
                        <dd>{humanizeCode(item.truth_status_code)}</dd>
                    </>
                ) : null}
                {item.sensitivity != null ? (
                    <>
                        <dt>Sensitivity</dt>
                        <dd>{humanizeCode(item.sensitivity)}</dd>
                    </>
                ) : null}
            </dl>
            <section aria-labelledby="member-preview-knowledge-heading">
                <h3 id="member-preview-knowledge-heading">{knowledgeHeading}</h3>
                {ready.characterId === null ? (
                    <p className="authoring-note">
                        No character or party perspective is selected, so no perspective-specific knowledge is shown.
                    </p>
                ) : recorded.length === 0 ? (
                    <p className="authoring-note">
                        This projection includes no awareness, confidence or sharing details for {perspectiveName}.
                    </p>
                ) : (
                    <dl className="authoring-fact-list">
                        {recorded.map((entry) => (
                            <div key={entry.label}>
                                <dt>{entry.label}</dt>
                                <dd>{entry.value}</dd>
                            </div>
                        ))}
                    </dl>
                )}
            </section>
            {back}
        </article>
    )
}

function MemberPreviewClaim({ campaignId, knowledgeItemId }: { campaignId: string; knowledgeItemId: string }) {
    const [params] = useSearchParams()
    const context = parseMemberPreviewContext(params)
    return (
        <MemberPreviewShell campaignId={campaignId} context={context} mode="claim">
            {(ready) => (
                <PreviewClaim campaignId={campaignId} knowledgeItemId={knowledgeItemId} ready={ready} context={context} />
            )}
        </MemberPreviewShell>
    )
}

export function KnowledgeMemberPreviewClaimPage() {
    const { campaignId, knowledgeItemId } = useParams<{ campaignId: string; knowledgeItemId: string }>()
    if (campaignId === undefined || knowledgeItemId === undefined) {
        return <PlaceholderPage title="Knowledge unavailable" description="The requested knowledge is not available." />
    }
    // Remounting on a campaign or claim change keeps one claim from showing under another's address.
    return (
        <MemberPreviewClaim
            key={`${campaignId}/${knowledgeItemId}`}
            campaignId={campaignId}
            knowledgeItemId={knowledgeItemId}
        />
    )
}
