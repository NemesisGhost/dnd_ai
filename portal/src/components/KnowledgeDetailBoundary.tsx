import { useEffect } from "react"
import type { ReactNode } from "react"
import { useSession } from "../context/SessionContext"
import { useKnowledgeDetail } from "../hooks/useKnowledgeDetail"
import { useBreadcrumbLabel } from "../navigation/BreadcrumbLabelContext"
import { resolveAuthorizedParties } from "../utils/authorizedParties"
import type { KnowledgeDetail } from "../types/knowledge"
import type { RefetchOutcome } from "../hooks/useAuthoringResource"
import PlaceholderPage from "../pages/PlaceholderPage"

interface KnowledgeDetailBoundaryProps {
    campaignId: string
    knowledgeItemId: string
    characterId: string | null
    partyId: string | null
    // Called once a party-scoped not-found was rechecked against a refreshed bootstrap and that
    // party is no longer among the character's authorized parties: the page drops it from the
    // address, and the record is read again without it. Never called while the party is still
    // authorized (that stays a genuine "unavailable").
    onPartyRevoked?: (partyId: string) => void
    // `refresh` re-reads the detail without remounting anything below.
    children: (item: KnowledgeDetail, refresh: () => Promise<RefetchOutcome>) => ReactNode
}

export function KnowledgeDetailBoundary({
    campaignId,
    knowledgeItemId,
    characterId,
    partyId,
    onPartyRevoked,
    children,
}: KnowledgeDetailBoundaryProps) {
    const { state, retry, refresh, authority } = useKnowledgeDetail(
        campaignId,
        knowledgeItemId,
        characterId,
        partyId,
    )
    // The claim's statement (as the page's own heading shows it), from this authorized read, for the
    // breadcrumbs of the pages opened from it. An unavailable (403/404) answer drops it.
    useBreadcrumbLabel({
        route: "knowledge.detail",
        params: { campaignId, knowledgeItemId },
        name: state.status === "success" ? state.item.statement : undefined,
        denied: state.status === "unavailable",
        authority,
    })

    // With no session state to compare against (an isolated render), nothing is treated as revoked.
    const sessionState = useSession().state as ReturnType<typeof useSession>["state"] | undefined
    const authorized =
        sessionState === undefined
            ? []
            : resolveAuthorizedParties(sessionState, campaignId, characterId)
    const recheckedPartyId =
        state.status === "unavailable" ? (state.recheckedPartyId ?? null) : null
    const revoked =
        sessionState?.status === "authenticated" &&
        recheckedPartyId !== null &&
        recheckedPartyId === partyId &&
        !authorized.some((party) => party.party_id === recheckedPartyId)

    useEffect(() => {
        if (revoked && recheckedPartyId !== null) {
            onPartyRevoked?.(recheckedPartyId)
        }
    }, [revoked, recheckedPartyId, onPartyRevoked])

    if (state.status === "loading") {
        return (
            <PlaceholderPage
                title="Loading knowledge"
                description="Loading the latest authorized knowledge."
            />
        )
    }

    if (state.status === "unavailable") {
        return (
            <PlaceholderPage
                title="Knowledge unavailable"
                description="The requested knowledge is not available."
            />
        )
    }

    if (state.status === "error") {
        return (
            <section
                className="placeholder-page"
                aria-labelledby="knowledge-detail-error-heading"
            >
                <h1 id="knowledge-detail-error-heading">
                    Knowledge information unavailable
                </h1>

                <p>
                    The portal could not load the knowledge information.
                    Try again.
                </p>

                <button type="button" onClick={retry}>
                    Try again
                </button>
            </section>
        )
    }

    return <>{children(state.item, refresh)}</>
}
