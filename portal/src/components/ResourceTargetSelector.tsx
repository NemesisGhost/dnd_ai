import { useEffect, useState } from "react"
import { useCampaignQuests } from "../hooks/useCampaignQuests"
import { useCampaignSessions } from "../hooks/useCampaignSessions"
import { useKnowledgeItems } from "../hooks/useKnowledgeItems"
import { useWorldEntities } from "../hooks/useWorldEntities"
import type { AssignableCharacter } from "../types/accessOverview"

export interface ResourceOption {
    id: string
    display_name: string
}

export interface ResourceTargetSelectorProps {
    campaignId: string
    targetType: string
    assignableCharacters: AssignableCharacter[]
    value: string
    disabled: boolean
    onChange: (option: ResourceOption | null) => void
    // The id of the caller's own <label>/<span> naming this control (e.g.
    // "Character", "Quest") — applied as aria-labelledby on the rendered
    // <select>, since each kind's own select id is generated internally
    // and the caller has no way to point a <label htmlFor> at it directly.
    labelId: string
}

interface PickerProps {
    value: string
    disabled: boolean
    onChange: (option: ResourceOption | null) => void
    labelId: string
}

// Every target kind reuses an existing audience-filtered, campaign.view-
// gated read contract 13D already delivered — never a new resource-
// directory endpoint, which would risk disclosing resources the actor
// cannot see (docs/UI_DESIGN.md §9). §5.3/P-8 of
// PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md: the "entity" selector
// deliberately excludes character/event/quest/knowledge_item categories
// from world/search, since each of those has its own dedicated target
// column and the backend now rejects an entity_id write for any of them.
function optionsFromIds<T>(
    items: T[],
    idOf: (item: T) => string,
    nameOf: (item: T) => string,
): ResourceOption[] {
    return items.map((item) => ({ id: idOf(item), display_name: nameOf(item) }))
}

// Selects the first option whenever the available list changes and the
// currently selected value is no longer (or never was) among them —
// mirrors AddResourceGrant's own pre-existing "reset the lower selection
// when a higher one changes" cascade, applied here to an asynchronously
// loaded list instead of a synchronous one.
function useAutoSelectFirst(
    options: ResourceOption[] | null,
    value: string,
    onChange: (option: ResourceOption | null) => void,
): void {
    useEffect(() => {
        if (options === null) {
            return
        }
        if (options.some((option) => option.id === value)) {
            return
        }
        onChange(options[0] ?? null)
        // Deliberately omits onChange/value from deps: this effect exists
        // only to react to a change in the resolved options list itself.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [options])
}

function ResourceSelect({
    labelId,
    options,
    value,
    disabled,
    onChange,
}: {
    labelId: string
    options: ResourceOption[]
    value: string
    disabled: boolean
    onChange: (option: ResourceOption | null) => void
}) {
    if (options.length === 0) {
        return <p>No eligible resource of this type is available.</p>
    }
    return (
        <select
            aria-labelledby={labelId}
            value={value}
            disabled={disabled}
            onChange={(event) => {
                const selected = options.find((option) => option.id === event.currentTarget.value)
                onChange(selected ?? null)
            }}
        >
            {options.map((option) => (
                <option key={option.id} value={option.id}>
                    {option.display_name}
                </option>
            ))}
        </select>
    )
}

function CharacterPicker({
    assignableCharacters,
    value,
    disabled,
    onChange,
    labelId,
}: PickerProps & { assignableCharacters: AssignableCharacter[] }) {
    const options = optionsFromIds(
        assignableCharacters,
        (character) => character.character_id,
        (character) => character.display_name,
    )
    useAutoSelectFirst(options, value, onChange)
    return (
        <ResourceSelect labelId={labelId} options={options} value={value} disabled={disabled} onChange={onChange} />
    )
}

function EntityPicker({
    campaignId,
    value,
    disabled,
    onChange,
    labelId,
}: PickerProps & { campaignId: string }) {
    const [query, setQuery] = useState("")
    const { state } = useWorldEntities(campaignId, null, query)
    const items =
        state.status === "success" || state.status === "refreshing"
            ? state.page.items.filter(
                  (item) =>
                      item.category === "location" ||
                      item.category === "organization" ||
                      item.category === "religion" ||
                      item.category === "item",
              )
            : null
    const options = items === null ? null : optionsFromIds(items, (item) => item.entity_id, (item) => item.name)
    useAutoSelectFirst(options, value, onChange)
    return (
        <>
            <input
                type="text"
                aria-label="Search locations, organizations, religions, and items"
                value={query}
                disabled={disabled}
                onChange={(event) => setQuery(event.currentTarget.value)}
            />
            {options === null ? (
                <p>Loading…</p>
            ) : (
                <ResourceSelect labelId={labelId} options={options} value={value} disabled={disabled} onChange={onChange} />
            )}
        </>
    )
}

function EventPicker({
    campaignId,
    value,
    disabled,
    onChange,
    labelId,
}: PickerProps & { campaignId: string }) {
    const [query, setQuery] = useState("")
    const { state } = useWorldEntities(campaignId, "event", query)
    const options =
        state.status === "success" || state.status === "refreshing"
            ? optionsFromIds(state.page.items, (item) => item.entity_id, (item) => item.name)
            : null
    useAutoSelectFirst(options, value, onChange)
    return (
        <>
            <input
                type="text"
                aria-label="Search events"
                value={query}
                disabled={disabled}
                onChange={(event) => setQuery(event.currentTarget.value)}
            />
            {options === null ? (
                <p>Loading…</p>
            ) : (
                <ResourceSelect labelId={labelId} options={options} value={value} disabled={disabled} onChange={onChange} />
            )}
        </>
    )
}

function KnowledgeItemPicker({
    campaignId,
    value,
    disabled,
    onChange,
    labelId,
}: PickerProps & { campaignId: string }) {
    const [query, setQuery] = useState("")
    // No character/party -- the canonical (ground-truth) projection,
    // reachable for a baseline GM (dnd_ai.queries.knowledge_browse.
    // list_knowledge's own docstring), the correct audience for an
    // access-management tool.
    const { state } = useKnowledgeItems(campaignId, "known", null, null, query, null)
    const options =
        state.status === "success" || state.status === "refreshing"
            ? optionsFromIds(
                  state.page.items,
                  (item) => item.knowledge_item_id,
                  (item) => item.statement,
              )
            : null
    useAutoSelectFirst(options, value, onChange)
    return (
        <>
            <input
                type="text"
                aria-label="Search knowledge items"
                value={query}
                disabled={disabled}
                onChange={(event) => setQuery(event.currentTarget.value)}
            />
            {options === null ? (
                <p>Loading…</p>
            ) : (
                <ResourceSelect labelId={labelId} options={options} value={value} disabled={disabled} onChange={onChange} />
            )}
        </>
    )
}

function QuestPicker({
    campaignId,
    value,
    disabled,
    onChange,
    labelId,
}: PickerProps & { campaignId: string }) {
    const { state } = useCampaignQuests(campaignId, null)
    const options =
        state.status === "success"
            ? optionsFromIds(state.quests, (quest) => quest.quest_id, (quest) => quest.name)
            : null
    useAutoSelectFirst(options, value, onChange)
    if (options === null) {
        return <p>Loading…</p>
    }
    return (
        <ResourceSelect labelId={labelId} options={options} value={value} disabled={disabled} onChange={onChange} />
    )
}

function SessionPicker({
    campaignId,
    value,
    disabled,
    onChange,
    labelId,
}: PickerProps & { campaignId: string }) {
    const { state } = useCampaignSessions(campaignId)
    const options =
        state.status === "success"
            ? optionsFromIds(
                  state.sessions,
                  (session) => session.session_id,
                  (session) => session.title ?? `Session ${session.session_number}`,
              )
            : null
    useAutoSelectFirst(options, value, onChange)
    if (options === null) {
        return <p>Loading…</p>
    }
    return (
        <ResourceSelect labelId={labelId} options={options} value={value} disabled={disabled} onChange={onChange} />
    )
}

// Switches over target kind, reusing four existing read hooks plus the
// overview's own assignable-character list -- one selector shared by the
// direct and group resource-grant forms (PHASE13E_REMAINING_
// IMPLEMENTATION_PLAN.md §8.5). Each kind renders through its own small
// component (never an if/else within one component body) specifically so
// only the currently selected kind's hook is ever mounted, satisfying the
// rules of hooks without firing four requests to populate one dropdown.
export function ResourceTargetSelector({
    campaignId,
    targetType,
    assignableCharacters,
    value,
    disabled,
    onChange,
    labelId,
}: ResourceTargetSelectorProps) {
    switch (targetType) {
        case "character":
            return (
                <CharacterPicker
                    assignableCharacters={assignableCharacters}
                    value={value}
                    disabled={disabled}
                    onChange={onChange}
                    labelId={labelId}
                />
            )
        case "entity":
            return (
                <EntityPicker
                    campaignId={campaignId}
                    value={value}
                    disabled={disabled}
                    onChange={onChange}
                    labelId={labelId}
                />
            )
        case "event":
            return (
                <EventPicker
                    campaignId={campaignId}
                    value={value}
                    disabled={disabled}
                    onChange={onChange}
                    labelId={labelId}
                />
            )
        case "knowledge_item":
            return (
                <KnowledgeItemPicker
                    campaignId={campaignId}
                    value={value}
                    disabled={disabled}
                    onChange={onChange}
                    labelId={labelId}
                />
            )
        case "quest":
            return (
                <QuestPicker
                    campaignId={campaignId}
                    value={value}
                    disabled={disabled}
                    onChange={onChange}
                    labelId={labelId}
                />
            )
        case "session":
            return (
                <SessionPicker
                    campaignId={campaignId}
                    value={value}
                    disabled={disabled}
                    onChange={onChange}
                    labelId={labelId}
                />
            )
        default:
            return null
    }
}
