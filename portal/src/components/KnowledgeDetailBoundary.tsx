import { useEffect, useRef } from "react"
import type { ReactNode } from "react"
import { useSession } from "../context/SessionContext"
import { useKnowledgeDetail } from "../hooks/useKnowledgeDetail"
import { useBreadcrumbLabel } from "../navigation/BreadcrumbLabelContext"
import { resolveAuthorizedParties } from "../utils/authorizedParties"
import type { KnowledgeDetail } from "../types/knowledge"
import type { KnowledgeRefreshOutcome } from "../hooks/useKnowledgeDetail"
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
    children: (item: KnowledgeDetail, refresh: () => Promise<KnowledgeRefreshOutcome>) => ReactNode
}

export function KnowledgeDetailBoundary({
    campaignId,
    knowledgeItemId,
    characterId,
    partyId,
    onPartyRevoked,
    children,
}: KnowledgeDetailBoundaryProps) {
    const { state, retry, refresh, authority, refusedAfterWrite } = useKnowledgeDetail(
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

    // The item became unavailable on a re-read after a confirmed write: the write is still confirmed, in
    // words that say nothing about the record (a refusal never discloses what was there). Focus goes to the
    // heading once, and only if the control that held it has gone (the page that was saved from is replaced).
    const confirmedThenRefused = state.status === "unavailable" && refusedAfterWrite
    const terminalHeading = useRef<HTMLHeadingElement>(null)
    useEffect(() => {
        if (!confirmedThenRefused) return
        const focused = document.activeElement
        if (focused === null || focused === document.body) terminalHeading.current?.focus()
    }, [confirmedThenRefused])

    if (state.status === "loading") {
        return (
            <PlaceholderPage
                title="Loading knowledge"
                description="Loading the latest authorized knowledge."
            />
        )
    }

    if (state.status === "unavailable" && confirmedThenRefused) {
        return (
            <section className="placeholder-page" aria-labelledby="knowledge-unavailable-heading">
                <h1 id="knowledge-unavailable-heading" ref={terminalHeading} tabIndex={-1}>
                    Knowledge unavailable
                </h1>
                <p>The requested knowledge is not available.</p>
                <p>Your change was saved.</p>
            </section>
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
