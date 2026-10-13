import { useEffect, useRef, useState } from "react"
import type { ReactNode, RefObject } from "react"
import { Link, useLocation } from "react-router"
import { entityLifecyclePath } from "../../api/entityLifecycle"
import { npcAuthoringPath } from "../../api/npcAuthoring"
import { organizationAuthoringPath, religionAuthoringPath } from "../../api/organizationAuthoring"
import { playerCharacterAuthoringPath } from "../../api/playerCharacterAuthoring"
import { provenancePath } from "../../api/sources"
import { revisionsPath } from "../../api/review"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import type { UseAuthoringResourceResult } from "../../hooks/useAuthoringResource"
import { useCampaignCapability } from "../../hooks/useCampaignCapability"
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
import { AreaNowSection } from "./AreaNowSection"
import { DungeonStructureSection } from "./DungeonStructureSection"
import { locationEditPath, locationNoun, locationViewPath } from "./placePaths"
import { WorldPublicationSection } from "./WorldPublication"
import { WorldRecordHeader } from "./WorldRecordHeader"
import { WorldReviewSection } from "./WorldReviewSection"
import {
    WORLD_STAGE_LABELS,
    defaultWorldSection,
    playBlockedText,
    worldGuidance,
    worldHeadingId,
    worldKindOf,
    worldSectionsInStage,
    worldSectionsOf,
    worldStagesOf,
} from "./worldStages"
import type { WorkspaceCategory, WorldKind, WorldSection } from "./worldStages"
import { worldDetailPath, worldHistoryPath } from "./worldPaths"
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
    const lifecycle = useAuthoringResource<EntityLifecycleView>(entityLifecyclePath(campaignId, entityId))
    const provenance = useAuthoringResource<Provenance>(provenancePath(campaignId, entityId))
    const revisions = useAuthoringResource<RevisionHistory>(revisionsPath(campaignId, entityId))
    const worldBack = useWorldBackPath(campaignId)
    const headingRef = usePageArrival(detail.state.kind === "ready", "path")
    // The last read that succeeded for this record. A refresh that fails recoverably (a network or
    // server error) keeps the workspace mounted on it, so unsent input in any section survives and
    // the person can retry; a denied or unavailable answer, or a loading state, discards it and
    // fails closed. The workspace is keyed by record, so this never outlives it.
    const [kept, setKept] = useState<WorkspaceDetail | null>(null)
    if (detail.state.kind === "ready" && kept !== detail.state.data) setKept(detail.state.data)
    if ((detail.state.kind === "denied" || detail.state.kind === "unavailable") && kept !== null) setKept(null)
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
        <Workspace
            campaignId={campaignId}
            category={category}
            entityId={entityId}
            data={detail.state.kind === "ready" ? detail.state.data : (kept as WorkspaceDetail)}
            refreshFailed={stale}
            refetchDetail={detail.refetch}
            lifecycle={lifecycle}
            provenance={provenance}
            revisions={revisions}
            headingRef={headingRef}
        />
    )
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
    headingRef,
}: Props & {
    data: WorkspaceDetail
    // The last refresh failed; `data` is the last read that succeeded.
    refreshFailed: boolean
    refetchDetail: () => Promise<void>
    lifecycle: UseAuthoringResourceResult<EntityLifecycleView>
    provenance: UseAuthoringResourceResult<Provenance>
    revisions: UseAuthoringResourceResult<RevisionHistory>
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
    const kind = worldKindOf(category, lifecycleView?.entity_type_code ?? null)
    const sections = worldSectionsOf(kind)
    const nav = useStagedNavigation(sections, defaultWorldSection(lifecycleView), { ready: settled && !unmanaged })
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

    const unsaved = [sourcesDirty ? "a source" : null].filter((part) => part !== null)
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
            case "structure":
                return (
                    <DungeonStructureSection
                        campaignId={campaignId}
                        dungeonId={entityId}
                        refreshToken={data}
                        linkState={linkState}
                        editHref={locationEditPath(campaignId, data as LocationDetail)}
                        editState={editStateFor("structure")}
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
                return <RelationshipsPanel embedded campaignId={campaignId} entityId={entityId} />
            case "review":
                return (
                    <WorldReviewSection
                        lifecycleView={lifecycleView}
                        revisions={revisions}
                        historyHref={historyHref}
                        detailsHref={sectionHref("details")}
                        publicationHref={sectionHref("publication")}
                        linkState={linkState}
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
            case "area-now":
                return (
                    <AreaNowSection
                        location={data as LocationDetail}
                        lifecycleView={lifecycleView}
                        editHref={locationEditPath(campaignId, data as LocationDetail)}
                        editState={editStateFor("area-now")}
                    />
                )
            case "members": {
                // Unknown status (the lifecycle read failed) is not eligibility: withhold the commands.
                const blocked =
                    lifecycleView === null
                        ? `The ${playNoun}'s status could not be loaded, so recording members or a status is not offered.`
                        : playBlockedText(lifecycleView, playNoun)
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
                        blockedText={playBlockedText(lifecycleView, "NPC")}
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

    const stages = worldStagesOf(kind)
    const inStage = worldSectionsInStage(kind, nav.stage)
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
            />
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
                        stages={stages.map((stage) => ({ key: stage, label: WORLD_STAGE_LABELS[stage] }))}
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
            // Each kind's authoring read is a 404 for the other, so exactly one edit link can
            // appear (and the portrayal link only for an NPC).
            return (
                <>
                    <CharacterPanels character={character} />
                    <AuthoringEditLink
                        campaignId={campaignId}
                        noun="NPC"
                        viewPath={npcAuthoringPath(campaignId, id)}
                        editPath={editPath}
                        detail={data}
                        linkState={editState}
                    />
                    <AuthoringEditLink
                        campaignId={campaignId}
                        noun="player character"
                        viewPath={playerCharacterAuthoringPath(campaignId, id)}
                        editPath={editPath}
                        detail={data}
                        linkState={editState}
                    />
                    <PortrayalLink campaignId={campaignId} characterId={id} detail={changes} />
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
