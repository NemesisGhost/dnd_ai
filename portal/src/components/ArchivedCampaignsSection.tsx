import { useState } from "react"
import { reactivateCampaign, ARCHIVED_CAMPAIGNS_PATH } from "../api/campaignSettings"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { ArchivedCampaign, ArchivedCampaignListResponse } from "../types/campaignSettings"
import { useAnnounce } from "./authoring/announcer"
import { ConfirmDialog } from "./authoring/ConfirmDialog"
import { LifecycleBadge, MutationStatusMessage } from "./authoring/feedback"
import "./authoring/authoring.css"

// "Archived campaigns you manage" with Reactivate. Rendered only once the
// server returned at least one; a loading or failed list renders nothing, so
// the Campaigns page is unchanged for people with nothing archived.
export function ArchivedCampaignsSection() {
    const { state, refetch } = useAuthoringResource<ArchivedCampaignListResponse>(
        ARCHIVED_CAMPAIGNS_PATH,
    )
    const { refresh, reload } = useSession()
    const announce = useAnnounce()
    const [target, setTarget] = useState<ArchivedCampaign | null>(null)

    const mutation = useAuthoringMutation<{ expected_row_version: number }, unknown>({
        scopeKey: `reactivate:${target?.campaign_id ?? "none"}`,
        request: (body, ctx) => reactivateCampaign(target!.campaign_id, body, ctx),
        onSuccess: async () => {
            // Authoritative state first: the bootstrap lists the campaign again,
            // then the archived list drops it.
            await refresh().catch(() => undefined)
            await refetch()
            setTarget(null)
            announce("Campaign reactivated")
        },
    })

    if (state.kind !== "ready" || state.data.items.length === 0) {
        return null
    }
    const error = mutation.status.kind === "error" ? mutation.status.error : null

    return (
        <section className="authoring-section" aria-labelledby="archived-campaigns-heading">
            <h2 id="archived-campaigns-heading">Archived campaigns you manage</h2>
            <ul className="authoring-list">
                {state.data.items.map((campaign) => (
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
                            onClick={() => {
                                mutation.reset()
                                setTarget(campaign)
                            }}
                        >
                            Reactivate {campaign.name}
                        </button>
                    </li>
                ))}
            </ul>
            <ConfirmDialog
                open={target !== null}
                title="Reactivate this campaign?"
                description="Members can open it again, exactly as it was when it was archived. Its world and timeline must be active."
                confirmLabel="Reactivate campaign"
                onConfirm={() =>
                    target !== null &&
                    mutation.submit({ expected_row_version: target.row_version })
                }
                onCancel={() => setTarget(null)}
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
