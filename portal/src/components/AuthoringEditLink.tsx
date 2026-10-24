import { useEffect, useRef } from "react"
import { Link } from "react-router"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { describeBlockedReason } from "../utils/blockedReason"
import { authoringOf } from "../utils/recordAuthoring"
import type { RecordAuthoring } from "../utils/recordAuthoring"
import type { EditableView } from "./authoring/ContentEditPage"
import "./authoring/authoring.css"

interface AuthoringEditLinkProps {
    campaignId: string
    // The authoring read the editor would load, and the edit route it links to.
    viewPath: string
    editPath: string
    // Lowercase noun for copy: "location".
    noun: string
    // The audience-safe detail the page is showing. It carries the server's `authoring` fields
    // for this record, which decide whether editing is offered at all; when a lifecycle action
    // refreshes it, the authoring read is refreshed too so the link never outlives the state
    // that allowed it.
    detail: unknown
    // Router state to carry to the edit page (where the person came from, so Save and Cancel can
    // return there).
    linkState?: object
}

// The "Edit" entry point on a record's detail page. Players (no `canon.edit` in
// the bootstrap) mount nothing and send no request. For an editor, the record's own `authoring`
// fields say whether the definition is theirs to edit (shared canon needs the world Editor
// capability; campaign-originated records do not), and the authoring read is not even requested
// otherwise. Once it is, the server's `available_actions` decides whether editing is offered right
// now, and a blocked edit is explained rather than silently hidden.
export function AuthoringEditLink(props: AuthoringEditLinkProps) {
    const hasCanonEdit = useCampaignCapability(props.campaignId, "canon.edit")
    const authoring = authoringOf(props.detail as { authoring?: RecordAuthoring } | null)
    if (!hasCanonEdit) {
        return null
    }
    if (!authoring.can_edit) {
        // Shared canon belongs to the world: running this campaign does not confer the right to
        // change it (ADR 0020). Explain, rather than offer an edit the server would refuse.
        return (
            <p className="authoring-note">
                Editing shared world content requires the world Editor role. Ask the world owner.
            </p>
        )
    }
    return <LoadedLink {...props} />
}

function LoadedLink({ viewPath, editPath, noun, detail, linkState }: AuthoringEditLinkProps) {
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
                <Link className="authoring-button" to={editPath} state={linkState}>
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
