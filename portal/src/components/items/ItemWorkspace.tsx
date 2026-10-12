import { useEffect, useRef, useState } from "react"
import type { ReactNode, RefObject } from "react"
import { Link, useLocation } from "react-router"
import { entityLifecyclePath } from "../../api/entityLifecycle"
import { itemAuthoringPath } from "../../api/items"
import { provenancePath } from "../../api/sources"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import type { UseAuthoringResourceResult } from "../../hooks/useAuthoringResource"
import { useCampaignCapability } from "../../hooks/useCampaignCapability"
import { pickReturnState, useItemsBackPath } from "../../hooks/useItemsBackPath"
import { usePageArrival } from "../../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../../hooks/useUnsavedChangesGuard"
import { useWorldBackPath } from "../../hooks/useWorldBackPath"
import type { EntityLifecycleView } from "../../types/entityLifecycle"
import type { ItemView } from "../../types/items"
import type { Provenance } from "../../types/provenance"
import { describeBlockedReason } from "../../utils/blockedReason"
import { rarityText } from "../../utils/itemState"
import { ConfirmDialog } from "../authoring/ConfirmDialog"
import { WorldTimePicker } from "../authoring/WorldTimePicker"
import { FactGrid } from "../FactGrid"
import { LifecycleActionList, LifecycleActionsProvider, LifecycleBlockedReasons } from "../EntityLifecyclePanel"
import { EntitySourcesSection } from "../EntitySourcesSection"
import { SectionNav, SectionPanel, StageNav } from "../staged/StagedNav"
import { ItemHeader } from "./ItemHeader"
import type { ItemOrigin } from "./ItemHeader"
import { ItemConditionSection, ItemEquipmentSection, ItemMoveSection } from "./ItemPlaySections"
import { ItemStateSummary } from "./ItemStateSummary"
import {
    ITEM_SECTIONS,
    ITEM_STAGES,
    defaultItemSection,
    itemGuidance,
    itemHeadingId,
    itemSectionsOf,
    itemStageLabel,
} from "./itemStages"
import type { ItemSection } from "./itemStages"
import { useItemDrafts } from "./useItemDrafts"
import { useItemOperations } from "./useItemOperation"
import { useItemNavigation } from "./useItemNavigation"
import "../authoring/authoring.css"

interface Props {
    campaignId: string
    itemId: string
    origin: ItemOrigin
}

// Stands in for the lifecycle read while it is unavailable, so the one set of lifecycle actions
// stays mounted whether or not the read succeeded. It offers nothing.
const NO_LIFECYCLE = (itemId: string): EntityLifecycleView => ({
    entity_id: itemId,
    entity_type_code: "item_instance",
    canonical_name: "",
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 0,
    lifecycle_managed: false,
    superseded_by: null,
    available_actions: [],
    blocked_actions: [],
})

// The editor's item page, reached from the item inventory (/items/:id) or from the World page
// (/world/item/:id): the same workspace, with the return navigation of wherever it was opened.
// Mounts nothing, and sends nothing, for anyone without `canon.edit`; they get the World reader.
//
// It is a guided workspace like the Knowledge claim page: stages and sections organise the
// interface only. They are links that change the address, never call the API and never change or
// imply a status; the record's real status is in the header. All sections stay mounted, so what
// was typed in one survives switching to another.
export function ItemWorkspace(props: Props) {
    if (!useCampaignCapability(props.campaignId, "canon.edit")) return null
    return <Loaded {...props} />
}

function Loaded({ campaignId, itemId, origin }: Props) {
    const view = useAuthoringResource<ItemView>(itemAuthoringPath(campaignId, itemId))
    const lifecycle = useAuthoringResource<EntityLifecycleView>(entityLifecyclePath(campaignId, itemId))
    const provenance = useAuthoringResource<Provenance>(provenancePath(campaignId, itemId))
    const headingRef = usePageArrival(view.state.kind === "ready", "path")
    // The last item read that succeeded for this item. A refresh that fails recoverably (a network
    // or server error) keeps the workspace mounted on it, so unsent input in any section survives
    // and the person can retry; a denied or unavailable answer, or a loading state, discards it and
    // fails closed. The workspace is keyed by item, so this never outlives the record or campaign.
    const [kept, setKept] = useState<ItemView | null>(null)
    if (view.state.kind === "ready" && kept !== view.state.data) setKept(view.state.data)
    if ((view.state.kind === "denied" || view.state.kind === "unavailable") && kept !== null) setKept(null)
    const stale = view.state.kind === "error" && kept !== null

    if (view.state.kind === "loading") {
        return (
            <section className="authoring-page" aria-label="Item">
                <p role="status">Loading item…</p>
            </section>
        )
    }
    if (view.state.kind !== "ready" && !stale) {
        const missing = view.state.kind === "unavailable" || view.state.kind === "denied"
        return (
            <section className="authoring-page" aria-labelledby="item-workspace-heading">
                <h1 id="item-workspace-heading" ref={headingRef} tabIndex={-1}>
                    {missing ? "Item unavailable" : "Item information unavailable"}
                </h1>
                <p role="alert">
                    {missing
                        ? "This item does not exist, or you do not have access to it."
                        : "The item could not be loaded. Try again."}
                </p>
                {missing ? null : (
                    <button type="button" className="authoring-button" onClick={() => void view.refetch()}>
                        Try again
                    </button>
                )}
            </section>
        )
    }
    return (
        <Workspace
            campaignId={campaignId}
            itemId={itemId}
            origin={origin}
            data={view.state.kind === "ready" ? view.state.data : (kept as ItemView)}
            refreshFailed={stale}
            refetchItem={view.refetch}
            lifecycle={lifecycle}
            provenance={provenance}
            headingRef={headingRef}
        />
    )
}

function Workspace({
    campaignId,
    itemId,
    origin,
    data,
    refetchItem,
    refreshFailed,
    lifecycle,
    provenance,
    headingRef,
}: Props & {
    data: ItemView
    // The last refresh failed; `data` is the last read that succeeded.
    refreshFailed: boolean
    refetchItem: () => Promise<void>
    lifecycle: UseAuthoringResourceResult<EntityLifecycleView>
    provenance: UseAuthoringResourceResult<Provenance>
    headingRef: RefObject<HTMLHeadingElement | null>
}) {
    const location = useLocation()
    // Router state naming the collection this was opened from rides along every in-page link, so
    // moving between sections never forgets where Back to World (or the inventory) returns to.
    const linkState = pickReturnState(location.state)
    const itemsBack = useItemsBackPath(campaignId)
    const worldBack = useWorldBackPath(campaignId)
    const backHref = origin === "items" ? itemsBack : worldBack

    const settled = lifecycle.state.kind !== "loading"
    const lifecycleView =
        lifecycle.state.kind === "ready" && lifecycle.state.data.lifecycle_managed ? lifecycle.state.data : null
    const nav = useItemNavigation(defaultItemSection(data), { ready: settled })
    const guidance = itemGuidance(data)
    const [sourcesDirty, setSourcesDirty] = useState(false)
    const drafts = useItemDrafts()
    const ops = useItemOperations({
        campaignId,
        view: data,
        when: drafts.when,
        consumeTime: () => drafts.setWhen(""),
        refetch: refetchItem,
    })

    // Move focus to the section heading when the section changes after arrival (a link, Back or
    // Forward), so a keyboard or screen reader user lands on the new content.
    const lastSection = useRef(nav.section)
    useEffect(() => {
        if (lastSection.current !== nav.section) {
            lastSection.current = nav.section
            document.getElementById(itemHeadingId(nav.section))?.focus()
        }
    }, [nav.section])

    const unsaved = [...drafts.unsaved, sourcesDirty ? "a source" : null].filter((part) => part !== null)
    const sectionProps = {
        campaignId,
        view: data,
        ops,
        drafts,
        guidance,
        sectionHref: nav.sectionHref,
        linkState,
    }
    const canRun = data.can_operate && !data.is_destroyed

    const body: Record<ItemSection, ReactNode> = {
        details: (
            <DetailsSection
                campaignId={campaignId}
                itemId={itemId}
                view={data}
                linkState={linkState}
                returnTo={{ pathname: location.pathname, search: nav.sectionHref("details") }}
            />
        ),
        sources: (
            <EntitySourcesSection
                embedded
                campaignId={campaignId}
                entityId={itemId}
                category="item"
                provenance={provenance}
                onDirtyChange={setSourcesDirty}
                returnTo={`${location.pathname}${nav.sectionHref("sources")}`}
                intro={
                    <p className="authoring-note">
                        Sources record where this item came from. They are optional, can be changed at any status,
                        and do not affect review or publication. A written source cannot be edited; write a new one
                        and detach the old.
                    </p>
                }
            />
        ),
        publication: <PublicationSection view={data} lifecycleView={lifecycleView} />,
        move: <ItemMoveSection {...sectionProps} />,
        equipment: <ItemEquipmentSection {...sectionProps} />,
        condition: <ItemConditionSection {...sectionProps} />,
    }

    return (
        <section className="authoring-page item-workspace" aria-labelledby="item-workspace-heading">
            <ItemHeader
                view={data}
                origin={origin}
                backHref={backHref}
                headingRef={headingRef}
                guidance={guidance}
                guidanceHref={guidance === null ? null : nav.sectionHref(guidance.section)}
                linkState={linkState}
            />
            {refreshFailed ? (
                <div className="authoring-message authoring-message--warning" role="alert">
                    <p>
                        The latest item information could not be loaded, so what is shown may be out of date. What
                        you have typed is kept.
                    </p>
                    <button type="button" className="authoring-button" onClick={() => void refetchItem()}>
                        Try again
                    </button>
                </div>
            ) : null}
            <ItemStateSummary view={data} />
            {!settled ? (
                <p role="status">Loading the item…</p>
            ) : (
                <LifecycleActionsProvider
                    campaignId={campaignId}
                    view={lifecycleView ?? NO_LIFECYCLE(itemId)}
                    refetch={lifecycle.refetch}
                    afterDeletePath={backHref}
                    onChanged={() => void refetchItem()}
                >
                    <StageNav
                        ariaLabel="Item stages"
                        stages={ITEM_STAGES}
                        current={nav.stage}
                        hrefFor={nav.stageHref}
                        linkState={linkState}
                    />
                    <div className="staged-workspace">
                        <div
                            className={
                                itemSectionsOf(nav.stage).length > 1
                                    ? "session-run__layout"
                                    : "session-run__layout session-run__layout--single"
                            }
                        >
                            {itemSectionsOf(nav.stage).length > 1 ? (
                                <SectionNav
                                    ariaLabel={`${itemStageLabel(nav.stage)} sections`}
                                    sections={itemSectionsOf(nav.stage)}
                                    current={nav.section}
                                    hrefFor={nav.sectionHref}
                                    linkState={linkState}
                                />
                            ) : null}
                            <div className="session-run__content">
                                {canRun ? (
                                    <div className="item-workspace__time" hidden={nav.stage !== "play"}>
                                        <WorldTimePicker
                                            campaignId={campaignId}
                                            id="item-ops-when"
                                            label="When this happens (in-world)"
                                            hint="Leave empty to use the campaign time."
                                            value={drafts.when}
                                            onChange={drafts.setWhen}
                                        />
                                    </div>
                                ) : null}
                                {ITEM_SECTIONS.map((section) => (
                                    <SectionPanel
                                        key={section.key}
                                        wide
                                        headingId={itemHeadingId(section.key)}
                                        label={section.label}
                                        purpose={section.purpose}
                                        active={section.key === nav.section}
                                    >
                                        {body[section.key]}
                                    </SectionPanel>
                                ))}
                            </div>
                        </div>
                    </div>
                </LifecycleActionsProvider>
            )}
            <UnsavedInputGuard unsaved={unsaved} />
        </section>
    )
}

function DetailsSection({
    itemId,
    view,
    linkState,
    returnTo,
    campaignId,
}: {
    campaignId: string
    itemId: string
    view: ItemView
    linkState?: object
    // The item page as it is now, so Save and Cancel on the edit page return to it.
    returnTo: { pathname: string; search: string }
}) {
    const blocked = view.blocked_actions.find((b) => b.action === "update")?.reason
    const canEdit = view.available_actions.includes("update")
    return (
        <>
            <FactGrid
                items={[
                    { key: "name", label: "Name", value: view.name },
                    {
                        key: "kind",
                        label: "Kind of item",
                        value: `${view.definition_name} (fixed once created)`,
                    },
                    { key: "category", label: "Category", value: view.category_label },
                    { key: "rarity", label: "Rarity", value: rarityText(view.rarity) },
                    {
                        key: "attunement",
                        label: "Requires attunement",
                        value: view.requires_attunement ? "Yes" : "No",
                    },
                    { key: "summary", label: "Summary", value: view.summary ?? "None" },
                    { key: "origin", label: "Origin notes", value: view.origin_notes ?? "None" },
                ]}
            />
            {canEdit ? (
                <p className="authoring-page__actions-row">
                    <Link
                        className="authoring-button"
                        to={`/app/${encodeURIComponent(campaignId)}/items/${encodeURIComponent(itemId)}/edit`}
                        state={{ ...linkState, returnTo }}
                    >
                        Edit item
                    </Link>
                </p>
            ) : blocked !== undefined ? (
                <p className="authoring-note">Editing unavailable: {describeBlockedReason(blocked)}</p>
            ) : null}
        </>
    )
}

// The status in words. Never claims publishing hands the item to anyone: where it is, and who has
// it, are recorded separately in Use in play.
function PublicationExplanation({ view }: { view: ItemView }) {
    if (view.lifecycle_status === "archived") {
        return (
            <p>
                Archived. It is hidden from players and lists, and kept as history. Where it is, who has it and its
                condition are kept, but nothing can change until it is restored.
            </p>
        )
    }
    switch (view.canon_status) {
        case "draft":
            return <p>Draft. Only people who can edit canon can see it. Submit it for review when it is ready.</p>
        case "proposed":
            return <p>In review. A reviewer can approve or reject it, or send it back to draft to change it.</p>
        case "approved":
            return <p>Approved, but not yet published. Publish it to make it part of canon.</p>
        case "canon":
            return <p>Published. It can now be given, placed and used in play.</p>
        case "rejected":
            return <p>Rejected. Return it to draft to rework it, or archive it.</p>
        case "superseded":
            return <p>Replaced. What was recorded here is kept.</p>
        default:
            return <p>No further review steps apply to this status.</p>
    }
}

function PublicationSection({ view, lifecycleView }: { view: ItemView; lifecycleView: EntityLifecycleView | null }) {
    if (lifecycleView === null) {
        return (
            <>
                <PublicationExplanation view={view} />
                <p className="authoring-note" role="status">
                    The item&apos;s lifecycle could not be loaded, so no step is shown. Reload the page to try again.
                </p>
            </>
        )
    }
    return (
        <>
            <PublicationExplanation view={view} />
            <LifecycleActionList />
            <LifecycleBlockedReasons />
        </>
    )
}

// One guard for everything an editor has typed and not yet sent (a hand-over, a place, an amount, a
// source): leaving the page asks first, and so does closing the tab (docs/UI_DESIGN.md §5.11).
function UnsavedInputGuard({ unsaved }: { unsaved: string[] }) {
    const guard = useUnsavedChangesGuard(unsaved.length > 0)
    return (
        <ConfirmDialog
            open={guard.blocked}
            title="Discard unsaved input?"
            description={`You have entered ${unsaved.join(" and ")}. It has not been sent.`}
            confirmLabel="Discard"
            cancelLabel="Keep editing"
            onConfirm={guard.discard}
            onCancel={guard.stay}
        />
    )
}
