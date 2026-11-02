import { Link, useParams, useSearchParams } from "react-router"
import { previewKnowledgeDetailPath } from "../api/knowledgePreview"
import { MemberPreviewShell } from "../components/knowledge/MemberPreviewShell"
import type { ReadyMemberPreview } from "../components/knowledge/MemberPreviewShell"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { KnowledgeDetail } from "../types/knowledge"
import { KnowledgeDetailsPanel } from "../components/knowledge/KnowledgeDetailsPanel"
import { characterKnowledgeOf } from "../utils/characterKnowledge"
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
    const known = characterKnowledgeOf(item)
    const hasBlock = item.character_knowledge !== undefined

    // The server says how the character knows the claim; the label follows that path rather than
    // the selection, so a direct record is never labelled as the party's (or the reverse). A
    // payload without a path keeps the selection-based wording.
    const partyKnowledge = ready.partyId !== null
    const perspectiveName = partyKnowledge ? (ready.partyName ?? "the party") : (ready.characterName ?? "the character")
    const characterLabel = `Character knowledge: ${ready.characterName ?? "the character"}`
    const perspectiveLabel =
        ready.characterId === null
            ? "Perspective knowledge"
            : known?.path === "character" || (known === null && hasBlock)
              ? characterLabel
              : known?.path === "party"
                ? partyKnowledge
                    ? `Party knowledge: ${ready.partyName ?? "the party"}`
                    : "Party knowledge"
                : known?.path === "public"
                  ? "Public knowledge"
                  : partyKnowledge
                    ? `Party knowledge: ${perspectiveName}`
                    : characterLabel
    const hasCanonicalFacts = item.truth_status_code != null || item.sensitivity != null

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
            {hasCanonicalFacts ? (
                <dl className="authoring-fact-list">
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
            ) : null}
            <KnowledgeDetailsPanel
                kindCode={item.knowledge_type_code}
                known={ready.characterId === null ? undefined : (known ?? (hasBlock ? null : { path: null, facts: [] }))}
                headingLevel={3}
                perspective={ready.characterId === null ? null : perspectiveLabel}
                noPerspectiveNote="No character or party perspective is selected, so no perspective-specific knowledge is shown."
                noKnowledgeNote={`${ready.characterName ?? "The selected character"} has no recorded knowledge of this claim.`}
                neutralNote={`This projection includes no awareness, confidence or sharing details for ${perspectiveName}.`}
            />
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
