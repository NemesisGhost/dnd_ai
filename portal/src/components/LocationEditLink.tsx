import { useEffect, useRef } from "react"
import { Link } from "react-router"
import { locationAuthoringPath } from "../api/locationAuthoring"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import type { LocationAuthoringView } from "../types/locationAuthoring"
import { describeBlockedReason } from "../utils/blockedReason"
import "./authoring/authoring.css"

interface LocationEditLinkProps {
    campaignId: string
    locationId: string
    // The audience-safe detail the page is showing. When a lifecycle action
    // refreshes it, the authoring read is refreshed too so the link never
    // outlives the state that allowed it.
    detail: unknown
}

// The "Edit" entry point on a location's detail page. Players (no `canon.edit`
// in the bootstrap) mount nothing and send no request; for an editor the server's
// `available_actions` decides whether editing is offered, and a blocked edit is
// explained rather than silently hidden.
export function LocationEditLink({ campaignId, locationId, detail }: LocationEditLinkProps) {
    if (!useCampaignCapability(campaignId, "canon.edit")) {
        return null
    }
    return <LoadedLink campaignId={campaignId} locationId={locationId} detail={detail} />
}

function LoadedLink({ campaignId, locationId, detail }: LocationEditLinkProps) {
    const { state, refetch } = useAuthoringResource<LocationAuthoringView>(
        locationAuthoringPath(campaignId, locationId),
    )
    const firstRender = useRef(true)
    useEffect(() => {
        if (firstRender.current) {
            firstRender.current = false
            return
        }
        void refetch()
    }, [detail, refetch])

    if (state.kind !== "ready") {
        return null
    }
    if (state.data.available_actions.includes("update")) {
        return (
            <p className="authoring-page__actions-row">
                <Link
                    className="authoring-button"
                    to={`/app/${encodeURIComponent(campaignId)}/world/location/${encodeURIComponent(locationId)}/edit`}
                >
                    Edit location
                </Link>
            </p>
        )
    }
    const reason = state.data.blocked_actions.find((b) => b.action === "update")?.reason
    return reason === undefined ? null : (
        <p className="authoring-note">Editing unavailable: {describeBlockedReason(reason)}</p>
    )
}
