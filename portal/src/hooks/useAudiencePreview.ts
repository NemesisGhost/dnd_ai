import { useCallback, useEffect, useState } from "react"
import { AudiencePreviewRequestError, fetchAudiencePreview } from "../api/audiencePreview"
import { useSession } from "../context/SessionContext"
import type { AudiencePreviewResourceType, AudiencePreviewResult } from "../types/audiencePreview"

export type AudiencePreviewState =
    | { status: "loading" }
    | { status: "success"; result: AudiencePreviewResult }
    | { status: "unavailable" }
    | { status: "error"; error: unknown }

export interface UseAudiencePreviewResult {
    state: AudiencePreviewState
    retry: () => void
}

interface AudiencePreviewSnapshot {
    campaignId: string
    campaignMembershipId: string
    resourceType: AudiencePreviewResourceType
    resourceId: string
    requestVersion: number
    state: AudiencePreviewState
}

const initialState: AudiencePreviewState = { status: "loading" }

// Mirrors useEffectiveAccess's own "never keep a prior request's result
// visible as current" snapshot pattern, keyed on all four request
// dimensions. The caller (AudiencePreviewPanel) is expected to mount this
// hook only while a member and a resource are both selected; unmounting —
// on close, or on either selection changing — is what actually clears the
// rendered preview from memory, per this checkpoint's own security
// invariant that protected content cannot outlive the preview target.
export function useAudiencePreview(
    campaignId: string,
    campaignMembershipId: string,
    resourceType: AudiencePreviewResourceType,
    resourceId: string,
): UseAudiencePreviewResult {
    const { reload } = useSession()

    const [requestVersion, setRequestVersion] = useState(0)

    const [snapshot, setSnapshot] = useState<AudiencePreviewSnapshot>(() => ({
        campaignId,
        campaignMembershipId,
        resourceType,
        resourceId,
        requestVersion: 0,
        state: initialState,
    }))

    const retry = useCallback(() => {
        setRequestVersion((currentVersion) => currentVersion + 1)
    }, [])

    const snapshotMatchesRequest =
        snapshot.campaignId === campaignId &&
        snapshot.campaignMembershipId === campaignMembershipId &&
        snapshot.resourceType === resourceType &&
        snapshot.resourceId === resourceId &&
        snapshot.requestVersion === requestVersion

    const state = snapshotMatchesRequest ? snapshot.state : initialState

    useEffect(() => {
        const controller = new AbortController()

        void fetchAudiencePreview(
            campaignId,
            campaignMembershipId,
            resourceType,
            resourceId,
            controller.signal,
        )
            .then((result) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    campaignMembershipId,
                    resourceType,
                    resourceId,
                    requestVersion,
                    state: { status: "success", result },
                })
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return
                }

                if (error instanceof DOMException && error.name === "AbortError") {
                    return
                }

                if (error instanceof AudiencePreviewRequestError && error.status === 401) {
                    void reload()
                    return
                }

                if (
                    error instanceof AudiencePreviewRequestError &&
                    (error.status === 403 || error.status === 404)
                ) {
                    setSnapshot({
                        campaignId,
                        campaignMembershipId,
                        resourceType,
                        resourceId,
                        requestVersion,
                        state: { status: "unavailable" },
                    })
                    return
                }

                setSnapshot({
                    campaignId,
                    campaignMembershipId,
                    resourceType,
                    resourceId,
                    requestVersion,
                    state: { status: "error", error },
                })
            })

        return () => {
            controller.abort()
        }
    }, [campaignId, campaignMembershipId, resourceType, resourceId, reload, requestVersion])

    return { state, retry }
}
