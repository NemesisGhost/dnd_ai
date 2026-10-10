import { useEffect, useId, useState } from "react"
import { useParams, useSearchParams } from "react-router"
import { previewKnowledgeListPath } from "../api/knowledgePreview"
import { CardGrid } from "../components/CardGrid"
import { KnowledgeCard } from "../components/KnowledgeCard"
import { MemberPreviewShell } from "../components/knowledge/MemberPreviewShell"
import type { ReadyMemberPreview } from "../components/knowledge/MemberPreviewShell"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { KnowledgePage, KnowledgeView } from "../types/knowledge"
import {
    PREVIEW_VIEWS,
    memberPreviewClaimPath,
    memberPreviewSearch,
    parseMemberPreviewContext,
} from "../utils/memberPreviewContext"
import type { MemberPreviewContext } from "../utils/memberPreviewContext"
import PlaceholderPage from "./PlaceholderPage"

const SEARCH_DEBOUNCE_MS = 180

const VIEW_LABEL: Readonly<Record<KnowledgeView, string>> = {
    known: "Known",
    rumors: "Rumors",
    party_shared: "Party shared",
    character_private: "Character private",
    recent: "Recent",
    public: "Public only",
}

// /app/:campaignId/knowledge/member-preview: the read-only Member preview workspace. The member,
// perspective, filters and page all live in the address, so Back/Forward, a reload and a shared
// link reproduce them; nothing here touches the normal Knowledge page's own state.
function MemberPreviewCollection({ campaignId }: { campaignId: string }) {
    const [params, setParams] = useSearchParams()
    const context = parseMemberPreviewContext(params)
    const update = (next: Partial<MemberPreviewContext>, replace = false) => {
        setParams(new URLSearchParams(memberPreviewSearch({ ...context, ...next })), { replace })
    }

    return (
        <MemberPreviewShell
            campaignId={campaignId}
            context={context}
            mode="collection"
            onContextChange={(next) => update(next)}
        >
            {(ready) => <PreviewResults campaignId={campaignId} ready={ready} context={context} onChange={update} />}
        </MemberPreviewShell>
    )
}

function PreviewResults({
    campaignId,
    ready,
    context,
    onChange,
}: {
    campaignId: string
    ready: ReadyMemberPreview
    context: MemberPreviewContext
    onChange: (next: Partial<MemberPreviewContext>, replace?: boolean) => void
}) {
    const viewId = useId()
    const searchId = useId()
    const publicId = useId()
    const [typed, setTyped] = useState(context.query)
    // A query changed from outside (Back/Forward) replaces what is typed.
    const [seen, setSeen] = useState(context.query)
    if (seen !== context.query) {
        setSeen(context.query)
        setTyped(context.query)
    }
    useEffect(() => {
        if (typed === context.query) return
        const timeout = window.setTimeout(() => onChange({ query: typed, cursor: null }, true), SEARCH_DEBOUNCE_MS)
        return () => window.clearTimeout(timeout)
    }, [typed, context.query, onChange])

    const publicOnly = context.view === "public"
    const list = useAuthoringResource<KnowledgePage>(
        previewKnowledgeListPath(campaignId, ready.membershipId, {
            view: context.view,
            characterId: ready.characterId,
            partyId: ready.partyId,
            query: context.query,
            includePublic: context.includePublic || publicOnly,
            cursor: context.cursor,
        }),
    )
    const claimHref = (id: string) =>
        `${memberPreviewClaimPath(campaignId, id)}${memberPreviewSearch({ ...context, characterId: ready.characterId, partyId: ready.partyId })}`
    const state = list.state

    return (
        <>
            <div className="knowledge-page__filters" role="search" aria-label="Preview knowledge search">
                <div className="knowledge-page__field">
                    <label htmlFor={viewId}>View</label>
                    <select
                        id={viewId}
                        value={context.view}
                        onChange={(event) => onChange({ view: event.currentTarget.value as KnowledgeView, cursor: null })}
                    >
                        {PREVIEW_VIEWS.map((view) => (
                            <option key={view} value={view}>
                                {VIEW_LABEL[view]}
                            </option>
                        ))}
                    </select>
                </div>
                <div className="knowledge-page__field">
                    <label htmlFor={searchId}>Search</label>
                    <input
                        id={searchId}
                        type="search"
                        value={typed}
                        onChange={(event) => setTyped(event.currentTarget.value)}
                    />
                </div>
                <div className="knowledge-page__field">
                    <label htmlFor={publicId}>
                        <input
                            id={publicId}
                            type="checkbox"
                            checked={context.includePublic || publicOnly}
                            disabled={publicOnly}
                            onChange={(event) => onChange({ includePublic: event.currentTarget.checked, cursor: null })}
                        />{" "}
                        Include public knowledge
                    </label>
                </div>
            </div>

            <div role="region" aria-label="Preview knowledge results" aria-busy={state.kind === "loading"}>
                {state.kind === "loading" ? (
                    <p role="status">Loading what {ready.memberName} can see…</p>
                ) : state.kind === "unavailable" || state.kind === "denied" ? (
                    <p role="alert">
                        {ready.memberName} cannot open Knowledge in this campaign, or this view is not available to them.
                    </p>
                ) : state.kind === "error" ? (
                    <>
                        <p role="alert">The preview could not be loaded.</p>
                        <button type="button" className="authoring-button" onClick={() => void list.refetch()}>
                            Try again
                        </button>
                    </>
                ) : (
                    <>
                        {state.data.items.length > 0 ? (
                            <CardGrid ariaLabel="Knowledge items the member can see" className="knowledge-card-grid">
                                {state.data.items.map((item) => (
                                    <KnowledgeCard
                                        key={item.knowledge_item_id}
                                        campaignId={campaignId}
                                        item={item}
                                        characterId={ready.characterId}
                                        partyId={ready.partyId}
                                        detailHref={claimHref(item.knowledge_item_id)}
                                    />
                                ))}
                            </CardGrid>
                        ) : (
                            <p>{ready.memberName} sees no knowledge matching this view and search.</p>
                        )}
                        <p className="member-preview__paging">
                            {context.cursor !== null ? (
                                <button type="button" className="authoring-button" onClick={() => onChange({ cursor: null })}>
                                    First page
                                </button>
                            ) : null}{" "}
                            {state.data.next_cursor !== null ? (
                                <button
                                    type="button"
                                    className="authoring-button"
                                    onClick={() => onChange({ cursor: state.data.next_cursor })}
                                >
                                    Next page
                                </button>
                            ) : null}
                        </p>
                    </>
                )}
            </div>
        </>
    )
}

export function KnowledgeMemberPreviewPage() {
    const { campaignId } = useParams<{ campaignId: string }>()
    if (campaignId === undefined) {
        return <PlaceholderPage title="Knowledge unavailable" description="The requested knowledge is not available." />
    }
    // A campaign change remounts everything, so no member or perspective carries over.
    return <MemberPreviewCollection key={campaignId} campaignId={campaignId} />
}
