import { useCallback, useEffect, useState } from "react"
import {
    CampaignInvitationsRequestError,
    fetchCampaignInvitations,
} from "../api/campaignInvitations"
import { useSession } from "../context/SessionContext"
import type { PendingCampaignInvitation } from "../types/campaignInvitations"

export type CampaignInvitationsState =
    | { status: "loading" }
    | { status: "success"; invitations: PendingCampaignInvitation[] }
    | { status: "denied" }
    | { status: "error"; error: unknown }

export interface UseCampaignInvitationsResult {
    state: CampaignInvitationsState
    retry: () => void
}

interface Snapshot {
    campaignId: string
    requestVersion: number
    state: CampaignInvitationsState
}

const initialState: CampaignInvitationsState = {
    status: "loading",
}

export function useCampaignInvitations(
    campaignId: string,
): UseCampaignInvitationsResult {
    const { reload } = useSession()
    const [requestVersion, setRequestVersion] = useState(0)
    const [snapshot, setSnapshot] = useState<Snapshot>(() => ({
        campaignId,
        requestVersion: 0,
        state: initialState,
    }))

    const retry = useCallback(() => {
        setRequestVersion((currentVersion) => currentVersion + 1)
    }, [])

    const state =
        snapshot.campaignId === campaignId &&
        snapshot.requestVersion === requestVersion
            ? snapshot.state
            : initialState

    useEffect(() => {
        const controller = new AbortController()

        void fetchCampaignInvitations(campaignId, controller.signal)
            .then((result) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    requestVersion,
                    state: {
                        status: "success",
                        invitations: result.invitations,
                    },
                })
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return
                }
                if (error instanceof DOMException && error.name === "AbortError") {
                    return
                }
                if (
                    error instanceof CampaignInvitationsRequestError &&
                    error.status === 401
                ) {
                    void reload()
                    return
                }
                if (
                    error instanceof CampaignInvitationsRequestError &&
                    (error.status === 403 || error.status === 404)
                ) {
                    setSnapshot({
                        campaignId,
                        requestVersion,
                        state: { status: "denied" },
                    })
                    return
                }

                setSnapshot({
                    campaignId,
                    requestVersion,
                    state: { status: "error", error },
                })
            })

        return () => {
            controller.abort()
        }
    }, [campaignId, reload, requestVersion])

    return { state, retry }
}