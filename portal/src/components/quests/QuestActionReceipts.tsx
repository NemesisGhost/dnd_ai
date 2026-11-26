import { Link } from "react-router"
import { receiptHeadingId, receiptHeadingText } from "./questReceipts"
import type { QuestReceipt } from "./questReceipts"
import { statusLabel } from "./questStatusLabel"

interface Props {
    campaignId: string
    receipts: readonly QuestReceipt[]
    // Reads progress again (read-only) for one receipt whose read-back failed.
    onCheck: (id: string) => void
}

// This visit's confirmed changes, newest first. Held in memory only; the campaign's event history is the
// record, reached by the link.
export function QuestActionReceipts({ campaignId, receipts, onCheck }: Props) {
    if (receipts.length === 0) return null
    return (
        <section className="quest-progress__receipts" aria-label="Changes in this visit">
            <ol className="op-list">
                {receipts.map((r) => (
                    <li key={r.id}>
                        <article className="authoring-card">
                            <h3 id={receiptHeadingId(r.id)} tabIndex={-1}>
                                {receiptHeadingText(r.action, r.who)}
                            </h3>
                            <ul>
                                <li>
                                    {r.changed
                                        ? `Status: ${statusLabel(r.previous)} → ${statusLabel(r.status)}, recorded as an event.`
                                        : `Status: already ${statusLabel(r.status)}; no new change was recorded.`}{" "}
                                    <Link to={`/app/${encodeURIComponent(campaignId)}/events/${encodeURIComponent(r.eventId)}`}>
                                        Open the recorded event
                                    </Link>
                                </li>
                                <li>
                                    {r.readBack ? "Progress shown: read again." : "Progress shown: could not be read again."}{" "}
                                    {r.readBack ? null : (
                                        <button type="button" className="authoring-button" onClick={() => onCheck(r.id)}>
                                            Check progress
                                        </button>
                                    )}
                                </li>
                                {r.rewardsLine === null ? null : <li>{r.rewardsLine}</li>}
                            </ul>
                        </article>
                    </li>
                ))}
            </ol>
        </section>
    )
}
