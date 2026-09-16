import { Link } from "react-router"
import { DetailPanel } from "../components/DetailPanel"
import { FactGrid } from "../components/FactGrid"
import type { KnowledgeDetail } from "../types/knowledge"
import { humanizeCode } from "../utils/humanize"

interface KnowledgeDetailPageProps {
    campaignId: string
    item: KnowledgeDetail
}

// Full-page Knowledge detail (UI_STYLE_GUIDE.md §11.2). Scope and source
// fields from the list contract are deliberately not shown here — the
// detail endpoint does not independently return them, so this page never
// copies them in from cached list state.
export function KnowledgeDetailPage({
    campaignId,
    item,
}: KnowledgeDetailPageProps) {
    const hasCanonicalInfo =
        item.truth_status_code !== null || item.sensitivity !== null

    return (
        <section aria-labelledby="knowledge-detail-heading">
            <p>
                <Link
                    to={`/app/${encodeURIComponent(campaignId)}/knowledge`}
                >
                    Back to Knowledge
                </Link>
            </p>

            <p className="knowledge-detail__eyebrow">
                {humanizeCode(item.knowledge_type_code)}
            </p>
            <h1 id="knowledge-detail-heading">{item.statement}</h1>

            <div className="world-detail__panel-grid">
                <DetailPanel title="Awareness and Confidence">
                    <FactGrid
                        items={[
                            {
                                key: "awareness",
                                label: "Awareness",
                                value:
                                    item.awareness_level !== null
                                        ? humanizeCode(item.awareness_level)
                                        : "Not recorded",
                            },
                            {
                                key: "confidence",
                                label: "Confidence",
                                value:
                                    item.confidence !== null
                                        ? `${item.confidence}%`
                                        : "Not recorded",
                            },
                        ]}
                    />
                </DetailPanel>

                <DetailPanel title="Sharing">
                    <FactGrid
                        items={[
                            {
                                key: "willing-to-share",
                                label: "Willing to share",
                                value:
                                    item.willing_to_share === null
                                        ? "Not recorded"
                                        : item.willing_to_share
                                            ? "Yes"
                                            : "No",
                            },
                        ]}
                    />
                </DetailPanel>

                {hasCanonicalInfo && (
                    <DetailPanel title="Canonical Information">
                        <FactGrid
                            items={[
                                {
                                    key: "truth-status",
                                    label: "Truth status",
                                    value:
                                        item.truth_status_code !== null
                                            ? humanizeCode(
                                                item.truth_status_code,
                                            )
                                            : "Not recorded",
                                },
                                {
                                    key: "sensitivity",
                                    label: "Sensitivity",
                                    value:
                                        item.sensitivity !== null
                                            ? humanizeCode(item.sensitivity)
                                            : "Not recorded",
                                },
                            ]}
                        />
                    </DetailPanel>
                )}
            </div>
        </section>
    )
}
