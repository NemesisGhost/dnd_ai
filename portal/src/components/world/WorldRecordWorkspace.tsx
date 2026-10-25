import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { ReactNode, RefObject } from "react"
import { Link, useLocation } from "react-router"
import { entityLifecyclePath } from "../../api/entityLifecycle"
import { npcAuthoringPath } from "../../api/npcAuthoring"
import { organizationAuthoringPath, religionAuthoringPath } from "../../api/organizationAuthoring"
import { playerCharacterAuthoringPath } from "../../api/playerCharacterAuthoring"
import { provenancePath } from "../../api/sources"
import { revisionsPath } from "../../api/review"
import { apiRequest } from "../../api/http"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import { useGatedAuthoringResource } from "../../hooks/useGatedAuthoringResource"
import type { UseAuthoringResourceResult } from "../../hooks/useAuthoringResource"
import { useCampaignCapability } from "../../hooks/useCampaignCapability"
import { useHeldWorldCapability, WORLD_CANON_READ_PRIVATE } from "../../hooks/useWorldCapability"
import { usePageArrival } from "../../hooks/usePageArrival"
import { pickWorldReturnState, useReviewBackPath, useWorldBackPath } from "../../hooks/useWorldBackPath"
import { CharacterPanels } from "../../pages/CharacterDetailPage"
import { LocationPanels } from "../../pages/WorldLocationDetailPage"
import { OrganizationPanels } from "../../pages/WorldOrganizationDetailPage"
import { ReligionPanels } from "../../pages/WorldReligionDetailPage"
import type { CharacterDetail } from "../../types/character"
import type { EntityLifecycleView } from "../../types/entityLifecycle"
import type { Provenance } from "../../types/provenance"
import type { RevisionHistory } from "../../types/review"
import type { LocationDetail, OrganizationDetail, ReligionDetail } from "../../types/world"
import { humanizeCode } from "../../utils/humanize"
import { NO_RECORD_AUTHORING, authoringOf } from "../../utils/recordAuthoring"
import type { RecordAuthoring } from "../../utils/recordAuthoring"
import type { RetainedChange } from "../../utils/retainedChanges"
import { useSession } from "../../context/SessionContext"
import { PermissionLost } from "../authoring/PermissionLost"
import type { RecheckResult } from "../authoring/PermissionLost"
import { PermissionLossContext } from "../authoring/permissionLoss"
import type { PermissionLossHandle } from "../authoring/permissionLoss"
import { AuthoringEditLink } from "../AuthoringEditLink"
import { LifecycleActionsProvider } from "../EntityLifecyclePanel"
import { EntitySourcesSection } from "../EntitySourcesSection"
import { CharacterInventoryPanel } from "../InventoryPanels"
import { BuildsLink, PlayerAccessLink, PortrayalLink } from "../NpcAuthoringControls"
import { NpcRuntimePanel } from "../NpcRuntimePanel"
import { OrganizationMembers } from "../OrganizationMembers"
import { RelationshipsPanel } from "../RelationshipsPanel"
import { SectionNav, SectionPanel, StageNav } from "../staged/StagedNav"
import { UnsavedInputGuard } from "../staged/UnsavedInputGuard"
import { useStagedNavigation } from "../staged/useStagedNavigation"
import { AreaContentsSection } from "./AreaContentsSection"
import { AreaNowSection } from "./AreaNowSection"
import { DungeonAreasReview } from "./DungeonAreasReview"
import { DungeonAreasSection } from "./DungeonAreasSection"
import { DungeonConnectionsSection } from "./DungeonConnectionsSection"
import { locationEditPath, locationNoun, locationViewPath } from "./placePaths"
import { WorldPublicationSection } from "./WorldPublication"
import { WorldRecordHeader } from "./WorldRecordHeader"
import { WorldReviewSection } from "./WorldReviewSection"
import { useAreaRead, useAreaRuntimeRead, useDungeonRead } from "./useDungeonRead"
import {
    LEGACY_SECTION_ALIASES,
    WORLD_STAGE_LABELS,
    defaultWorldSection,
    playBlockedText,
    sectionWithheldReason,
    worldGuidance,
    worldHeadingId,
    worldKindOf,
    worldSectionsInStage,
    worldSectionsOf,
    worldStagesOf,
} from "./worldStages"
import type { WorkspaceCategory, WorldKind, WorldSection, WorldStage } from "./worldStages"
import { worldDetailPath, worldHistoryPath, worldRecordPath } from "./worldPaths"
import type { WorkspaceDetail } from "./worldPaths"
import "../authoring/authoring.css"

interface Props {
    campaignId: string
    category: WorkspaceCategory
    entityId: string
}

const NOUN: Readonly<Record<WorkspaceCategory, string>> = {
    location: "location",
    organization: "organization",
    religion: "religion",
    character: "character",
}

// What the header calls the record in "You can read and use this ...", by its kind.
const KIND_NOUN: Readonly<Record<WorldKind, string>> = {
    place: "place",
    dungeon: "dungeon",
    area: "area",
    organization: "organization",
    religion: "religion",
    npc: "NPC",
    pc: "player character",
    character: "character",
}

// Stands in for the lifecycle read while it is unavailable, so the one set of lifecycle actions
// stays mounted whether or not the read succeeded. It offers nothing.
const NO_LIFECYCLE = (entityId: string): EntityLifecycleView => ({
    entity_id: entityId,
    entity_type_code: "unknown",
    canonical_name: "",
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 0,
    lifecycle_managed: false,
    superseded_by: null,
    available_actions: [],
    blocked_actions: [],
})

// The editor's page for a World record that goes through the canon lifecycle: a place, a dungeon,
// a dungeon area, an organization, a religion, an NPC or a player character. Mounts nothing, and
// sends nothing, for anyone without `canon.edit`; they get the World reader. (Items keep the item
// workspace; events and relationships are not lifecycle-managed and have no workspace.)
//
// It is a guided workspace like the item page and the Knowledge claim: stages and sections
// organise the interface only. They are links that change the address, never call the API and
// never change or imply a status; the record's real status is in the header. All sections stay
// mounted, so what was typed in one survives switching to another, and each keeps its own saves.
export function WorldRecordWorkspace(props: Props) {
    if (!useCampaignCapability(props.campaignId, "canon.edit")) return null
    return <Loaded {...props} />
}

function Loaded({ campaignId, category, entityId }: Props) {
    const detail = useAuthoringResource<WorkspaceDetail>(worldDetailPath(campaignId, category, entityId))
    // The last read that succeeded for this record. A refresh that fails recoverably (a network or
    // server error) keeps the workspace mounted on it, so unsent input in any section survives and
    // the person can retry; a denied or unavailable answer, or a loading state, discards it and
    // fails closed. The workspace is keyed by record, so this never outlives it.
    const [kept, setKept] = useState<WorkspaceDetail | null>(null)
    if (detail.state.kind === "ready" && kept !== detail.state.data) setKept(detail.state.data)
    if ((detail.state.kind === "denied" || detail.state.kind === "unavailable") && kept !== null) setKept(null)
    // What the server says this caller may do to the record. The private side of a record
    // (its lifecycle, sources, revisions and preparation) is requested only once it says so, and
    // not at all otherwise: a runtime GM with no world role reads and runs the published record
    // without a single refused request.
    // A private-authoring command refused because the world authority is gone (the confirmed loss):
    // the unsent input worth showing back, or null while nothing was lost. From then on the private
    // reads are not held and the private controls are not offered; the server's own later answers
    // (the record read again, the bootstrap refreshed) decide whether access is restored.
    const [lost, setLost] = useState<RetainedChange[] | null>(null)
    const retained = useRef(new Map<string, RetainedChange[]>())
    const { refresh } = useSession()
    const loss = useMemo<PermissionLossHandle>(
        () => ({
            reportLoss: () => {
                setLost((current) => current ?? [...retained.current.values()].flat())
                // Bring the bootstrap's world-capability snapshot up to date without unmounting the page.
                void Promise.resolve(refresh?.()).catch(() => undefined)
            },
            retain: (source, changes) => {
                if (changes.length === 0) retained.current.delete(source)
                else retained.current.set(source, changes)
            },
        }),
        [refresh],
    )
    // "Check my access again": the panel, and what it retains, stay until a fresh check has finished
    // and the server's own answers (the session and this record's `authoring`) say access is back.
    // Anything else leaves the values in place with a retryable result.
    const [recheck, setRecheck] = useState<RecheckResult>("idle")
    const checking = useRef(false)
    const headingRef = usePageArrival(detail.state.kind === "ready", "path")
    const startRecheck = useCallback(async () => {
        if (checking.current) return
        checking.current = true
        setRecheck("checking")
        try {
            // A request of its own, so the answer is the server's now and not whatever the page last held.
            const [refreshed, fresh] = await Promise.all([
                Promise.resolve(refresh?.()).then(
                    (ok) => ok !== false,
                    () => false,
                ),
                apiRequest<WorkspaceDetail>("GET", worldDetailPath(campaignId, category, entityId)).then(
                    (data) => ({ data }),
                    () => null,
                ),
            ])
            if (!refreshed || fresh === null) {
                setRecheck("failed")
            } else if (!authoringOf(fresh.data).can_edit) {
                setRecheck("denied")
            } else {
                // Restored: only now do the retained values go. The button that had focus unmounts with
                // the panel, so focus moves to the record's heading rather than falling to the page.
                retained.current.clear()
                setLost(null)
                setRecheck("idle")
                void detail.refetch()
                headingRef.current?.focus()
            }
        } finally {
            checking.current = false
        }
    }, [refresh, campaignId, category, entityId, detail, headingRef])
    const authoring =
        lost !== null ? NO_RECORD_AUTHORING : authoringOf(detail.state.kind === "ready" ? detail.state.data : kept)
    const canReadWorldPrivate = useHeldWorldCapability(campaignId, WORLD_CANON_READ_PRIVATE) && lost === null
    // Once lost, the record keeps its audience-safe fields but no longer claims any authoring right,
    // so every edit entry point built from it fails closed.
    const loaded = detail.state.kind === "ready" ? detail.state.data : (kept as WorkspaceDetail)
    const shown = lost !== null && loaded !== null ? ({ ...loaded, authoring: NO_RECORD_AUTHORING } as WorkspaceDetail) : loaded
    const lifecycle = useGatedAuthoringResource<EntityLifecycleView>(
        entityLifecyclePath(campaignId, entityId),
        authoring.can_read_private,
    )
    const provenance = useGatedAuthoringResource<Provenance>(
        provenancePath(campaignId, entityId),
        canReadWorldPrivate,
    )
    const revisions = useGatedAuthoringResource<RevisionHistory>(
        revisionsPath(campaignId, entityId),
        canReadWorldPrivate,
    )
    const worldBack = useWorldBackPath(campaignId)
    const stale = detail.state.kind === "error" && kept !== null
    const noun = NOUN[category]
    const title = `${noun.charAt(0).toUpperCase()}${noun.slice(1)}`

    if (detail.state.kind === "loading") {
        return (
            <section className="authoring-page" aria-label={title}>
                <p role="status">Loading {noun}…</p>
            </section>
        )
    }
    if (detail.state.kind !== "ready" && !stale) {
        const missing = detail.state.kind === "unavailable" || detail.state.kind === "denied"
        return (
            <section className="authoring-page" aria-labelledby="world-workspace-heading">
                <p>
                    <Link to={worldBack}>Back to World</Link>
                </p>
                <h1 id="world-workspace-heading" ref={headingRef} tabIndex={-1}>
                    {missing ? `${title} unavailable` : `${title} information unavailable`}
                </h1>
                <p role="alert">
                    {missing
                        ? `This ${noun} does not exist, or you do not have access to it.`
                        : `The ${noun} could not be loaded. Try again.`}
                </p>
                {missing ? null : (
                    <button type="button" className="authoring-button" onClick={() => void detail.refetch()}>
                        Try again
                    </button>
                )}
            </section>
        )
    }
    return (
        <PermissionLossContext.Provider value={loss}>
            <Workspace
                campaignId={campaignId}
                category={category}
                entityId={entityId}
                data={shown}
                refreshFailed={stale}
                refetchDetail={detail.refetch}
                lifecycle={lifecycle}
                provenance={provenance}
                revisions={revisions}
                authoring={authoring}
                canReadWorldPrivate={canReadWorldPrivate}
                lost={lost}
                onRecheck={() => void startRecheck()}
                recheck={recheck}
                headingRef={headingRef}
            />
        </PermissionLossContext.Provider>
    )
}

// The entity type of a record, from the audience-safe detail, for the kinds whose category holds
// more than one (a place is a dungeon or an area; a character is an NPC or a player character).
function typeCodeOf(category: WorkspaceCategory, data: WorkspaceDetail): string | null {
    switch (category) {
        case "location":
            return (data as LocationDetail).location_type_code
        case "character":
            return (data as CharacterDetail).character_kind
        default:
            return null
    }
}

// The canon and lifecycle status the audience-safe detail carries (places, organizations and
// religions do; a character does not), for explaining what play cannot do yet.
function statusOf(data: WorkspaceDetail): { canon_status: string; lifecycle_status: string } | null {
    const d = data as Partial<{ canon_status: string; lifecycle_status: string }>
    return typeof d.canon_status === "string" && typeof d.lifecycle_status === "string"
        ? { canon_status: d.canon_status, lifecycle_status: d.lifecycle_status }
        : null
}

// What the header says about the record, from the audience-safe detail the page already read.
function describe(category: WorkspaceCategory, kind: WorldKind, data: WorkspaceDetail) {
    switch (category) {
        case "location": {
            const d = data as LocationDetail
            return { name: d.name, eyebrow: humanizeCode(d.location_type_code), summary: d.summary }
        }
        case "organization": {
            const d = data as OrganizationDetail
            return { name: d.name, eyebrow: humanizeCode(d.kind_code), summary: d.summary }
        }
        case "religion": {
            const d = data as ReligionDetail
            return { name: d.name, eyebrow: "Religion", summary: d.summary }
        }
        case "character": {
            const d = data as CharacterDetail
            return {
                name: d.name,
                eyebrow: kind === "npc" ? "NPC" : kind === "pc" ? "Player character" : "Character",
                summary: null,
            }
        }
    }
}

function Workspace({
    campaignId,
    category,
    entityId,
    data,
    refetchDetail,
    refreshFailed,
    lifecycle,
    provenance,
    revisions,
    authoring,
    canReadWorldPrivate,
    lost,
    onRecheck,
    recheck,
    headingRef,
}: Props & {
    data: WorkspaceDetail
    // The last refresh failed; `data` is the last read that succeeded.
    refreshFailed: boolean
    refetchDetail: () => Promise<unknown>
    lifecycle: UseAuthoringResourceResult<EntityLifecycleView>
    provenance: UseAuthoringResourceResult<Provenance>
    revisions: UseAuthoringResourceResult<RevisionHistory>
    // What the server says the caller may do to this record, and whether the world's private side
    // is theirs to read (it decides the preparation sections; see worldStages.sectionWithheldReason).
    authoring: RecordAuthoring
    canReadWorldPrivate: boolean
    // Set once a private-authoring command was refused for lack of the world authority.
    lost: RetainedChange[] | null
    onRecheck: () => void
    recheck: RecheckResult
    headingRef: RefObject<HTMLHeadingElement | null>
}) {
    const location = useLocation()
    // Router state naming where the record was opened from (the World browser, the Review queue)
    // rides along every in-page link, so moving between sections never forgets where Back returns.
    const linkState = pickWorldReturnState(location.state)
    const worldBack = useWorldBackPath(campaignId)
    const reviewBack = useReviewBackPath(campaignId)
    const back = reviewBack !== null ? { href: reviewBack, label: "Back to Review queue" } : { href: worldBack, label: "Back to World" }

    const settled = lifecycle.state.kind !== "loading"
    // A lifecycle read that succeeded and says the record is not lifecycle-managed (a bare
    // character) is not a failed read: it has no publication workflow, only its details.
    const unmanaged = lifecycle.state.kind === "ready" && !lifecycle.state.data.lifecycle_managed
    const lifecycleView =
        lifecycle.state.kind === "ready" && lifecycle.state.data.lifecycle_managed ? lifecycle.state.data : null
    // The kind comes from the lifecycle read when there is one and from the record itself when the
    // lifecycle is not the caller's to read, so a withheld lifecycle never turns a player character
    // or an NPC into a generic character (and its runtime sections away).
    // The record's status for the explanations of what play cannot do yet: the lifecycle read when
    // the caller has one, else the audience-safe detail (which carries the status fields).
    const playStatus = lifecycleView ?? statusOf(data)
    const kind = worldKindOf(category, lifecycleView?.entity_type_code ?? typeCodeOf(category, data))
    const access = { canReadRecordPrivate: authoring.can_read_private, canReadWorldPrivate }
    const everySection = worldSectionsOf(kind)
    // Only the sections that are the caller's are navigable, mounted and requested; the rest stay in
    // the structure as text with their reason (stable structure), never as links.
    const sections = everySection.filter((section) => sectionWithheldReason(section.key, access) === null)
    const nav = useStagedNavigation(sections, defaultWorldSection(lifecycleView), {
        ready: settled && !unmanaged,
        aliases: LEGACY_SECTION_ALIASES,
    })
    // A dungeon's Areas and Connections share one read of the dungeon, so both always name the same
    // version. Nothing is requested for any other record.
    const dungeonRead = useDungeonRead(campaignId, entityId, kind === "dungeon" && canReadWorldPrivate)
    // The same for an area's Contents and Area now.
    // The area's structure reads the authoring view, which is the world's private side: asked for
    // only when that is the caller's. "Area now" reads the campaign's own runtime projection, which
    // needs no world role, so a campaign GM can run the area without any private request.
    const areaRead = useAreaRead(campaignId, entityId, kind === "area" && canReadWorldPrivate)
    const areaRuntime = useAreaRuntimeRead(campaignId, entityId, kind === "area")
    const guidance = lifecycleView === null ? null : worldGuidance(lifecycleView)
    const [sourcesDirty, setSourcesDirty] = useState(false)
    // How many times the record was refreshed after a step, for the links that read the record's
    // authoring view and must not outlive the state that allowed them.
    const [changes, setChanges] = useState(0)
    // A command recorded on a panel (hit points, a status): the page's own view of the record is
    // read again; nothing is remounted and no other section's input is touched.
    const refreshDetail = () => void refetchDetail()
    const refreshRecord = () => {
        setChanges((n) => n + 1)
        void refetchDetail()
        void revisions.refetch()
        void dungeonRead.reload()
        void areaRead.reload()
        void areaRuntime.reload()
    }
    // A structural command bumps the dungeon's version, which the lifecycle actions send as their
    // stale-write token: read the dungeon, its lifecycle and its revisions together, so a publish
    // right after adding a connection names the version the server now holds.
    const refreshStructure = async () => {
        await Promise.all([dungeonRead.reload(), lifecycle.refetch(), revisions.refetch()])
    }
    // A change to an area's contents reads the area, its lifecycle and its revisions again (the
    // dungeon's lifecycle is not on this page).
    const refreshContents = async () => {
        await Promise.all([areaRead.reload(), areaRuntime.reload(), lifecycle.refetch(), revisions.refetch()])
    }
    // A recorded state reads the area again, and the facts shown above its controls.
    const refreshState = async () => {
        await Promise.all([areaRuntime.reload(), refetchDetail()])
    }

    // Move focus to the section heading when the section changes after arrival (a link, Back or
    // Forward), so a keyboard or screen reader user lands on the new content.
    const lastSection = useRef(nav.section)
    useEffect(() => {
        if (lastSection.current !== nav.section) {
            lastSection.current = nav.section
            document.getElementById(worldHeadingId(nav.section))?.focus()
        }
    }, [nav.section])

    // What is typed and not sent, by reporter, for the page's one guard.
    const [unsentBy, setUnsentBy] = useState<Record<string, string[]>>({})
    const reportUnsaved = useCallback((source: string, labels: string[]) => {
        setUnsentBy((current) => {
            const before = current[source] ?? []
            if (before.join("|") === labels.join("|")) return current
            const next = { ...current }
            if (labels.length === 0) delete next[source]
            else next[source] = labels
            return next
        })
    }, [])
    const unsaved = [...new Set([sourcesDirty ? "a source" : null, ...Object.values(unsentBy).flat()])].filter(
        (part) => part !== null,
    )
    const info = describe(category, kind, data)
    const here = location.pathname
    const sectionHref = (key: WorldSection): string => nav.sectionHref(key)
    // The page as it is now, so Save and Cancel on an edit page return to the section left.
    const editStateFor = (section: WorldSection) => ({
        ...linkState,
        returnTo: { pathname: here, search: nav.sectionHref(section) },
    })
    const editState = editStateFor("details")
    const historyHref = worldHistoryPath(campaignId, category, entityId)
    const playNoun = kind === "area" ? "area" : kind === "organization" ? "organization" : "character"

    function renderSection(key: WorldSection): ReactNode {
        switch (key) {
            case "details":
                return (
                    <DetailsSection
                        campaignId={campaignId}
                        category={category}
                        kind={kind}
                        data={data}
                        changes={changes}
                        editState={editState}
                    />
                )
            case "areas":
                return (
                    <DungeonAreasSection
                        campaignId={campaignId}
                        dungeonId={entityId}
                        read={dungeonRead}
                        refresh={refreshStructure}
                        linkState={linkState}
                        editState={editStateFor("areas")}
                        onUnsaved={reportUnsaved}
                    />
                )
            case "connections":
                return (
                    <DungeonConnectionsSection
                        campaignId={campaignId}
                        dungeonId={entityId}
                        read={dungeonRead}
                        refresh={refreshStructure}
                        areasHref={sectionHref("areas")}
                        linkState={linkState}
                        onUnsaved={reportUnsaved}
                    />
                )
            case "sources":
                return (
                    <EntitySourcesSection
                        embedded
                        campaignId={campaignId}
                        entityId={entityId}
                        category={category}
                        provenance={provenance}
                        onDirtyChange={setSourcesDirty}
                        returnTo={`${here}${nav.sectionHref("sources")}`}
                        intro={
                            <p className="authoring-note">
                                Sources record where this record came from. They are optional, can be changed at any
                                status, and do not affect review or publication. A written source cannot be edited;
                                write a new one and detach the old.
                            </p>
                        }
                    />
                )
            case "relationships":
                return (
                    <RelationshipsPanel
                        embedded
                        campaignId={campaignId}
                        entityId={entityId}
                        kind={kind}
                        membersHref={kind === "organization" ? sectionHref("members") : undefined}
                        onUnsaved={reportUnsaved}
                    />
                )
            case "review":
                return (
                    <WorldReviewSection
                        lifecycleView={lifecycleView}
                        revisions={revisions}
                        historyHref={historyHref}
                        detailsHref={sectionHref("details")}
                        publicationHref={sectionHref("publication")}
                        linkState={linkState}
                        summary={kind === "dungeon" ? <DungeonAreasReview view={dungeonRead.view} /> : undefined}
                    />
                )
            case "publication":
                return (
                    <WorldPublicationSection
                        lifecycleView={lifecycleView}
                        historyHref={historyHref}
                        linkState={linkState}
                        onRetry={() => void lifecycle.refetch()}
                    />
                )
            case "contents": {
                const dungeonId = (data as LocationDetail).parent_location_id
                return (
                    <AreaContentsSection
                        campaignId={campaignId}
                        areaId={entityId}
                        read={areaRead}
                        refresh={refreshContents}
                        connectionsHref={
                            dungeonId === null
                                ? worldRecordPath(campaignId, "location", entityId)
                                : `${worldRecordPath(campaignId, "location", dungeonId)}?section=connections`
                        }
                        linkState={linkState}
                        onUnsaved={reportUnsaved}
                    />
                )
            }
            case "area-now":
                return (
                    <AreaNowSection
                        campaignId={campaignId}
                        areaId={entityId}
                        location={data as LocationDetail}
                        lifecycleView={playStatus}
                        read={areaRuntime}
                        refresh={refreshState}
                        onUnsaved={reportUnsaved}
                    />
                )
            case "members": {
                // Unknown status (the lifecycle read failed) is not eligibility: withhold the commands.
                const blocked =
                    playStatus === null
                        ? `The ${playNoun}'s status could not be loaded, so recording members or a status is not offered.`
                        : playBlockedText(playStatus, playNoun)
                return (
                    <>
                        {blocked !== null ? <p className="authoring-note">{blocked}</p> : null}
                        <OrganizationMembers
                            embedded
                            campaignId={campaignId}
                            organizationId={entityId}
                            refreshToken={changes}
                            onChanged={refreshDetail}
                            commandsBlocked={blocked !== null}
                        />
                    </>
                )
            }
            case "run":
                return (
                    <NpcRuntimePanel
                        embedded
                        campaignId={campaignId}
                        characterId={entityId}
                        refreshToken={changes}
                        onChanged={refreshDetail}
                        blockedText={playStatus === null ? undefined : playBlockedText(playStatus, "NPC")}
                    />
                )
            case "player":
                return (
                    <PlayerSection
                        campaignId={campaignId}
                        characterId={entityId}
                        version={changes}
                    />
                )
            case "inventory":
                return <CharacterInventoryPanel embedded campaignId={campaignId} characterId={entityId} />
        }
    }

    if (unmanaged) {
        return (
            <section className="authoring-page item-workspace" aria-labelledby="world-workspace-heading">
                <WorldRecordHeader
                    name={info.name}
                    eyebrow={info.eyebrow}
                    summary={info.summary}
                    status={null}
                    back={back}
                    headingRef={headingRef}
                    guidance={null}
                    guidanceHref={null}
                />
                <DetailsSection
                    campaignId={campaignId}
                    category={category}
                    kind={kind}
                    data={data}
                    changes={changes}
                    editState={editState}
                />
            </section>
        )
    }

    // An area names the dungeon it is in, from its own containment: a link up to the dungeon's Areas.
    const parent = category === "location" && kind === "area" ? (data as LocationDetail).breadcrumbs.at(-1) : undefined
    const context =
        parent !== undefined && parent.location_type_code === "dungeon" && parent.location_id === (data as LocationDetail).parent_location_id
            ? {
                  label: parent.name,
                  href: `${worldRecordPath(campaignId, "location", parent.location_id)}?section=areas`,
                  state: linkState,
              }
            : null
    const stages = worldStagesOf(kind)
    // The stage's sections as listed, withheld ones included (marked), and which stages hold
    // nothing the caller may use.
    const listed = (stage: WorldStage) =>
        worldSectionsInStage(kind, stage).map((section) => {
            const reason = sectionWithheldReason(section.key, access)
            return reason === null ? section : { ...section, unavailableReason: reason }
        })
    const stageReason = (stage: WorldStage): string | undefined => {
        const inside = listed(stage)
        return inside.every((section) => "unavailableReason" in section) ? (inside[0] as { unavailableReason: string }).unavailableReason : undefined
    }
    const inStage = listed(nav.stage)
    const withheldNote = !authoring.can_read_private || !canReadWorldPrivate
    return (
        <section className="authoring-page item-workspace" aria-labelledby="world-workspace-heading">
            <WorldRecordHeader
                name={info.name}
                eyebrow={info.eyebrow}
                summary={info.summary}
                status={lifecycleView}
                back={back}
                headingRef={headingRef}
                guidance={guidance}
                guidanceHref={guidance === null ? null : sectionHref(guidance.section)}
                linkState={linkState}
                context={context}
            />
            {lost !== null ? (
                <PermissionLost noun="record" retained={lost} back={{ to: back.href, label: back.label }} recheck={onRecheck} result={recheck} />
            ) : null}
            {withheldNote && !authoring.campaign_originated ? (
                <p className="authoring-note">
                    You can read and use this {KIND_NOUN[kind]} in this campaign. Preparing, reviewing and publishing
                    it belong to the shared world and need a world role; ask the world owner.
                </p>
            ) : null}
            {refreshFailed ? (
                <div className="authoring-message authoring-message--warning" role="alert">
                    <p>
                        The latest information could not be loaded, so what is shown may be out of date. What you
                        have typed is kept.
                    </p>
                    <button type="button" className="authoring-button" onClick={() => void refetchDetail()}>
                        Try again
                    </button>
                </div>
            ) : null}
            {!settled ? (
                <p role="status">Loading the record…</p>
            ) : (
                <LifecycleActionsProvider
                    campaignId={campaignId}
                    view={lifecycleView ?? NO_LIFECYCLE(entityId)}
                    refetch={lifecycle.refetch}
                    afterDeletePath={reviewBack ?? worldBack}
                    onChanged={refreshRecord}
                >
                    <StageNav
                        ariaLabel="Record stages"
                        stages={stages.map((stage) => ({
                            key: stage,
                            label: WORLD_STAGE_LABELS[stage],
                            unavailableReason: stageReason(stage),
                        }))}
                        current={nav.stage}
                        hrefFor={nav.stageHref}
                        linkState={linkState}
                    />
                    <div className="staged-workspace">
                        <div
                            className={
                                inStage.length > 1 ? "session-run__layout" : "session-run__layout session-run__layout--single"
                            }
                        >
                            {inStage.length > 1 ? (
                                <SectionNav
                                    ariaLabel={`${WORLD_STAGE_LABELS[nav.stage]} sections`}
                                    sections={inStage}
                                    current={nav.section}
                                    hrefFor={nav.sectionHref}
                                    linkState={linkState}
                                />
                            ) : null}
                            <div className="session-run__content">
                                {sections.map((section) => (
                                    <SectionPanel
                                        key={section.key}
                                        wide
                                        headingId={worldHeadingId(section.key)}
                                        label={section.label}
                                        purpose={section.purpose}
                                        active={section.key === nav.section}
                                    >
                                        {renderSection(section.key)}
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

// The reader's own panels, so an editor reads the same facts in the same words, with the way to
// edit them. Editing is offered only when the server says the record can be edited right now.
function DetailsSection({
    campaignId,
    category,
    kind,
    data,
    changes,
    editState,
}: {
    campaignId: string
    category: WorkspaceCategory
    kind: WorldKind
    data: WorkspaceDetail
    changes: number
    editState: object
}) {
    const root = `/app/${encodeURIComponent(campaignId)}`
    switch (category) {
        case "location": {
            const location = data as LocationDetail
            return (
                <>
                    <LocationPanels location={location} omitCurrentState={kind === "area"} />
                    <AuthoringEditLink
                        campaignId={campaignId}
                        noun={locationNoun(location)}
                        viewPath={locationViewPath(campaignId, location)}
                        editPath={locationEditPath(campaignId, location)}
                        detail={data}
                        linkState={editState}
                    />
                </>
            )
        }
        case "organization": {
            const organization = data as OrganizationDetail
            return (
                <>
                    <OrganizationPanels campaignId={campaignId} organization={organization} />
                    <AuthoringEditLink
                        campaignId={campaignId}
                        noun="organization"
                        viewPath={organizationAuthoringPath(campaignId, organization.organization_id)}
                        editPath={`${root}/world/organization/${encodeURIComponent(organization.organization_id)}/edit`}
                        detail={data}
                        linkState={editState}
                    />
                </>
            )
        }
        case "religion": {
            const religion = data as ReligionDetail
            return (
                <>
                    <ReligionPanels religion={religion} />
                    <AuthoringEditLink
                        campaignId={campaignId}
                        noun="religion"
                        viewPath={religionAuthoringPath(campaignId, religion.religion_id)}
                        editPath={`${root}/world/religion/${encodeURIComponent(religion.religion_id)}/edit`}
                        detail={data}
                        linkState={editState}
                    />
                </>
            )
        }
        case "character": {
            const character = data as CharacterDetail
            const id = character.character_id
            const editPath = `${root}/characters/${encodeURIComponent(id)}/edit`
            // Exactly one edit link, by the character's kind (and the portrayal link only for an
            // NPC); a bare character row has none.
            return (
                <>
                    <CharacterPanels character={character} />
                    {/* The sheet is its own page: linked, never embedded a second time here. */}
                    <p className="authoring-page__actions-row">
                        <Link className="authoring-button" to={`${root}/characters/${encodeURIComponent(id)}`}>
                            Open character sheet
                        </Link>
                    </p>
                    {character.character_kind === "npc" ? (
                        <AuthoringEditLink
                            campaignId={campaignId}
                            noun="NPC"
                            viewPath={npcAuthoringPath(campaignId, id)}
                            editPath={editPath}
                            detail={data}
                            linkState={editState}
                        />
                    ) : null}
                    {character.character_kind === "player_character" ? (
                        <AuthoringEditLink
                            campaignId={campaignId}
                            noun="player character"
                            viewPath={playerCharacterAuthoringPath(campaignId, id)}
                            editPath={editPath}
                            detail={data}
                            linkState={editState}
                        />
                    ) : null}
                    {/* How an NPC is played is an NPC's profile: a player character has none, and its read
                        would be a request for a record of another kind. */}
                    {character.character_kind === "npc" ? (
                        <PortrayalLink
                            campaignId={campaignId}
                            characterId={id}
                            detail={changes}
                            authoring={authoringOf(character)}
                        />
                    ) : null}
                    <BuildsLink campaignId={campaignId} characterId={id} />
                </>
            )
        }
    }
}

// Linking a player is done in Access, once the character is published. The link itself says when it
// is not yet possible; this says what the section is for, and why there may be no link.
function PlayerSection({ campaignId, characterId, version }: { campaignId: string; characterId: string; version: number }) {
    const canManage = useCampaignCapability(campaignId, "access.manage")
    return (
        <>
            <p className="authoring-note">
                A player character is controlled by one player. The player is linked in Access once the character is
                published.
            </p>
            <PlayerAccessLink campaignId={campaignId} characterId={characterId} detail={version} />
            {canManage ? null : (
                <p className="authoring-note">Linking a player needs permission to manage access.</p>
            )}
        </>
    )
}
