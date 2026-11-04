import { Link } from "react-router"
import { TaskBreadcrumb } from "../navigation/TaskBreadcrumb"
import type { KnowledgeDetail } from "../../types/knowledge"
import { humanizeCode } from "../../utils/humanize"
import { LifecycleBadge } from "../authoring/feedback"
import { KnowledgeSubjectLink } from "../KnowledgeSubjectLink"
import type { ClaimGuidance } from "./claimStages"

const HEADING_MAX = 200

// The headline is the claim itself; a long statement is cut here and shown in full in the Claim
// section.
const headline = (statement: string): string =>
    statement.length > HEADING_MAX ? `${statement.slice(0, HEADING_MAX).trimEnd()}…` : statement

export interface HeaderStatus {
    canonStatus: string
    lifecycleStatus: string
    supersededBy: { entityId: string; name: string } | null
}

interface Props {
    campaignId: string
    item: KnowledgeDetail
    characterId: string | null
    partyId: string | null
    // Router state for the links to other records: the claim's own task, continued.
    linkState?: object
    // The Knowledge list, carrying the perspective.
    listHref: string
    // The actual record status, for people who can read it (editors). Stage navigation never
    // carries status: it lives here.
    status: HeaderStatus | null
    // Where the replacing claim is, when this one was superseded.
    replacementHref: string | null
    guidance: ClaimGuidance | null
    // Where the guidance leads; null when it has no destination the person can open.
    guidanceHref: string | null
    // Router state for the guidance link (the page's own section keeps the task; another record continues it).
    guidanceState?: object
    canEdit: boolean
}

// The always-visible top of the Knowledge claim page: where it is, the claim itself, what it is
// about, and the record's real status. Everything here is information or navigation; no lifecycle
// action lives in the header.
export function KnowledgeClaimHeader({
    campaignId,
    item,
    characterId,
    partyId,
    linkState,
    listHref,
    status,
    replacementHref,
    guidance,
    guidanceHref,
    guidanceState,
    canEdit,
}: Props) {
    return (
        <header className="knowledge-claim__header">
            {/* The task the claim was opened in; the Knowledge list is opened under the claim's perspective. */}
            <TaskBreadcrumb
                current="Claim"
                queries={{ "knowledge.list": listHref.includes("?") ? listHref.slice(listHref.indexOf("?")) : "" }}
            />
            <div className="knowledge-claim__headline">
                <h1 id="knowledge-claim-heading" className="knowledge-claim__title" tabIndex={-1}>
                    {headline(item.statement)}
                </h1>
                {status !== null ? (
                    <span className="knowledge-claim__status" role="group" aria-label="Record status">
                        <LifecycleBadge status={status.canonStatus} />
                        {status.lifecycleStatus === "archived" ? <LifecycleBadge status="archived" /> : null}
                    </span>
                ) : null}
            </div>
            <KnowledgeSubjectLink
                campaignId={campaignId}
                subject={item.subject}
                characterId={characterId}
                partyId={partyId}
                linkState={linkState}
                variant="claim"
                separateOpen={canEdit}
            />
            {status?.supersededBy != null ? (
                <p className="knowledge-claim__replaced" role="status">
                    {replacementHref !== null ? (
                        <>
                            Replaced by <Link to={replacementHref} state={linkState}>
                                {status.supersededBy.name}
                            </Link>.
                        </>
                    ) : (
                        <>Replaced by {status.supersededBy.name}.</>
                    )}
                </p>
            ) : null}
            {canEdit || guidance !== null ? (
                <div className="knowledge-claim__meta">
                    {/* Readers see the kind inside the Knowledge details panel, not here. */}
                    {canEdit ? <span>Kind: {humanizeCode(item.knowledge_type_code)}</span> : null}
                    {guidance !== null ? (
                        <span className="knowledge-claim__next">
                            Next:{" "}
                            {guidanceHref !== null ? <Link to={guidanceHref} state={guidanceState}>
                                    {guidance.text} ›
                                </Link> : guidance.text}
                        </span>
                    ) : null}
                </div>
            ) : null}
        </header>
    )
}
