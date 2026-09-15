import {
    useCallback,
    useEffect,
    useState,
} from "react"
import {
    CampaignSummaryRequestError,
    fetchCampaignSummary,
} from "../api/campaignSummary"
import { useSession } from "../context/SessionContext"
import type { CampaignSummary } from "../types/campaignSummary"

export type CampaignSummaryState =
    | {
        status: "loading"
    }
    | {
        status: "success"
        summary: CampaignSummary
    }
    | {
        status: "unavailable"
    }
    | {
        status: "error"
        error: Error
    }

export interface UseCampaignSummaryResult {
    state: CampaignSummaryState
    retry: () => void
}

const initialState: CampaignSummaryState = {
    status: "loading",
}

export function useCampaignSummary(
    campaignId: string,
): UseCampaignSummaryResult {
    const { reload: reloadSession } = useSession()

    const [state, setState] =
        useState<CampaignSummaryState>(initialState)

    const [requestVersion, setRequestVersion] =
        useState(0)

    const retry = useCallback(() => {
        setState({
            status: "loading",
        })

        setRequestVersion(
            (currentVersion) => currentVersion + 1,
        )
    }, [])

    useEffect(() => {
        const controller = new AbortController()

        void fetchCampaignSummary(
            campaignId,
            controller.signal,
        )
            .then((summary) => {
                if (controller.signal.aborted) {
                    return
                }

                setState({
                    status: "success",
                    summary,
                })
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) {
                    return
                }

                if (
                    cause instanceof CampaignSummaryRequestError
                ) {
                    if (cause.status === 401) {
                        setState({
                            status: "loading",
                        })

                        reloadSession()
                        return
                    }

                    if (
                        cause.status === 403 ||
                        cause.status === 404
                    ) {
                        setState({
                            status: "unavailable",
                        })
                        return
                    }
                }

                const error =
                    cause instanceof Error
                        ? cause
                        : new Error(
                            "Campaign summary request failed",
                        )

                setState({
                    status: "error",
                    error,
                })
            })

        return () => {
            controller.abort()
        }
    }, [
        campaignId,
        reloadSession,
        requestVersion,
    ])

    return {
        state,
        retry,
    }
}