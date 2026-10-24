import { useCallback, useEffect, useRef, useState } from "react"
import type { ReactNode } from "react"
import { Link, useLocation, useSearchParams } from "react-router"
import { entityLifecyclePath } from "../../api/entityLifecycle"
import { questAuthoringPath, questOptionsPath } from "../../api/questAuthoring"
import { revisionsPath } from "../../api/review"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import type { UseAuthoringResourceResult } from "../../hooks/useAuthoringResource"
import { useCampaignCapability } from "../../hooks/useCampaignCapability"
import { usePageArrival } from "../../hooks/usePageArrival"
import { pickWorldReturnState, useReviewBackPath } from "../../hooks/useWorldBackPath"
import type { EntityLifecycleView } from "../../types/entityLifecycle"
import type { QuestAuthoringView, QuestOptions } from "../../types/questAuthoring"
import type { RevisionHistory } from "../../types/review"
import { questPerspectiveSearch } from "../../utils/questPerspectiveSearch"
import { QuestStructureEditor } from "../authoring/QuestEditor"
import { AudiencePreviewSection } from "../AudiencePreviewSection"
import { LifecycleActionsProvider } from "../EntityLifecyclePanel"
import { EntitySourcesSection } from "../EntitySourcesSection"
import { SectionNav, SectionPanel, StageNav } from "../staged/StagedNav"
import { UnsavedInputGuard } from "../staged/UnsavedInputGuard"
import { useStagedNavigation } from "../staged/useStagedNavigation"
import { WorldPublicationSection } from "../world/WorldPublication"
import { WorldRecordHeader } from "../world/WorldRecordHeader"
import { WorldReviewSection } from "../world/WorldReviewSection"
import { worldHistoryPath } from "../world/worldPaths"
import { QuestDependencies, QuestOutcomes, QuestParticipants } from "./QuestCompletionSections"
import { QuestDetailsSection } from "./QuestDetailsSection"
import { QuestProgressPanel } from "./QuestProgressPanel"
import { QuestReviewSummary } from "./QuestReviewSummary"
import {
    QUEST_PHASE_LABELS,
    defaultQuestSection,
    questGuidance,
    questHeadingId,
    questPhasesOf,
    questPlayBlockedText,
    questSectionsInPhase,
    questSectionsOf,
} from "./questPhases"
import type { QuestSection } from "./questPhases"
import "../authoring/authoring.css"

const PUBLISHED_TEXT =
    "Published. Players see it only once it is activated for the campaign or for their party, and then only the objectives its visibility allows. Running it is in Use in play."

// Stands in for the lifecycle read while it is unavailable, so the one set of lifecycle actions
// stays mounted whether or not the read succeeded. It offers nothing.
const NO_LIFECYCLE = (entityId: string): EntityLifecycleView => ({
    entity_id: entityId,
    entity_type_code: "quest",
    canonical_name: "",
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 0,
    lifecycle_managed: false,
    superseded_by: null,
    available_actions: [],
    blocked_actions: [],
})

const enc = encodeURIComponent
const questsPath = (campaignId: string): string => `/app/${enc(campaignId)}/quests`

interface Props {
    campaignId: string
    questId: string
}

// The editor's page for a quest. Mounts nothing, and sends nothing, for anyone without `canon.edit`;
// they get the quest reader. It is a guided workspace like the item page, the Knowledge claim and
// the World record workspace: workflow phases (Prepare, Review & publish, Use in play) and their
// sections organise the interface only. They are links that change the address, never call the API
// and never change or imply a status. Three things stay apart: these phases, the quest's own stages
// and objectives (the authored adventure), and progress (what has happened in play). The record's
// real status is in the header. All sections stay mounted once shown, so what was typed in one
// survives switching to another, and each keeps its own saves.
export function QuestWorkspace(props: Props) {
    if (!useCampaignCapability(props.campaignId, "canon.edit")) return null
    return <Loaded {...props} />
}

function Loaded({ campaignId, questId }: Props) {
    const authoring = useAuthoringResource<QuestAuthoringView>(questAuthoringPath(campaignId, questId))
    const options = useAuthoringResource<QuestOptions>(questOptionsPath(campaignId))
    const lifecycle = useAuthoringResource<EntityLifecycleView>(entityLifecyclePath(campaignId, questId))
    const revisions = useAuthoringResource<RevisionHistory>(revisionsPath(campaignId, questId))
    const headingRef = usePageArrival(authoring.state.kind === "ready" && options.state.kind === "ready", "path")
    // The last quest read that succeeded. A refresh that fails recoverably (a network or server
    // error) keeps the workspace mounted on it, so unsent input in any section survives and the
    // person can retry; a denied or unavailable answer discards it and fails closed.
    const [kept, setKept] = useState<QuestAuthoringView | null>(null)
    if (authoring.state.kind === "ready" && kept !== authoring.state.data) setKept(authoring.state.data)
    if ((authoring.state.kind === "denied" || authoring.state.kind === "unavailable") && kept !== null) setKept(null)
    const stale = authoring.state.kind === "error" && kept !== null
    const back = questsPath(campaignId)

    if (authoring.state.kind === "loading" || (authoring.state.kind === "ready" && options.state.kind === "loading")) {
        return (
            <section className="authoring-page" aria-label="Quest">
                <p role="status">Loading quest…</p>
            </section>
        )
    }
    const view = authoring.state.kind === "ready" ? authoring.state.data : stale ? kept : null
    if (view === null || options.state.kind !== "ready") {
        const missing = authoring.state.kind === "unavailable" || authoring.state.kind === "denied"
        return (
            <section className="authoring-page" aria-labelledby="quest-workspace-heading">
                <p>
                    <Link to={back}>Back to Quests</Link>
                </p>
                <h1 id="quest-workspace-heading" ref={headingRef} tabIndex={-1}>
                    {missing ? "Quest unavailable" : "Quest information unavailable"}
                </h1>
                <p role="alert">
                    {missing
                        ? "This quest does not exist, or you do not have access to it."
                        : "The quest could not be loaded. Try again."}
                </p>
                {missing ? null : (
                    <button
                        type="button"
                        className="authoring-button"
                        onClick={() => {
                            void authoring.refetch()
                            void options.refetch()
                        }}
                    >
                        Try again
                    </button>
                )}
            </section>
        )
    }
    return (
        <Workspace
            campaignId={campaignId}
            questId={questId}
            view={view}
            options={options.state.data}
            refreshing={authoring.state.kind === "ready" && authoring.state.refreshing}
            refreshFailed={stale}
            refetchQuest={authoring.refetch}
            lifecycle={lifecycle}
            revisions={revisions}
            headingRef={headingRef}
        />
    )
}

function Workspace({
    campaignId,
    questId,
    view,
    options,
    refreshing,
    refreshFailed,
    refetchQuest,
    lifecycle,
    revisions,
    headingRef,
}: Props & {
    view: QuestAuthoringView
    options: QuestOptions
    refreshing: boolean
    // The last refresh failed; `view` is the last read that succeeded.
    refreshFailed: boolean
    refetchQuest: () => Promise<unknown>
    lifecycle: UseAuthoringResourceResult<EntityLifecycleView>
    revisions: UseAuthoringResourceResult<RevisionHistory>
    headingRef: ReturnType<typeof usePageArrival>
}) {
    const location = useLocation()
    const [params] = useSearchParams()
    // Router state naming where the quest was opened from (the Review queue) rides along every
    // in-page link, so moving between sections never forgets where Back returns.
    const linkState = pickWorldReturnState(location.state)
    const reviewBack = useReviewBackPath(campaignId)
    const back = reviewBack !== null
        ? { href: reviewBack, label: "Back to Review queue" }
        : {
              href: `${questsPath(campaignId)}${questPerspectiveSearch(params.get("character_id"), params.get("party_id"))}`,
              label: "Back to Quests",
          }
    const canPreview = useCampaignCapability(campaignId, "access.manage")

    const settled = lifecycle.state.kind !== "loading"
    const lifecycleView =
        lifecycle.state.kind === "ready" && lifecycle.state.data.lifecycle_managed ? lifecycle.state.data : null
    const sections = questSectionsOf({ canPreview })
    const nav = useStagedNavigation(sections.map((s) => ({ key: s.key, stage: s.phase })), defaultQuestSection(lifecycleView), { ready: settled })
    const hasObjective = view.stages.some((s) => s.objectives.length > 0)
    const guidance = lifecycleView === null ? null : questGuidance(lifecycleView, {
        canEdit: view.available_actions.includes("update"),
        hasObjective,
    })
    const guidanceHref =
        guidance === null
            ? null
            : guidance.target.kind === "section"
              ? nav.sectionHref(guidance.target.section)
              : `${questsPath(campaignId)}/${enc(guidance.target.entityId)}`

    // How many times the quest was changed from this page, for the panel that reads progress
    // itself and must be read again in place.
    const [changes, setChanges] = useState(0)
    // Every command reads the quest, its lifecycle (the next lifecycle step carries the version it
    // saw) and its revisions again. Nothing is remounted, so nothing typed elsewhere is lost.
    const refreshRecord = useCallback(
        async () => void (await Promise.all([refetchQuest(), lifecycle.refetch(), revisions.refetch()])),
        [refetchQuest, lifecycle, revisions],
    )
    const refreshAll = useCallback(async () => {
        setChanges((n) => n + 1)
        await refreshRecord()
    }, [refreshRecord])

    // What is typed and not sent, by reporter, for the page's one guard.
    const [unsaved, setUnsaved] = useState<Record<string, string[]>>({})
    const report = useCallback((source: string, labels: string[]) => {
        setUnsaved((current) => {
            const before = current[source] ?? []
            if (before.join("|") === labels.join("|")) return current
            const next = { ...current }
            if (labels.length === 0) delete next[source]
            else next[source] = labels
            return next
        })
    }, [])
    const reportSource = useCallback((dirty: boolean) => report("sources", dirty ? ["a source"] : []), [report])
    const unsavedLabels = [...new Set(Object.values(unsaved).flat())]

    // The sections that read the timeline are mounted when the person first opens Use in play (a
    // draft quest should not cost a progress request), and stay mounted from then on.
    const [playSeen, setPlaySeen] = useState(false)
    if (!playSeen && nav.stage === "play") setPlaySeen(true)

    // Move focus to the section heading when the section changes after arrival (a link, Back or
    // Forward), so a keyboard or screen reader user lands on the new content.
    // The section the page settled on is the arrival (focus stays on the page heading); only a
    // later change moves focus.
    const lastSection = useRef<QuestSection | null>(null)
    useEffect(() => {
        if (!settled) return
        if (lastSection.current === null) {
            lastSection.current = nav.section
        } else if (lastSection.current !== nav.section) {
            lastSection.current = nav.section
            document.getElementById(questHeadingId(nav.section))?.focus()
        }
    }, [settled, nav.section])

    const here = location.pathname
    const sectionHref = (key: QuestSection): string => nav.sectionHref(key)
    const historyHref = worldHistoryPath(campaignId, "record", questId)
    const common = { campaignId, view, options, refetch: refreshAll, onUnsaved: report }

    function renderSection(key: QuestSection): ReactNode {
        switch (key) {
            case "details":
                return (
                    <QuestDetailsSection
                        {...common}
                        refreshing={refreshing}
                        publicationHref={sectionHref("publication")}
                        linkState={linkState}
                    />
                )
            case "structure":
                return <QuestStructureEditor {...common} refreshing={refreshing} />
            case "dependencies":
                return <QuestDependencies {...common} />
            case "outcomes":
                return <QuestOutcomes {...common} />
            case "participants":
                return <QuestParticipants {...common} />
            case "sources":
                return (
                    <EntitySourcesSection
                        embedded
                        campaignId={campaignId}
                        entityId={questId}
                        onDirtyChange={reportSource}
                        returnTo={`${here}${sectionHref("sources")}`}
                        returnState={linkState}
                        intro={
                            <p className="authoring-note">
                                Sources record where this quest came from. They are optional, can be changed at any
                                status, and do not affect review or publication. A written source cannot be edited;
                                write a new one and detach the old.
                            </p>
                        }
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
                        publishedText={PUBLISHED_TEXT}
                        summary={<QuestReviewSummary view={view} options={options} />}
                    />
                )
            case "publication":
                return (
                    <WorldPublicationSection
                        lifecycleView={lifecycleView}
                        historyHref={historyHref}
                        linkState={linkState}
                        onRetry={() => void lifecycle.refetch()}
                        publishedText={PUBLISHED_TEXT}
                    />
                )
            case "progress":
                return playSeen ? (
                    <QuestProgressPanel
                        campaignId={campaignId}
                        questId={questId}
                        // Unknown status (the lifecycle read failed) is not eligibility: withhold the commands.
                        blockedText={
                            lifecycleView === null
                                ? "The quest's status could not be loaded, so running it is not offered."
                                : questPlayBlockedText(lifecycleView)
                        }
                        refreshToken={changes}
                        onUnsaved={report}
                        // A progress command can lock the structure (the quest now has progress): read the
                        // quest again, in place. Progress itself was already read, so it is not read twice.
                        onChanged={refreshRecord}
                    />
                ) : null
            case "preview":
                return playSeen ? (
                    <>
                        <p className="authoring-note">
                            A member sees a quest only once it has been activated for the campaign or for their
                            party, so a published quest that has not started reads as not visible to them. Choosing
                            a member here changes nothing.
                        </p>
                        <AudiencePreviewSection
                            campaignId={campaignId}
                            resourceType="quest"
                            fixedResource={{ id: questId, display_name: view.name }}
                        />
                    </>
                ) : null
        }
    }

    const phases = questPhasesOf(sections)
    const inPhase = questSectionsInPhase(sections, nav.stage)
    return (
        <section className="authoring-page item-workspace" aria-labelledby="quest-workspace-heading">
            <WorldRecordHeader
                headingId="quest-workspace-heading"
                name={view.name}
                eyebrow="Quest"
                summary={view.summary}
                status={lifecycleView}
                back={back}
                headingRef={headingRef}
                guidance={guidance}
                guidanceHref={guidanceHref}
                linkState={linkState}
            />
            {refreshFailed ? (
                <div className="authoring-message authoring-message--warning" role="alert">
                    <p>
                        The latest information could not be loaded, so what is shown may be out of date. What you
                        have typed is kept.
                    </p>
                    <button type="button" className="authoring-button" onClick={() => void refetchQuest()}>
                        Try again
                    </button>
                </div>
            ) : null}
            {!settled ? (
                <p role="status">Loading the record…</p>
            ) : (
                <LifecycleActionsProvider
                    campaignId={campaignId}
                    view={lifecycleView ?? NO_LIFECYCLE(questId)}
                    refetch={lifecycle.refetch}
                    afterDeletePath={reviewBack ?? questsPath(campaignId)}
                    onChanged={() => void refreshAll()}
                >
                    <StageNav
                        ariaLabel="Quest workflow"
                        stages={phases.map((phase) => ({ key: phase, label: QUEST_PHASE_LABELS[phase] }))}
                        current={nav.stage}
                        hrefFor={nav.stageHref}
                        linkState={linkState}
                    />
                    <div className="staged-workspace">
                        <div
                            className={
                                inPhase.length > 1 ? "session-run__layout" : "session-run__layout session-run__layout--single"
                            }
                        >
                            {inPhase.length > 1 ? (
                                <SectionNav
                                    ariaLabel={`${QUEST_PHASE_LABELS[nav.stage]} sections`}
                                    sections={inPhase}
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
                                        headingId={questHeadingId(section.key)}
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
            <UnsavedInputGuard unsaved={unsavedLabels} />
        </section>
    )
}
