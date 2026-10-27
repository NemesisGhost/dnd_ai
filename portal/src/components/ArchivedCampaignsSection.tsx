import { useState } from "react"
import { reactivateCampaign, ARCHIVED_CAMPAIGNS_PATH } from "../api/campaignSettings"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useKept } from "../hooks/useKeptResource"
import { bootstrapRefreshOutcome } from "../utils/refreshOutcome"
import type { ArchivedCampaign, ArchivedCampaignListResponse } from "../types/campaignSettings"
import { useAnnounce } from "./authoring/announcer"
import { ConfirmDialog } from "./authoring/ConfirmDialog"
import { LifecycleBadge, MutationStatusMessage, SavedRefreshFailedNotice } from "./authoring/feedback"
import "./authoring/authoring.css"

// "Archived campaigns you manage" with Reactivate. Rendered only once the server returned at least
// one; a loading or failed list renders nothing, so the Campaigns page is unchanged for people with
// nothing archived. After a reactivation the page needs two reads to agree with the server (the
// bootstrap, which lists the campaign again, and this list); if either fails the campaign IS
// reactivated and the section says so instead of showing an unexplained stale list.
export function ArchivedCampaignsSection() {
    const { state, refetch } = useAuthoringResource<ArchivedCampaignListResponse>(ARCHIVED_CAMPAIGNS_PATH)
    const list = useKept(state, ARCHIVED_CAMPAIGNS_PATH)
    const { refresh, reload } = useSession()
    const announce = useAnnounce()
    const [target, setTarget] = useState<ArchivedCampaign | null>(null)
    const [dialogOpen, setDialogOpen] = useState(false)
    // Which follow-up read of the last confirmed reactivation has not succeeded yet.
    const [unread, setUnread] = useState({ bootstrap: false, list: false })
    const [retrying, setRetrying] = useState(false)

    const mutation = useAuthoringMutation<{ expected_row_version: number }, unknown>({
        scopeKey: `reactivate:${target?.campaign_id ?? "none"}`,
        ownsRefreshNotice: true,
        request: (body, ctx) => reactivateCampaign(target!.campaign_id, body, ctx),
        onSuccess: async () => {
            // Authoritative state first: the bootstrap lists the campaign again, then the archived
            // list drops it.
            const bootstrap = (await bootstrapRefreshOutcome(refresh)) === "failed"
            const reloaded = (await refetch()) !== "ok"
            setDialogOpen(false)
            if (bootstrap || reloaded) {
                setUnread({ bootstrap, list: reloaded })
                return "failed"
            }
            setTarget(null)
            announce("Campaign reactivated")
        },
    })
    const unrefreshed = mutation.status.kind === "confirmed"

    async function retryReads() {
        setRetrying(true)
        const bootstrap = unread.bootstrap ? (await bootstrapRefreshOutcome(refresh)) === "failed" : false
        const reloaded = unread.list ? (await refetch()) !== "ok" : false
        setRetrying(false)
        setUnread({ bootstrap, list: reloaded })
        if (!bootstrap && !reloaded) {
            setTarget(null)
            announce("Campaign reactivated")
        }
    }

    if (!unrefreshed && (list === null || list.items.length === 0)) {
        return null
    }
    const items = list?.items ?? []
    const error = mutation.status.kind === "error" ? mutation.status.error : null

    return (
        <section className="authoring-section" aria-labelledby="archived-campaigns-heading">
            <h2 id="archived-campaigns-heading">Archived campaigns you manage</h2>
            {unrefreshed ? (
                <SavedRefreshFailedNotice
                    done="Campaign reactivated."
                    what={unread.bootstrap ? "campaign list and menus" : "list of archived campaigns"}
                    onRetry={() => void retryReads()}
                    retrying={retrying}
                />
            ) : null}
            <ul className="authoring-list">
                {items.map((campaign) => (
                    <li className="authoring-list__item" key={campaign.campaign_id}>
                        <div>
                            <h3>{campaign.name}</h3>
                            <p className="authoring-field__hint">
                                {campaign.world_name} · {campaign.timeline_name}
                            </p>
                        </div>
                        <LifecycleBadge status="archived" />
                        <button
                            type="button"
                            className="authoring-button"
                            disabled={unrefreshed}
                            onClick={() => {
                                mutation.reset()
                                setTarget(campaign)
                                setDialogOpen(true)
                            }}
                        >
                            Reactivate {campaign.name}
                        </button>
                    </li>
                ))}
            </ul>
            <ConfirmDialog
                open={dialogOpen}
                title="Reactivate this campaign?"
                description="Members can open it again, exactly as it was when it was archived. Its world and timeline must be active."
                confirmLabel="Reactivate campaign"
                onConfirm={() =>
                    target !== null &&
                    mutation.submit({ expected_row_version: target.row_version })
                }
                onCancel={() => {
                    setDialogOpen(false)
                    setTarget(null)
                }}
                pending={mutation.status.kind === "pending"}
                error={
                    error === null ? null : (
                        <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                    )
                }
            />
        </section>
    )
}
