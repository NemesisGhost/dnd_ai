import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react"
import {
    EligibleAccountRequestError,
    fetchEligibleCampaignAccount,
} from "../api/eligibleAccount"
import { useSession } from "../context/SessionContext"
import type { EligibleAccount } from "../types/eligibleAccount"

export type EligibleAccountLookupStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "found"; account: EligibleAccount }
    | { kind: "not_found" }
    | { kind: "denied" }
    | { kind: "error" }

export interface UseEligibleAccountLookupResult {
    status: EligibleAccountLookupStatus
    lookup: (loginName: string) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: EligibleAccountLookupStatus
}

const idleStatus: EligibleAccountLookupStatus = {
    kind: "idle",
}

// A manager-triggered, exact-match lookup (never a live/typeahead search —
// dnd_ai.queries.access_overview.find_eligible_campaign_account's own
// deliberate exact-match, non-directory design) for the Access page's
// "Add campaign member" account-selection step. `found`/`not_found` are
// both ordinary successful outcomes (200 with account: {...} or null) —
// distinguished here so the control can render each distinctly, never
// folded into a shared "success" the way the mutation hooks' `success`
// means "the requested change happened" (this is a read, not a mutation).
export function useEligibleAccountLookup(
    campaignId: string,
): UseEligibleAccountLookupResult {
    const { state: sessionState, reload } = useSession()
    const controllerRef =
        useRef<AbortController | null>(null)

    const [snapshot, setSnapshot] = useState<Snapshot>(
        () => ({ campaignId, status: idleStatus }),
    )

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [campaignId])

    const status =
        snapshot.campaignId === campaignId
            ? snapshot.status
            : idleStatus

    const lookup = useCallback(
        (loginName: string) => {
            if (sessionState.status !== "authenticated") {
                return
            }

            const requestCampaignId = campaignId
            const controller = new AbortController()
            controllerRef.current?.abort()
            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void fetchEligibleCampaignAccount(
                requestCampaignId,
                loginName,
                controller.signal,
            )
                .then((response) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    setSnapshot({
                        campaignId: requestCampaignId,
                        status:
                            response.account !== null
                                ? {
                                      kind: "found",
                                      account: response.account,
                                  }
                                : { kind: "not_found" },
                    })
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    if (
                        cause instanceof
                        EligibleAccountRequestError
                    ) {
                        if (cause.status === 401) {
                            setSnapshot({
                                campaignId: requestCampaignId,
                                status: idleStatus,
                            })
                            reload()
                            return
                        }
                        if (
                            cause.status === 403 ||
                            cause.status === 404
                        ) {
                            setSnapshot({
                                campaignId: requestCampaignId,
                                status: { kind: "denied" },
                            })
                            return
                        }
                    }

                    setSnapshot({
                        campaignId: requestCampaignId,
                        status: { kind: "error" },
                    })
                })
        },
        [sessionState, campaignId, reload],
    )

    const reset = useCallback(() => {
        controllerRef.current?.abort()
        setSnapshot({ campaignId, status: idleStatus })
    }, [campaignId])

    return { status, lookup, reset }
}
