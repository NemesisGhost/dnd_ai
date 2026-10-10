import { useEffect, useRef, useState } from "react"
import type { ReactNode } from "react"
import { Link, useLocation } from "react-router"
import {
    fetchKnowledgeSubjectOptions,
    knowledgeAuthoringPath,
    knowledgeOptionsPath,
    updateKnowledgeItem,
} from "../api/knowledgeAuthoring"
import { entityLifecyclePath } from "../api/entityLifecycle"
import { provenancePath } from "../api/sources"
import { useAnnounce } from "../components/authoring/announcer"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { SelectField, TextAreaField, TextField } from "../components/authoring/fields"
import { ErrorSummary, MutationStatusMessage, StaleWriteNotice } from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { ReferenceCombobox } from "../components/authoring/ReferenceCombobox"
import type { ReferenceOption } from "../components/authoring/ReferenceCombobox"
import { LifecycleActionsProvider, LifecycleReviewAction } from "../components/EntityLifecyclePanel"
import { EntitySourcesSection } from "../components/EntitySourcesSection"
import { ClaimPublication } from "../components/knowledge/ClaimPublication"
import { ClaimReview } from "../components/knowledge/ClaimReview"
import {
    CLAIM_SECTIONS,
    CLAIM_STAGES,
    claimGuidance,
    claimHeadingId,
    claimSectionsOf,
    claimStageLabel,
    defaultClaimSection,
} from "../components/knowledge/claimStages"
import type { ClaimGuidance, ClaimSection } from "../components/knowledge/claimStages"
import { KnowledgeClaimHeader } from "../components/knowledge/KnowledgeClaimHeader"
import { KnowledgeRoster } from "../components/knowledge/KnowledgeRoster"
import type { Restriction } from "../components/knowledge/KnowledgeRoster"
import { useClaimNavigation } from "../components/knowledge/useClaimNavigation"
import { KnowledgeSubjectLink } from "../components/KnowledgeSubjectLink"
import { SectionNav, SectionPanel, StageNav } from "../components/staged/StagedNav"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { UseAuthoringResourceResult } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import type { KnowledgeDetail } from "../types/knowledge"
import type { EntityLifecycleView } from "../types/entityLifecycle"
import type { KnowledgeAuthoringView, KnowledgeOptions } from "../types/knowledgeAuthoring"
import type { Provenance } from "../types/provenance"
import { ERROR_CODE_MESSAGE, REASON_MAX, fieldForErrorCode } from "../utils/authoringValidation"
import { describeBlockedReason } from "../utils/blockedReason"
import { KnowledgeDetailsPanel } from "../components/knowledge/KnowledgeDetailsPanel"
import { characterKnowledgeOf } from "../utils/characterKnowledge"
import { humanizeCode } from "../utils/humanize"
import { canonStatusLabel } from "../utils/lifecycleNextStep"
import { FIELD, STATEMENT_MAX, fromView, same, toBody, validate } from "../utils/knowledgeForm"
import type { KnowledgeFormValues } from "../utils/knowledgeForm"
import { knowledgeSubjectHref } from "../utils/knowledgeSubject"
import { statusDetail } from "../utils/locationForm"
import "../components/authoring/authoring.css"

interface KnowledgeClaimPageProps {
    campaignId: string
    /** The claim in the address. Every request names this id with this campaign, never an id
     * copied back out of a response. */
    knowledgeItemId: string
    item: KnowledgeDetail
    /** The perspective this claim was requested under. */
    characterId: string | null
    partyId: string | null
    /** Re-reads the audience-safe detail in place after a claim save. */
    refreshDetail: () => void
}

const LOCK_REASON = "Someone already knows this claim, so this cannot change."

// Stands in for the lifecycle read while it is unavailable, so the one set of lifecycle actions
// stays mounted (and its dialogs with it) whether or not the read succeeded. It offers nothing.
const NO_LIFECYCLE = (knowledgeItemId: string): EntityLifecycleView => ({
    entity_id: knowledgeItemId,
    entity_type_code: "knowledge_item",
    canonical_name: "",
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 0,
    lifecycle_managed: false,
    superseded_by: null,
    available_actions: [],
    blocked_actions: [],
})

// The one Knowledge claim page: /app/:campaignId/knowledge/:knowledgeItemId. Its header always
// shows the claim, what it is about and the record's real status. People who may change canon get
// the Guided workspace under it: three presentation stages (Prepare, Review & publish, Use in
// play), each with its own sections, one section visible at a time. Everyone else gets the same
// facts as text, and anything they may not see is simply absent. Stages and sections are
// navigation only; the claim, each source change, each knowledge action and each lifecycle step
// save separately and never overwrite one another's unsaved work.
export function KnowledgeClaimPage({
    campaignId,
    knowledgeItemId,
    item,
    characterId,
    partyId,
    refreshDetail,
}: KnowledgeClaimPageProps) {
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    // The editor's own read model, the record's lifecycle and its provenance are loaded once here:
    // they feed the claim form, the header, the review summary and the roster's publication gate.
    const view = useAuthoringResource<KnowledgeAuthoringView>(
        canEdit ? knowledgeAuthoringPath(campaignId, knowledgeItemId) : null,
    )
    const options = useAuthoringResource<KnowledgeOptions>(canEdit ? knowledgeOptionsPath(campaignId) : null)
    const lifecycle = useAuthoringResource<EntityLifecycleView>(
        canEdit ? entityLifecyclePath(campaignId, knowledgeItemId) : null,
    )
    const provenance = useAuthoringResource<Provenance>(
        canEdit ? provenancePath(campaignId, knowledgeItemId) : null,
    )
    // The unsaved claim edits live here, above the claim form, so the lifecycle controls can say
    // plainly that they are not part of a submit, approve or publish, and so they survive the form
    // being replaced by a read-only presentation.
    const [changes, setChanges] = useState<Partial<KnowledgeFormValues>>({})
    const [changeNote, setChangeNote] = useState("")
    const [sourcesDirty, setSourcesDirty] = useState(false)
    const [rosterDirty, setRosterDirty] = useState(false)
    const base = view.state.kind === "ready" ? fromView(view.state.data) : null
    const claimDirty = base !== null && (!same({ ...base, ...changes }, base) || changeNote.trim() !== "")
    // What is typed and not yet saved, named for the guard below.
    const unsaved = [
        claimDirty ? "the claim" : null,
        sourcesDirty ? "a source" : null,
        rosterDirty ? "a knowledge entry" : null,
    ].filter((part) => part !== null)

    const status = view.state.kind === "ready" ? view.state.data : null
    const lifecycleView =
        lifecycle.state.kind === "ready" && lifecycle.state.data.lifecycle_managed ? lifecycle.state.data : null
    const canonStatus = lifecycleView?.canon_status ?? status?.canon_status ?? null
    const lifecycleStatus = lifecycleView?.lifecycle_status ?? status?.lifecycle_status ?? null
    // The default section needs the lifecycle read, so the workspace waits for it to settle.
    const settled = lifecycle.state.kind !== "loading"
    const nav = useClaimNavigation(defaultClaimSection(lifecycleView), { ready: settled, enabled: canEdit })
    const location = useLocation()

    // Move focus to the section heading when the section changes after arrival (a link, Back or
    // Forward), so a keyboard or screen reader user lands on the new content.
    const lastSection = useRef(nav.section)
    useEffect(() => {
        if (lastSection.current !== nav.section) {
            lastSection.current = nav.section
            document.getElementById(claimHeadingId(nav.section))?.focus()
        }
    }, [nav.section])

    const base0 = `/app/${encodeURIComponent(campaignId)}/knowledge`
    const perspective = new URLSearchParams()
    if (characterId !== null) perspective.set("character_id", characterId)
    if (partyId !== null) perspective.set("party_id", partyId)
    const perspectiveSearch = perspective.toString() === "" ? "" : `?${perspective.toString()}`
    const listHref = `${base0}${perspectiveSearch}`
    const claimHref = (id: string) => `${base0}/${encodeURIComponent(id)}${perspectiveSearch}`
    const replacement = lifecycleView?.superseded_by ?? null
    const replacementHref = replacement === null ? null : claimHref(replacement.entity_id)
    const subjectHref =
        item.subject == null ? null : knowledgeSubjectHref(campaignId, item.subject, characterId, partyId)

    const guidance = lifecycleView === null ? null : claimGuidance(lifecycleView)
    const hrefOf = (g: ClaimGuidance): string | null =>
        g.target.kind === "section"
            ? nav.sectionHref(g.target.section)
            : g.target.kind === "replacement"
              ? claimHref(g.target.entityId)
              : subjectHref

    // Only a published (canon, active) claim can have knowledge recorded or changed; the server
    // enforces it. Otherwise one note says why, and where the next step is.
    const restriction: Restriction | null =
        !canEdit || canonStatus === null || (canonStatus === "canon" && lifecycleStatus === "active")
            ? null
            : {
                  message:
                      lifecycleStatus === "archived" ? (
                          <>
                              This claim is archived. What was recorded is kept, but nothing new can be recorded or
                              changed until it is restored.{" "}
                              {lifecycleView !== null ? <Link to={nav.sectionHref("publication")}>Open Publication</Link> : null}
                          </>
                      ) : canonStatus === "superseded" ? (
                          <>
                              This claim was replaced
                              {replacement !== null ? (
                                  <>
                                      {" "}
                                      by{" "}
                                      {replacementHref !== null ? (
                                          <Link to={replacementHref}>{replacement.canonical_name}</Link>
                                      ) : (
                                          replacement.canonical_name
                                      )}
                                  </>
                              ) : null}
                              . What was recorded here is kept; record new knowledge on the replacement.
                          </>
                      ) : (
                          <>
                              Only a published claim can be recorded as known. This claim is{" "}
                              {canonStatusLabel(canonStatus)}.{" "}
                              {guidance !== null ? (
                                  <>
                                      Next:{" "}
                                      {hrefOf(guidance) !== null ? (
                                          <Link to={hrefOf(guidance) as string}>{guidance.text}</Link>
                                      ) : (
                                          guidance.text
                                      )}
                                  </>
                              ) : null}
                          </>
                      ),
              }

    const headerStatus =
        canEdit && canonStatus !== null && lifecycleStatus !== null
            ? {
                  canonStatus,
                  lifecycleStatus,
                  supersededBy:
                      replacement === null ? null : { entityId: replacement.entity_id, name: replacement.canonical_name },
              }
            : null

    const header = (
        <KnowledgeClaimHeader
            campaignId={campaignId}
            item={item}
            characterId={characterId}
            partyId={partyId}
            listHref={listHref}
            status={headerStatus}
            replacementHref={replacementHref}
            guidance={guidance}
            guidanceHref={guidance === null ? null : hrefOf(guidance)}
            canEdit={canEdit}
        />
    )

    if (!canEdit) {
        // Readers: the claim and what the server chose to show, then the selected character's
        // knowledge. No stages, no editor requests, and a `?section=` in the address is ignored.
        return (
            <section className="authoring-page knowledge-claim" aria-labelledby="knowledge-claim-heading">
                {header}
                <ClaimLayout
                    campaignId={campaignId}
                    item={item}
                    characterId={characterId}
                    partyId={partyId}
                    inPanel={false}
                    edit={null}
                    note={null}
                />
                <CharacterKnowledge item={item} characterId={characterId} heading />
            </section>
        )
    }

    const sourceCount =
        provenance.state.kind === "ready" ? provenance.state.data.links.filter((l) => l.is_attached).length : null
    const whoKnowsHref = nav.sectionHref("who-knows")
    const claimSectionHref = nav.sectionHref("claim")

    const body: Record<ClaimSection, ReactNode> = {
        claim: (
            <EditableClaim
                view={view}
                options={options}
                changes={changes}
                setChanges={setChanges}
                changeNote={changeNote}
                setChangeNote={setChangeNote}
                claimDirty={claimDirty}
                publicationHref={nav.sectionHref("publication")}
                replacement={replacement === null ? null : { name: replacement.canonical_name, href: replacementHref }}
                campaignId={campaignId}
                knowledgeItemId={knowledgeItemId}
                item={item}
                characterId={characterId}
                partyId={partyId}
                refreshDetail={refreshDetail}
            />
        ),
        sources: (
            <EntitySourcesSection
                compact
                hideHeading
                campaignId={campaignId}
                entityId={knowledgeItemId}
                category="knowledge"
                provenance={provenance}
                onDirtyChange={setSourcesDirty}
                returnTo={`${location.pathname}${nav.sectionHref("sources")}`}
                intro={
                    <p className="authoring-note">
                        Sources record where this claim came from. They are optional, can be changed at any status,
                        and do not affect review or publication. A written source cannot be edited; write a new one
                        and detach the old.
                    </p>
                }
            />
        ),
        review: (
            <ClaimReview
                view={status}
                options={options.state.kind === "ready" ? options.state.data : null}
                sourceCount={sourceCount}
                claimHref={claimSectionHref}
                sourcesHref={nav.sectionHref("sources")}
                unsavedEdits={claimDirty}
            >
                {lifecycleView !== null ? <LifecycleReviewAction /> : null}
            </ClaimReview>
        ),
        publication:
            lifecycleView !== null ? (
                <ClaimPublication
                    view={lifecycleView}
                    subject={
                        item.subject == null || subjectHref === null ? null : { name: item.subject.name, href: subjectHref }
                    }
                    whoKnowsHref={whoKnowsHref}
                    replacementHref={replacementHref}
                    claimHref={claimSectionHref}
                    unsavedEdits={claimDirty}
                />
            ) : (
                <p className="authoring-note" role="status">
                    The claim's lifecycle could not be loaded, so no step is shown. Reload the page to try again.
                </p>
            ),
        "who-knows": (
            <KnowledgeRoster
                campaignId={campaignId}
                knowledgeItemId={knowledgeItemId}
                restriction={restriction}
                onDirtyChange={setRosterDirty}
            />
        ),
        character: <CharacterKnowledge item={item} characterId={characterId} heading={false} />,
    }

    return (
        <section className="authoring-page knowledge-claim" aria-labelledby="knowledge-claim-heading">
            {header}
            {!settled ? (
                <p role="status">Loading the claim…</p>
            ) : (
                <LifecycleActionsProvider
                    campaignId={campaignId}
                    view={lifecycleView ?? NO_LIFECYCLE(knowledgeItemId)}
                    refetch={lifecycle.refetch}
                    unsavedEdits={claimDirty}
                    afterDeletePath={listHref}
                    onChanged={() => {
                        void view.refetch()
                        refreshDetail()
                    }}
                >
                    <StageNav
                        ariaLabel="Claim stages"
                        stages={CLAIM_STAGES}
                        current={nav.stage}
                        hrefFor={nav.stageHref}
                    />
                    <div className="session-run__layout">
                        <SectionNav
                            ariaLabel={`${claimStageLabel(nav.stage)} sections`}
                            sections={claimSectionsOf(nav.stage)}
                            current={nav.section}
                            hrefFor={nav.sectionHref}
                        />
                        <div className="session-run__content">
                            {CLAIM_SECTIONS.map((section) => (
                                <SectionPanel
                                    key={section.key}
                                    wide
                                    headingId={claimHeadingId(section.key)}
                                    label={section.label}
                                    purpose={section.purpose}
                                    active={section.key === nav.section}
                                >
                                    {body[section.key]}
                                </SectionPanel>
                            ))}
                        </div>
                    </div>
                </LifecycleActionsProvider>
            )}
            <UnsavedInputGuard unsaved={unsaved} />
        </section>
    )
}

// One guard for everything an editor has typed on the page and not yet saved (the claim, a source,
// a knowledge entry): leaving the page asks first, and so does closing the tab
// (docs/UI_DESIGN.md §5.11). Only mounted for editors; a reader has nothing to lose.
function UnsavedInputGuard({ unsaved }: { unsaved: string[] }) {
    const guard = useUnsavedChangesGuard(unsaved.length > 0)
    return (
        <ConfirmDialog
            open={guard.blocked}
            title="Discard unsaved changes?"
            description={`You have unsaved input in ${unsaved.join(" and ")}. It has not been saved.`}
            confirmLabel="Discard changes"
            cancelLabel="Keep editing"
            onConfirm={guard.discard}
            onCancel={guard.stay}
        />
    )
}

interface DraftBindings {
    changes: Partial<KnowledgeFormValues>
    setChanges: (changes: Partial<KnowledgeFormValues>) => void
    changeNote: string
    setChangeNote: (note: string) => void
}

// Why the claim cannot be edited right now, in one line, and the step that unlocks it.
function editBlockedNote(
    view: KnowledgeAuthoringView,
    replacement: { name: string; href: string | null } | null,
    publicationHref: string,
): ReactNode {
    const unlock = (text: string) => (
        <>
            {text} <Link to={publicationHref}>Open Publication</Link>
        </>
    )
    if (view.lifecycle_status === "archived") return unlock("This claim is archived. Restore it before editing.")
    switch (view.canon_status) {
        case "proposed":
            return unlock("This claim is in review. Return it to draft to edit it.")
        case "approved":
            return unlock("This claim is approved. Return it to draft to edit it.")
        case "rejected":
            return unlock("This claim is rejected. Return it to draft to rework it.")
        case "superseded":
            return replacement === null
                ? "This claim was replaced, so it can no longer be edited."
                : `This claim was replaced by ${replacement.name}, so it can no longer be edited.`
        default: {
            const reason = view.blocked_actions.find((b) => b.action === "update")?.reason
            return reason === undefined ? null : `Editing unavailable: ${describeBlockedReason(reason)}`
        }
    }
}

// Loads the editor's own read model. While it loads, or when editing is not offered, the same
// layout shows the values as text (with one line saying why editing is blocked).
function EditableClaim({
    view,
    options,
    changes,
    setChanges,
    changeNote,
    setChangeNote,
    claimDirty,
    publicationHref,
    replacement,
    ...props
}: KnowledgeClaimPageProps &
    DraftBindings & {
        view: UseAuthoringResourceResult<KnowledgeAuthoringView>
        options: UseAuthoringResourceResult<KnowledgeOptions>
        claimDirty: boolean
        publicationHref: string
        replacement: { name: string; href: string | null } | null
    }) {
    if (view.state.kind === "loading" || options.state.kind === "loading") {
        return <p role="status">Loading the claim…</p>
    }
    if (view.state.kind === "ready" && options.state.kind === "ready") {
        if (view.state.data.available_actions.includes("update")) {
            return (
                <ClaimForm
                    {...props}
                    changes={changes}
                    setChanges={setChanges}
                    changeNote={changeNote}
                    setChangeNote={setChangeNote}
                    view={view.state.data}
                    options={options.state.data}
                    refreshing={view.state.refreshing}
                    refetch={view.refetch}
                />
            )
        }
        const data = view.state.data
        const optionData = options.state.data
        return (
            <>
                <ClaimLayout
                    campaignId={props.campaignId}
                    item={props.item}
                    characterId={props.characterId}
                    partyId={props.partyId}
                    inPanel
                    edit={null}
                    note={editBlockedNote(data, replacement, publicationHref)}
                />
                {claimDirty ? (
                    <div className="authoring-message authoring-message--warning" role="status">
                        <div>
                            <p>
                                <strong>Unsaved changes not applied.</strong> This claim is{" "}
                                {data.lifecycle_status === "archived" ? "archived" : canonStatusLabel(data.canon_status)}
                                , so these changes cannot be saved now. They stay here; discard them, or make the
                                claim editable again to save them.
                            </p>
                            <DraftSummary
                                values={{ ...fromView(data), ...changes }}
                                options={optionData}
                                changeNote={changeNote}
                            />
                            <button
                                type="button"
                                className="authoring-button"
                                onClick={() => {
                                    setChanges({})
                                    setChangeNote("")
                                }}
                            >
                                Discard changes
                            </button>
                        </div>
                    </div>
                ) : null}
            </>
        )
    }
    return (
        <ClaimLayout
            campaignId={props.campaignId}
            item={props.item}
            characterId={props.characterId}
            partyId={props.partyId}
            inPanel
            edit={null}
            note={null}
        />
    )
}

interface EditBindings {
    values: KnowledgeFormValues
    setValues: (values: KnowledgeFormValues) => void
    options: KnowledgeOptions
    locked: boolean
    errorFor: (fieldId: string) => string | null
    canon: boolean
    changeNote: string
    setChangeNote: (note: string) => void
    searchSubjects: (query: string, signal: AbortSignal) => Promise<ReferenceOption[]>
    /** Save, Discard and their feedback; rendered at the end of the claim's own sections. */
    actions: ReactNode
}

function changedFields(base: KnowledgeFormValues, next: KnowledgeFormValues): Partial<KnowledgeFormValues> {
    const out: Partial<KnowledgeFormValues> = {}
    if (next.statement !== base.statement) out.statement = next.statement
    if (next.knowledgeType !== base.knowledgeType) out.knowledgeType = next.knowledgeType
    if (next.truthStatus !== base.truthStatus) out.truthStatus = next.truthStatus
    if (next.sensitivity !== base.sensitivity) out.sensitivity = next.sensitivity
    if ((next.subject?.id ?? null) !== (base.subject?.id ?? null)) out.subject = next.subject
    return out
}

const readable = (options: { value: string; label: string }[], value: string): string =>
    options.find((o) => o.value === value)?.label ?? humanizeCode(value)

// The edits that are held and not saved, as a list.
function DraftSummary({
    values,
    options,
    changeNote,
}: {
    values: KnowledgeFormValues
    options: KnowledgeOptions
    changeNote?: string
}) {
    return (
        <dl className="authoring-fact-list">
            <dt>Claim</dt>
            <dd>{values.statement || "(empty)"}</dd>
            <dt>Kind</dt>
            <dd>{readable(options.knowledge_types, values.knowledgeType)}</dd>
            <dt>Truth</dt>
            <dd>{readable(options.truth_statuses, values.truthStatus)}</dd>
            <dt>Sensitivity</dt>
            <dd>{readable(options.sensitivities, values.sensitivity)}</dd>
            <dt>Subject</dt>
            <dd>{values.subject?.label ?? "(none)"}</dd>
            {changeNote !== undefined && changeNote.trim() !== "" ? (
                <>
                    <dt>Change note</dt>
                    <dd>{changeNote.trim()}</dd>
                </>
            ) : null}
        </dl>
    )
}

// The claim's own fields. The header already states the claim and its subject, so the read-only
// presentation adds only the canonical facts (and the reason editing is blocked); the editable
// one adds the controls. What moves between them is only whether a value is a control or text.
function ClaimLayout({
    campaignId,
    item,
    characterId,
    partyId,
    inPanel,
    edit,
    note,
}: Pick<KnowledgeClaimPageProps, "campaignId" | "item" | "characterId" | "partyId"> & {
    // Inside a section panel the panel supplies the h2, so this one is a level lower.
    inPanel: boolean
    edit: EditBindings | null
    note: ReactNode
}) {
    const hasCanonical = item.truth_status_code !== null || item.sensitivity !== null
    const [changingSubject, setChangingSubject] = useState(false)
    const Heading = inPanel ? "h3" : "h2"

    const savedSubjectId = item.subject?.entity_id ?? null
    const draftSubjectChanged = edit !== null && (edit.values.subject?.id ?? null) !== savedSubjectId
    const subjectSelector =
        edit === null || edit.locked ? undefined : (
            <ReferenceCombobox
                id={FIELD.subject}
                label="Subject"
                value={null}
                onChange={(subject) => {
                    edit.setValues({ ...edit.values, subject })
                    setChangingSubject(false)
                }}
                search={edit.searchSubjects}
                error={edit.errorFor(FIELD.subject)}
                placeholder="Search places, organizations, religions, characters, quests"
            />
        )
    const subjectActions =
        edit === null || edit.locked ? undefined : (
            <>
                <button type="button" className="authoring-button" onClick={() => setChangingSubject(!changingSubject)}>
                    {changingSubject ? "Keep subject" : "Change subject"}
                </button>
                <button
                    type="button"
                    className="authoring-button"
                    onClick={() => {
                        edit.setValues({ ...edit.values, subject: null })
                        setChangingSubject(false)
                    }}
                >
                    Clear subject
                </button>
            </>
        )
    const lockedSubjectNote =
        edit !== null && edit.locked && edit.values.subject !== null ? (
            <p className="authoring-note">The subject cannot change: {LOCK_REASON.toLowerCase()}</p>
        ) : null
    const subjectError = edit?.errorFor(FIELD.subject) ?? null

    return (
        <>
            {note !== null ? (
                <p className="authoring-note" role="status">
                    {note}
                </p>
            ) : null}
            {edit !== null ? (
                <section id="claim" className="knowledge-claim__claim" aria-label="Claim">
                    <TextAreaField
                        id={FIELD.statement}
                        label="Claim"
                        hideLabel
                        className="knowledge-claim__textarea"
                        hint={edit.locked ? LOCK_REASON : undefined}
                        rows={3}
                        value={edit.values.statement}
                        onChange={(statement) => edit.setValues({ ...edit.values, statement })}
                        required
                        disabled={edit.locked}
                        maxLength={STATEMENT_MAX}
                        error={edit.errorFor(FIELD.statement)}
                    />
                </section>
            ) : null}

            {edit === null ? null : draftSubjectChanged ? (
                <div className="knowledge-about knowledge-about--claim">
                    <p className="knowledge-about__label">About this World entry</p>
                    <div className="knowledge-about__row">
                        <p className="knowledge-about__subject">
                            {edit.values.subject !== null ? (
                                <>
                                    <strong className="knowledge-about__name">{edit.values.subject.label}</strong>{" "}
                                    <span className="knowledge-about__type">not saved yet</span>
                                </>
                            ) : (
                                <span className="knowledge-about__type">No subject (not saved yet)</span>
                            )}
                        </p>
                        <div className="knowledge-about__actions">{subjectActions}</div>
                    </div>
                    {edit.values.subject === null || changingSubject ? subjectSelector : null}
                    {subjectError !== null && !changingSubject && edit.values.subject !== null ? (
                        <p className="authoring-field__error" role="alert">{subjectError}</p>
                    ) : null}
                    {lockedSubjectNote}
                </div>
            ) : item.subject !== null && item.subject !== undefined ? (
                <KnowledgeSubjectLink
                    campaignId={campaignId}
                    subject={item.subject}
                    characterId={characterId}
                    partyId={partyId}
                    variant="claim"
                    separateOpen
                    actions={subjectActions}
                >
                    {changingSubject ? subjectSelector : null}
                    {lockedSubjectNote}
                </KnowledgeSubjectLink>
            ) : (
                <div className="knowledge-about knowledge-about--claim">
                    <p className="knowledge-about__label">About this World entry</p>
                    {subjectSelector}
                    {lockedSubjectNote}
                </div>
            )}

            {edit !== null || hasCanonical ? (
                <section className="knowledge-gm" aria-labelledby="knowledge-canonical-heading">
                    <Heading id="knowledge-canonical-heading">GM and canonical information</Heading>
                    {edit === null ? (
                        <dl className="knowledge-gm__grid knowledge-gm__facts">
                            {inPanel ? (
                                <div>
                                    <dt>Kind</dt>
                                    <dd>{humanizeCode(item.knowledge_type_code)}</dd>
                                </div>
                            ) : null}
                            {item.truth_status_code !== null ? (
                                <div>
                                    <dt>Truth</dt>
                                    <dd>{humanizeCode(item.truth_status_code)}</dd>
                                </div>
                            ) : null}
                            {item.sensitivity !== null ? (
                                <div>
                                    <dt>Sensitivity</dt>
                                    <dd>{humanizeCode(item.sensitivity)}</dd>
                                </div>
                            ) : null}
                        </dl>
                    ) : (
                        <div className="knowledge-gm__grid">
                            <SelectField
                                id={FIELD.type}
                                label="Kind"
                                hint={edit.locked ? LOCK_REASON : undefined}
                                value={edit.values.knowledgeType}
                                placeholder="Choose a kind"
                                required
                                disabled={edit.locked}
                                options={edit.options.knowledge_types}
                                error={edit.errorFor(FIELD.type)}
                                onChange={(knowledgeType) => edit.setValues({ ...edit.values, knowledgeType })}
                            />
                            <SelectField
                                id={FIELD.truth}
                                label="Truth"
                                value={edit.values.truthStatus}
                                placeholder="Choose"
                                required
                                options={edit.options.truth_statuses}
                                error={edit.errorFor(FIELD.truth)}
                                onChange={(truthStatus) => edit.setValues({ ...edit.values, truthStatus })}
                            />
                            <SelectField
                                id={FIELD.sensitivity}
                                label="Sensitivity"
                                value={edit.values.sensitivity}
                                placeholder="Choose a sensitivity"
                                required
                                options={edit.options.sensitivities}
                                error={edit.errorFor(FIELD.sensitivity)}
                                onChange={(sensitivity) => edit.setValues({ ...edit.values, sensitivity })}
                            />
                            {edit.canon ? (
                                <div className="knowledge-gm__wide">
                                    <TextField
                                        id="change-note"
                                        label="Change note (optional)"
                                        value={edit.changeNote}
                                        onChange={edit.setChangeNote}
                                        maxLength={REASON_MAX}
                                        error={edit.errorFor("change-note")}
                                    />
                                </div>
                            ) : null}
                        </div>
                    )}
                    {edit !== null ? edit.actions : null}
                </section>
            ) : null}
        </>
    )
}

function CharacterKnowledge({
    item,
    characterId,
    heading,
}: {
    item: KnowledgeDetail
    characterId: string | null
    // The reader layout supplies its own heading; a section panel already has one.
    heading: boolean
}) {
    // The reader layout supplies the panel's own h2; inside a section panel it is one level lower.
    return (
        <KnowledgeDetailsPanel
            kindCode={item.knowledge_type_code}
            known={characterId === null ? undefined : characterKnowledgeOf(item)}
            headingLevel={heading ? 2 : 3}
            ariaLabel={heading ? undefined : "Character knowledge"}
        />
    )
}

function ClaimForm({
    campaignId,
    knowledgeItemId,
    item,
    characterId,
    partyId,
    refreshDetail,
    view,
    options,
    refreshing,
    refetch,
    changes,
    setChanges,
    changeNote,
    setChangeNote,
}: KnowledgeClaimPageProps &
    DraftBindings & {
        view: KnowledgeAuthoringView
        options: KnowledgeOptions
        refreshing: boolean
        refetch: () => Promise<void>
    }) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const base = fromView(view)
    // The unsaved claim edits (held by the page): only the fields the user changed. Everything else
    // follows the saved claim, so a refresh of it (or of a lifecycle change, a knowledge action or
    // a source) never overwrites an edit in progress.
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const [confirming, setConfirming] = useState(false)
    const [saved, setSaved] = useState(false)
    const values: KnowledgeFormValues = { ...base, ...changes }
    const setValues = (next: KnowledgeFormValues) => setChanges(changedFields(base, next))
    const dirty = !same(values, base) || changeNote.trim() !== ""
    const isCanon = view.canon_status === "canon"

    const mutation = useAuthoringMutation<
        ReturnType<typeof toBody> & { expected_row_version: number; change_note: string | null },
        unknown
    >({
        scopeKey: `edit-knowledge-claim:${knowledgeItemId}:${view.row_version}`,
        request: (body, ctx) => updateKnowledgeItem(campaignId, knowledgeItemId, body, ctx),
        onSuccess: async () => {
            setConfirming(false)
            await refetch()
            refreshDetail()
            setChanges({})
            setChangeNote("")
            setErrors([])
            setSaved(true)
            announce("Knowledge claim saved")
        },
    })
    const pending = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const serverField = error ? fieldForErrorCode(error.code) : null
    const serverErrors: FieldError[] =
        serverField !== null && error?.code
            ? [{ fieldId: serverField, message: ERROR_CODE_MESSAGE[error.code] ?? "Check this field." }]
            : []
    const noteError: FieldError[] =
        changeNote.trim().length > REASON_MAX
            ? [{ fieldId: "change-note", message: `Change note must be ${REASON_MAX} characters or fewer.` }]
            : []
    const all = [...errors, ...serverErrors]
    const errorFor = (fieldId: string) => all.find((e) => e.fieldId === fieldId)?.message ?? null

    function submitNow() {
        const note = changeNote.trim()
        mutation.submit({
            ...toBody(values),
            expected_row_version: view.row_version,
            change_note: note === "" ? null : note,
        })
    }

    function handleSubmit() {
        setSaved(false)
        const found = [...validate(values), ...noteError]
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        if (isCanon) {
            setConfirming(true)
            return
        }
        submitNow()
    }

    async function searchSubjects(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchKnowledgeSubjectOptions(campaignId, query, signal)
        return page.items.map((option) => ({
            id: option.entity_id,
            label: option.name,
            detail: `${option.kind.replace(/_/g, " ")}, ${statusDetail(option.canon_status, "active")}`,
        }))
    }

    const actions = (
        <>
            <ErrorSummary errors={all} attempt={attempt} />
            {error !== null && error.kind === "stale" ? (
                <StaleWriteNotice
                    loading={refreshing}
                    onLoadLatest={() => {
                        // Your edits stay in the form; only the saved version they build on is refreshed.
                        mutation.reset()
                        void refetch()
                    }}
                    yourChanges={<DraftSummary values={values} options={options} />}
                />
            ) : error !== null && serverField === null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            <div className="authoring-actions knowledge-claim__actions">
                <button
                    type="submit"
                    className="authoring-button authoring-button--primary"
                    disabled={pending || !dirty}
                    aria-busy={pending}
                >
                    {pending ? "Saving…" : "Save claim"}
                </button>
                <button
                    type="button"
                    className="authoring-button"
                    disabled={pending || !dirty}
                    aria-describedby="discard-claim-hint"
                    onClick={() => {
                        setChanges({})
                        setChangeNote("")
                        setErrors([])
                        mutation.reset()
                    }}
                >
                    Discard changes
                </button>
                <span className="knowledge-claim__state" role="status">
                    {dirty ? "Unsaved changes to the claim" : saved ? "Claim saved" : ""}
                </span>
            </div>
            <p id="discard-claim-hint" className="authoring-note">
                Claim changes and knowledge actions save independently.
            </p>
        </>
    )

    return (
        <form
            noValidate
            aria-label="Knowledge claim"
            className="knowledge-claim__form"
            onSubmit={(event) => {
                event.preventDefault()
                handleSubmit()
            }}
        >
            <ClaimLayout
                campaignId={campaignId}
                item={item}
                characterId={characterId}
                partyId={partyId}
                inPanel
                note={null}
                edit={{
                    values,
                    setValues,
                    options,
                    locked: view.in_use,
                    errorFor,
                    canon: isCanon,
                    changeNote,
                    setChangeNote,
                    searchSubjects,
                    actions,
                }}
            />
            <ConfirmDialog
                open={confirming && mutation.status.kind !== "error"}
                title="Save changes to a published claim?"
                description="This claim is published. People with access will see the change. For a change in meaning, create a replacement claim instead."
                confirmLabel="Save changes"
                cancelLabel="Keep editing"
                pending={pending}
                onConfirm={submitNow}
                onCancel={() => setConfirming(false)}
            />
        </form>
    )
}
