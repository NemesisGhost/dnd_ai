import { useEffect, useRef } from "react"
import { Link } from "react-router"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { useWorldCapability, WORLD_CANON_EDIT } from "../hooks/useWorldCapability"
import { describeBlockedReason } from "../utils/blockedReason"
import type { EditableView } from "./authoring/ContentEditPage"
import "./authoring/authoring.css"

interface AuthoringEditLinkProps {
    campaignId: string
    // The authoring read the editor would load, and the edit route it links to.
    viewPath: string
    editPath: string
    // Lowercase noun for copy: "location".
    noun: string
    // The audience-safe detail the page is showing. When a lifecycle action
    // refreshes it, the authoring read is refreshed too so the link never
    // outlives the state that allowed it.
    detail: unknown
}

// The "Edit" entry point on a record's detail page. Players (no `canon.edit` in
// the bootstrap) mount nothing and send no request; for an editor the server's
// `available_actions` decides whether editing is offered, and a blocked edit is
// explained rather than silently hidden.
export function AuthoringEditLink(props: AuthoringEditLinkProps) {
    const hasCanonEdit = useCampaignCapability(props.campaignId, "canon.edit")
    const hasWorldEdit = useWorldCapability(props.campaignId, WORLD_CANON_EDIT)
    if (!hasCanonEdit) {
        return null
    }
    if (!hasWorldEdit) {
        // Shared canon belongs to the world: running this campaign does not confer the right to
        // change it (ADR 0020). Explain, rather than offer an edit the server would refuse.
        return <p className="authoring-note">Editing shared world content requires the world Editor role. Ask the world owner.</p>
    }
    return <LoadedLink {...props} />
}

function LoadedLink({ viewPath, editPath, noun, detail }: AuthoringEditLinkProps) {
    const { state, refetch } = useAuthoringResource<EditableView>(viewPath)
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
                <Link className="authoring-button" to={editPath}>
                    Edit {noun}
                </Link>
            </p>
        )
    }
    const reason = state.data.blocked_actions.find((b) => b.action === "update")?.reason
    return reason === undefined ? null : (
        <p className="authoring-note">Editing unavailable: {describeBlockedReason(reason)}</p>
    )
}
